import os
from pathlib import Path

TEST_DB = Path(__file__).resolve().parent / "test_tutorio.db"

if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["ADMIN_EMAIL"] = "admin@test.ru"
os.environ["ADMIN_PASSWORD"] = "Admin12345"

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_full_user_scenario():
    tutor_response = client.post(
        "/api/register",
        json={
            "name": "Рита",
            "email": "rita@test.ru",
            "password": "123456",
            "role": "tutor",
            "city": "Санкт-Петербург"
        }
    )

    assert tutor_response.status_code == 200
    tutor_data = tutor_response.json()
    tutor_token = tutor_data["token"]
    tutor_id = tutor_data["user"]["id"]

    student_response = client.post(
        "/api/register",
        json={
            "name": "Иван",
            "email": "ivan@test.ru",
            "password": "123456",
            "role": "student",
            "city": "Санкт-Петербург"
        }
    )

    assert student_response.status_code == 200
    student_data = student_response.json()
    student_token = student_data["token"]

    forbidden_listing = client.post(
        "/api/listings",
        headers=auth_headers(student_token),
        json={
            "title": "Физика",
            "subject": "Физика",
            "price": 1200,
            "format": "Онлайн",
            "level": "ОГЭ",
            "description": "Подготовка к экзамену",
            "image_url": ""
        }
    )

    assert forbidden_listing.status_code == 403

    invalid_listing = client.post(
        "/api/listings",
        headers=auth_headers(tutor_token),
        json={
            "title": "A",
            "subject": "М",
            "price": -100,
            "format": "Онлайн",
            "level": "ЕГЭ",
            "description": "коротко",
            "image_url": ""
        }
    )

    assert invalid_listing.status_code == 422

    listing_response = client.post(
        "/api/listings",
        headers=auth_headers(tutor_token),
        json={
            "title": "Математика",
            "subject": "Математика",
            "price": 1500,
            "format": "Онлайн",
            "level": "ЕГЭ",
            "description": "Подготовка к ЕГЭ за 3 месяца!",
            "image_url": ""
        }
    )

    assert listing_response.status_code == 200
    listing = listing_response.json()
    listing_id = listing["id"]

    calendar_response = client.post(
        "/api/calendar",
        headers=auth_headers(tutor_token),
        json={
            "slot_date": "2026-05-15",
            "starts_at": "12:35",
            "ends_at": "13:35",
            "is_available": True
        }
    )

    assert calendar_response.status_code == 200

    catalog_response = client.get("/api/listings?q=Математика&city=Санкт-Петербург")

    assert catalog_response.status_code == 200
    catalog = catalog_response.json()
    assert len(catalog) >= 1
    assert catalog[0]["title"] == "Математика"

    details_response = client.get(f"/api/listings/{listing_id}")

    assert details_response.status_code == 200
    details = details_response.json()
    assert details["title"] == "Математика"
    assert len(details["calendar"]) >= 1

    unavailable_booking_response = client.post(
        "/api/bookings",
        headers=auth_headers(student_token),
        json={
            "listing_id": listing_id,
            "requested_date": "2026-05-15",
            "requested_time": "10:00",
            "note": "Хочу время, которого нет в календаре"
        }
    )

    assert unavailable_booking_response.status_code == 400

    booking_response = client.post(
        "/api/bookings",
        headers=auth_headers(student_token),
        json={
            "listing_id": listing_id,
            "requested_date": "2026-05-15",
            "requested_time": "12:35",
            "note": "Хочу подготовиться к ЕГЭ"
        }
    )

    assert booking_response.status_code == 200
    booking = booking_response.json()
    booking_id = booking["id"]
    assert booking["status"] == "pending"

    duplicate_booking_response = client.post(
        "/api/bookings",
        headers=auth_headers(student_token),
        json={
            "listing_id": listing_id,
            "requested_date": "2026-05-15",
            "requested_time": "12:35",
            "note": "Дубль"
        }
    )

    assert duplicate_booking_response.status_code == 409

    early_review_response = client.post(
        "/api/reviews",
        headers=auth_headers(student_token),
        json={
            "tutor_id": tutor_id,
            "rating": 5,
            "body": "Пока еще не было принятой заявки"
        }
    )

    assert early_review_response.status_code == 403

    decision_response = client.put(
        f"/api/bookings/{booking_id}",
        headers=auth_headers(tutor_token),
        json={
            "status": "accepted",
            "alternative_date": "",
            "alternative_time": ""
        }
    )

    assert decision_response.status_code == 200

    student_bookings_response = client.get(
        "/api/bookings",
        headers=auth_headers(student_token)
    )

    assert student_bookings_response.status_code == 200
    student_bookings = student_bookings_response.json()

    accepted_booking = next(
        item for item in student_bookings
        if item["id"] == booking_id
    )

    assert accepted_booking["status"] == "accepted"

    message_response = client.post(
        "/api/messages",
        headers=auth_headers(student_token),
        json={
            "recipient_id": tutor_id,
            "listing_id": listing_id,
            "body": "Здравствуйте!",
            "image_url": ""
        }
    )

    assert message_response.status_code == 200
    assert message_response.json()["body"] == "Здравствуйте!"

    dialogs_response = client.get(
        "/api/dialogs",
        headers=auth_headers(tutor_token)
    )

    assert dialogs_response.status_code == 200
    assert len(dialogs_response.json()) >= 1

    review_response = client.post(
        "/api/reviews",
        headers=auth_headers(student_token),
        json={
            "tutor_id": tutor_id,
            "rating": 4,
            "body": "Было интересно!"
        }
    )

    assert review_response.status_code == 200
    assert review_response.json()["rating"] == 4

    details_with_review_response = client.get(f"/api/listings/{listing_id}")

    assert details_with_review_response.status_code == 200
    details_with_review = details_with_review_response.json()
    assert details_with_review["rating"] == 4
    assert len(details_with_review["reviews"]) == 1

    notifications_response = client.get(
        "/api/notifications",
        headers=auth_headers(tutor_token)
    )

    assert notifications_response.status_code == 200
    notifications = notifications_response.json()
    assert len(notifications) >= 2
