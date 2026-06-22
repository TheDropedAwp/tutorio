from contextlib import asynccontextmanager
from datetime import date
from hashlib import sha256
import os
from pathlib import Path
from secrets import token_hex
from shutil import copyfileobj

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import inspect, or_, select, text
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import Booking, CalendarSlot, Listing, Message, Notification, Review, ScheduleSlot, User

root_dir = Path(__file__).resolve().parent.parent
static_dir = root_dir / "static"
upload_dir = static_dir / "uploads"
upload_dir.mkdir(parents=True, exist_ok=True)

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@tutorio-school.ru")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
AUTO_SEED_ON_STARTUP = os.getenv("AUTO_SEED_ON_STARTUP", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def ensure_schema() -> None:
    """Tiny dev migration helper for the local SQLite fallback."""
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    message_columns = {column["name"] for column in inspector.get_columns("messages")}
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    with engine.begin() as connection:
        if "image_url" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN image_url VARCHAR(500) DEFAULT ''"))
        if "is_blocked" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN is_blocked BOOLEAN DEFAULT false"))


def ensure_admin() -> None:
    if not ADMIN_PASSWORD:
        print("ADMIN_PASSWORD is not set. Skipping admin seed.")
        return

    with Session(engine) as db:
        admin = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        if not admin:
            admin = User(
                name="Администратор",
                email=ADMIN_EMAIL,
                password_hash=hash_password(ADMIN_PASSWORD),
                role="admin",
                city="",
                bio="Администратор платформы Tutorio.",
                avatar_url="",
                token=token_hex(24),
            )
            db.add(admin)
        else:
            admin.password_hash = hash_password(ADMIN_PASSWORD)
            admin.role = "admin"
            admin.is_blocked = False
            if not admin.token:
                admin.token = token_hex(24)
        db.commit()


def hash_password(password: str) -> str:
    return sha256(password.encode("utf-8")).hexdigest()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    if AUTO_SEED_ON_STARTUP:
        try:
            ensure_admin()
        except Exception as exc:
            print(f"Admin seed skipped: {exc}")
    yield


app = FastAPI(title="Tutorio", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


def notify(db: Session, user_id: int, title: str, body: str = "") -> None:
    db.add(Notification(user_id=user_id, title=title, body=body))


def current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> User:
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        raise HTTPException(401, "Нужна авторизация")
    user = db.scalar(select(User).where(User.token == token))
    if not user:
        raise HTTPException(401, "Сессия не найдена")
    if user.is_blocked and user.role != "admin":
        raise HTTPException(403, "Аккаунт заблокирован")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Нужны права администратора")
    return user


def can_tutor(user: User) -> bool:
    return user.role in {"tutor", "admin"}


def can_student(user: User) -> bool:
    return user.role in {"student", "admin"}


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6)
    role: str = Field(pattern="^(student|tutor)$")
    city: str = Field(default="", max_length=80)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ProfileIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    city: str = Field(default="", max_length=80)
    bio: str = Field(default="", max_length=3000)
    avatar_url: str = Field(default="", max_length=500)


class ListingIn(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    subject: str = Field(min_length=2, max_length=80)
    price: int = Field(ge=0, le=1_000_000)
    format: str = Field(default="Онлайн", max_length=40)
    level: str = Field(default="", max_length=80)
    description: str = Field(min_length=10, max_length=5000)
    image_url: str = Field(default="", max_length=500)


def validate_date(value: str) -> str:
    try:
        parts = value.split("-")
        if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
            raise ValueError
        year, month, day = map(int, parts)
        date(year, month, day)
    except (TypeError, ValueError):
        raise ValueError("Дата должна быть в формате ГГГГ-ММ-ДД")
    return value


def validate_time(value: str) -> str:
    try:
        parts = value.split(":")
        if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 2:
            raise ValueError
        hour, minute = map(int, parts)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("Время должно быть в формате ЧЧ:ММ")
    return value


class WeeklySlotIn(BaseModel):
    weekday: int = Field(ge=0, le=6)
    starts_at: str
    ends_at: str
    is_available: bool = True

    @field_validator("starts_at", "ends_at")
    @classmethod
    def time_format(cls, value: str) -> str:
        return validate_time(value)

    @model_validator(mode="after")
    def time_order(self):
        if self.starts_at >= self.ends_at:
            raise ValueError("Время начала должно быть раньше времени окончания")
        return self


class CalendarSlotIn(BaseModel):
    slot_date: str
    starts_at: str
    ends_at: str
    is_available: bool = True

    @field_validator("slot_date")
    @classmethod
    def date_format(cls, value: str) -> str:
        return validate_date(value)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def time_format(cls, value: str) -> str:
        return validate_time(value)

    @model_validator(mode="after")
    def time_order(self):
        if self.starts_at >= self.ends_at:
            raise ValueError("Время начала должно быть раньше времени окончания")
        return self


class BookingIn(BaseModel):
    listing_id: int
    requested_date: str
    requested_time: str
    note: str = Field(default="", max_length=2000)

    @field_validator("requested_date")
    @classmethod
    def date_format(cls, value: str) -> str:
        return validate_date(value)

    @field_validator("requested_time")
    @classmethod
    def time_format(cls, value: str) -> str:
        return validate_time(value)


class BookingDecisionIn(BaseModel):
    status: str = Field(pattern="^(accepted|declined|alternative)$")
    alternative_date: str = ""
    alternative_time: str = ""

    @field_validator("alternative_date")
    @classmethod
    def optional_date_format(cls, value: str) -> str:
        return validate_date(value) if value else value

    @field_validator("alternative_time")
    @classmethod
    def optional_time_format(cls, value: str) -> str:
        return validate_time(value) if value else value


class MessageIn(BaseModel):
    recipient_id: int
    listing_id: int | None = None
    body: str = Field(default="", max_length=4000)
    image_url: str = Field(default="", max_length=500)


class ReviewIn(BaseModel):
    tutor_id: int
    rating: int = Field(ge=1, le=5)
    body: str = Field(min_length=3, max_length=3000)


class BlockUserIn(BaseModel):
    is_blocked: bool


def public_user(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "is_blocked": user.is_blocked,
        "city": user.city,
        "bio": user.bio,
        "avatar_url": user.avatar_url,
        "created_at": user.created_at,
    }


def public_listing(listing: Listing) -> dict:
    tutor = listing.tutor
    return {
        "id": listing.id,
        "tutor_id": listing.tutor_id,
        "tutor_name": tutor.name,
        "tutor_city": tutor.city,
        "tutor_bio": tutor.bio,
        "tutor_avatar_url": tutor.avatar_url,
        "title": listing.title,
        "subject": listing.subject,
        "price": listing.price,
        "format": listing.format,
        "level": listing.level,
        "description": listing.description,
        "image_url": listing.image_url,
        "is_active": listing.is_active,
        "created_at": listing.created_at,
    }


def public_review(review: Review, db: Session) -> dict:
    student = db.get(User, review.student_id)
    tutor = db.get(User, review.tutor_id)
    return {
        "id": review.id,
        "tutor_id": review.tutor_id,
        "tutor_name": tutor.name if tutor else "Репетитор",
        "student_id": review.student_id,
        "student_name": student.name if student else "Ученик",
        "student_avatar_url": student.avatar_url if student else "",
        "rating": review.rating,
        "body": review.body,
        "created_at": review.created_at,
    }


def public_message(message: Message, current_id: int, db: Session) -> dict:
    sender = db.get(User, message.sender_id)
    recipient = db.get(User, message.recipient_id)
    other = recipient if message.sender_id == current_id else sender
    return {
        "id": message.id,
        "sender_id": message.sender_id,
        "recipient_id": message.recipient_id,
        "listing_id": message.listing_id,
        "body": message.body,
        "image_url": message.image_url,
        "created_at": message.created_at,
        "sender": public_user(sender) if sender else None,
        "recipient": public_user(recipient) if recipient else None,
        "other": public_user(other) if other else None,
    }


@app.get("/")
def index():
    return FileResponse(static_dir / "index.html")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/api/upload")
def upload(file: UploadFile = File(...), user: User = Depends(current_user)):
    suffix = Path(file.filename or "").suffix.lower() or ".jpg"
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        raise HTTPException(400, "Можно загрузить jpg, png, webp или gif")
    filename = f"{user.id}-{token_hex(10)}{suffix}"
    target = upload_dir / filename
    with target.open("wb") as buffer:
        copyfileobj(file.file, buffer)
    return {"url": f"/static/uploads/{filename}"}


@app.post("/api/register")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(409, "Email уже зарегистрирован")
    user = User(
        name=data.name,
        email=data.email,
        password_hash=hash_password(data.password),
        role=data.role,
        city=data.city,
        token=token_hex(24),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": user.token, "user": public_user(user)}


@app.post("/api/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email))
    if not user or user.password_hash != hash_password(data.password):
        raise HTTPException(401, "Неверный email или пароль")
    if user.is_blocked and user.role != "admin":
        raise HTTPException(403, "Аккаунт заблокирован")
    return {"token": user.token, "user": public_user(user)}


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    return public_user(user)


@app.put("/api/me")
def update_me(data: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.name = data.name
    user.city = data.city
    user.bio = data.bio
    user.avatar_url = data.avatar_url
    db.commit()
    return public_user(user)


@app.get("/api/users/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Профиль не найден")
    payload = public_user(user)
    if user.role == "tutor":
        reviews = db.scalars(select(Review).where(Review.tutor_id == user.id)).all()
        payload["rating"] = round(sum(item.rating for item in reviews) / len(reviews), 1) if reviews else 0
        payload["reviews_count"] = len(reviews)
        payload["listings"] = [public_listing(item) for item in db.scalars(select(Listing).where(Listing.tutor_id == user.id)).all()]
    return payload


@app.get("/api/listings")
def listings(q: str = "", subject: str = "", city: str = "", db: Session = Depends(get_db)):
    stmt = select(Listing).where(Listing.is_active.is_(True)).join(User)
    if q:
        needle = f"%{q}%"
        stmt = stmt.where(or_(Listing.title.ilike(needle), Listing.description.ilike(needle), Listing.subject.ilike(needle), User.name.ilike(needle)))
    if subject:
        stmt = stmt.where(Listing.subject.ilike(f"%{subject}%"))
    if city:
        stmt = stmt.where(User.city.ilike(f"%{city}%"))
    return [public_listing(item) for item in db.scalars(stmt.order_by(Listing.created_at.desc())).all()]


@app.get("/api/listings/mine")
def my_listings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not can_tutor(user):
        raise HTTPException(403, "Только репетитор может управлять объявлениями")
    return [public_listing(item) for item in db.scalars(select(Listing).where(Listing.tutor_id == user.id)).all()]


@app.get("/api/listings/{listing_id}")
def listing_details(listing_id: int, db: Session = Depends(get_db)):
    listing = db.get(Listing, listing_id)
    if not listing:
        raise HTTPException(404, "Объявление не найдено")
    reviews = db.scalars(select(Review).where(Review.tutor_id == listing.tutor_id).order_by(Review.created_at.desc())).all()
    schedule = db.scalars(select(CalendarSlot).where(CalendarSlot.tutor_id == listing.tutor_id, CalendarSlot.is_available.is_(True)).order_by(CalendarSlot.slot_date, CalendarSlot.starts_at)).all()
    payload = public_listing(listing)
    payload["reviews"] = [public_review(item, db) for item in reviews]
    payload["rating"] = round(sum(item.rating for item in reviews) / len(reviews), 1) if reviews else 0
    payload["calendar"] = schedule
    return payload


@app.post("/api/listings")
def create_listing(data: ListingIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not can_tutor(user):
        raise HTTPException(403, "Объявления создают только репетиторы")
    listing = Listing(tutor_id=user.id, **data.model_dump())
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return public_listing(listing)


@app.put("/api/listings/{listing_id}")
def update_listing(listing_id: int, data: ListingIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    listing = db.get(Listing, listing_id)
    if not listing or listing.tutor_id != user.id:
        raise HTTPException(404, "Объявление не найдено")
    for key, value in data.model_dump().items():
        setattr(listing, key, value)
    db.commit()
    return public_listing(listing)


@app.delete("/api/listings/{listing_id}")
def delete_listing(listing_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    listing = db.get(Listing, listing_id)
    if not listing or (listing.tutor_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Объявление не найдено")
    db.delete(listing)
    db.commit()
    return {"ok": True}


@app.get("/api/tutors/{tutor_id}/schedule")
def tutor_schedule(tutor_id: int, db: Session = Depends(get_db)):
    return db.scalars(select(ScheduleSlot).where(ScheduleSlot.tutor_id == tutor_id).order_by(ScheduleSlot.weekday, ScheduleSlot.starts_at)).all()


@app.post("/api/schedule")
def create_weekly_slot(data: WeeklySlotIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not can_tutor(user):
        raise HTTPException(403, "График доступен репетиторам")
    slot = ScheduleSlot(tutor_id=user.id, **data.model_dump())
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return slot


@app.delete("/api/schedule/{slot_id}")
def delete_weekly_slot(slot_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    slot = db.get(ScheduleSlot, slot_id)
    if not slot or slot.tutor_id != user.id:
        raise HTTPException(404, "Слот не найден")
    db.delete(slot)
    db.commit()
    return {"ok": True}


@app.get("/api/calendar")
def my_calendar(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not can_tutor(user):
        raise HTTPException(403, "Календарь доступен репетиторам")
    return db.scalars(select(CalendarSlot).where(CalendarSlot.tutor_id == user.id).order_by(CalendarSlot.slot_date, CalendarSlot.starts_at)).all()


@app.get("/api/tutors/{tutor_id}/calendar")
def tutor_calendar(tutor_id: int, db: Session = Depends(get_db)):
    return db.scalars(select(CalendarSlot).where(CalendarSlot.tutor_id == tutor_id, CalendarSlot.is_available.is_(True)).order_by(CalendarSlot.slot_date, CalendarSlot.starts_at)).all()


@app.post("/api/calendar")
def create_calendar_slot(data: CalendarSlotIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not can_tutor(user):
        raise HTTPException(403, "Календарь доступен репетиторам")
    slot = CalendarSlot(tutor_id=user.id, **data.model_dump())
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return slot


@app.delete("/api/calendar/{slot_id}")
def delete_calendar_slot(slot_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    slot = db.get(CalendarSlot, slot_id)
    if not slot or slot.tutor_id != user.id:
        raise HTTPException(404, "Слот не найден")
    db.delete(slot)
    db.commit()
    return {"ok": True}


@app.post("/api/bookings")
def create_booking(data: BookingIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not can_student(user):
        raise HTTPException(403, "Записываться могут только ученики")
    listing = db.get(Listing, data.listing_id)
    if not listing or not listing.is_active:
        raise HTTPException(404, "Объявление не найдено")
    slot = db.scalar(
        select(CalendarSlot).where(
            CalendarSlot.tutor_id == listing.tutor_id,
            CalendarSlot.slot_date == data.requested_date,
            CalendarSlot.starts_at == data.requested_time,
            CalendarSlot.is_available.is_(True),
        )
    )
    if not slot:
        raise HTTPException(400, "Выберите свободное время из календаря репетитора")
    busy_booking = db.scalar(
        select(Booking).where(
            Booking.tutor_id == listing.tutor_id,
            Booking.requested_date == data.requested_date,
            Booking.requested_time == data.requested_time,
            Booking.status.in_(("pending", "accepted")),
        )
    )
    if busy_booking:
        raise HTTPException(409, "На это время уже есть активная заявка")
    booking = Booking(student_id=user.id, tutor_id=listing.tutor_id, **data.model_dump())
    db.add(booking)
    notify(db, listing.tutor_id, "Новая заявка на занятие", f"{user.name} хочет записаться {data.requested_date} в {data.requested_time}")
    db.commit()
    db.refresh(booking)
    return booking


@app.get("/api/bookings")
def get_bookings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == "admin":
        return db.scalars(select(Booking).order_by(Booking.created_at.desc())).all()
    field = Booking.tutor_id if user.role == "tutor" else Booking.student_id
    return db.scalars(select(Booking).where(field == user.id).order_by(Booking.created_at.desc())).all()


@app.put("/api/bookings/{booking_id}")
def decide_booking(booking_id: int, data: BookingDecisionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    booking = db.get(Booking, booking_id)
    if not booking or (booking.tutor_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Заявка не найдена")
    booking.status = data.status
    booking.alternative_date = data.alternative_date
    booking.alternative_time = data.alternative_time
    title = {"accepted": "Заявка принята", "declined": "Заявка отклонена", "alternative": "Предложено другое время"}[data.status]
    body = f"Репетитор {user.name} обновил вашу запись"
    if data.status == "alternative":
        body = f"Репетитор предлагает {data.alternative_date} в {data.alternative_time}"
    notify(db, booking.student_id, title, body)
    db.commit()
    return booking


@app.post("/api/messages")
def send_message(data: MessageIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not data.body and not data.image_url:
        raise HTTPException(400, "Сообщение не может быть пустым")
    recipient = db.get(User, data.recipient_id)
    if not recipient:
        raise HTTPException(404, "Получатель не найден")
    message = Message(sender_id=user.id, **data.model_dump())
    db.add(message)
    notify(db, data.recipient_id, "Новое сообщение", f"{user.name}: {data.body[:80] or 'фотография'}")
    db.commit()
    db.refresh(message)
    return public_message(message, user.id, db)


@app.get("/api/messages")
def get_messages(user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Message).where(or_(Message.sender_id == user.id, Message.recipient_id == user.id)).order_by(Message.created_at.asc())
    return [public_message(item, user.id, db) for item in db.scalars(stmt).all()]


@app.get("/api/dialogs")
def dialogs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    messages = db.scalars(select(Message).where(or_(Message.sender_id == user.id, Message.recipient_id == user.id)).order_by(Message.created_at.desc())).all()
    seen: set[int] = set()
    result = []
    for message in messages:
        other_id = message.recipient_id if message.sender_id == user.id else message.sender_id
        if other_id in seen:
            continue
        seen.add(other_id)
        other = db.get(User, other_id)
        result.append({
            "user": public_user(other) if other else None,
            "last_message": public_message(message, user.id, db),
        })
    return result


@app.get("/api/dialogs/{other_id}")
def dialog_messages(other_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Message).where(
        or_(
            (Message.sender_id == user.id) & (Message.recipient_id == other_id),
            (Message.sender_id == other_id) & (Message.recipient_id == user.id),
        )
    ).order_by(Message.created_at.asc())
    return [public_message(item, user.id, db) for item in db.scalars(stmt).all()]


@app.get("/api/tutors/{tutor_id}/reviews")
def tutor_reviews(tutor_id: int, db: Session = Depends(get_db)):
    return [public_review(item, db) for item in db.scalars(select(Review).where(Review.tutor_id == tutor_id).order_by(Review.created_at.desc())).all()]


@app.post("/api/reviews")
def create_review(data: ReviewIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not can_student(user):
        raise HTTPException(403, "Отзывы оставляют ученики")
    tutor = db.get(User, data.tutor_id)
    if not tutor or tutor.role != "tutor":
        raise HTTPException(404, "Репетитор не найден")
    accepted_booking = db.scalar(
        select(Booking).where(
            Booking.student_id == user.id,
            Booking.tutor_id == data.tutor_id,
            Booking.status == "accepted",
        )
    )
    if not accepted_booking:
        raise HTTPException(403, "Оставить отзыв можно после принятой заявки")
    review = Review(tutor_id=data.tutor_id, student_id=user.id, rating=data.rating, body=data.body)
    db.add(review)
    notify(db, data.tutor_id, "Новый отзыв", f"{user.name} оставил оценку {data.rating}")
    db.commit()
    db.refresh(review)
    return public_review(review, db)


@app.get("/api/admin/users")
def admin_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [public_user(item) for item in db.scalars(select(User).order_by(User.created_at.desc())).all()]


@app.put("/api/admin/users/{user_id}/block")
def admin_block_user(user_id: int, data: BlockUserIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    if user.id == admin.id:
        raise HTTPException(400, "Нельзя заблокировать самого себя")
    user.is_blocked = data.is_blocked
    db.commit()
    return public_user(user)


@app.get("/api/admin/listings")
def admin_listings(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [public_listing(item) for item in db.scalars(select(Listing).order_by(Listing.created_at.desc())).all()]


@app.delete("/api/admin/listings/{listing_id}")
def admin_delete_listing(listing_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    listing = db.get(Listing, listing_id)
    if not listing:
        raise HTTPException(404, "Объявление не найдено")
    db.delete(listing)
    db.commit()
    return {"ok": True}


@app.get("/api/admin/reviews")
def admin_reviews(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [public_review(item, db) for item in db.scalars(select(Review).order_by(Review.created_at.desc())).all()]


@app.delete("/api/admin/reviews/{review_id}")
def admin_delete_review(review_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    review = db.get(Review, review_id)
    if not review:
        raise HTTPException(404, "Отзыв не найден")
    db.delete(review)
    db.commit()
    return {"ok": True}


@app.get("/api/notifications")
def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc())).all()


@app.put("/api/notifications/read")
def read_notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    for item in db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False))).all():
        item.is_read = True
    db.commit()
    return {"ok": True}
