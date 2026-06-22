const state = {
  token: localStorage.getItem("token") || "",
  user: JSON.parse(localStorage.getItem("user") || "null"),
  listings: [],
  activeListing: null,
  activeDialogUserId: null,
  authMode: "login",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const money = (value) => `${Number(value || 0).toLocaleString("ru-RU")} ₽/час`;
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  "\"": "&quot;",
  "'": "&#39;",
}[char]));

function safeText(value, fallback = "") {
  return escapeHtml(value || fallback);
}

function safeUrl(value) {
  const url = String(value || "").trim();
  if (!url) return "";
  if (url.startsWith("/static/uploads/")) return escapeHtml(url);
  try {
    const parsed = new URL(url, window.location.origin);
    if (["http:", "https:"].includes(parsed.protocol)) return escapeHtml(parsed.href);
  } catch {
    return "";
  }
  return "";
}

function errorMessage(detail) {
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || item.message || String(item)).join(". ");
  }
  return detail || "Ошибка запроса";
}

function showToast(message, type = "ok") {
  const toast = $("#toast");
  toast.textContent = message;
  toast.className = `toast ${type}`;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add("hidden"), 3200);
}

function setFormError(id, message = "") {
  const element = $(id);
  if (!element) return;
  element.textContent = message;
  element.classList.toggle("hidden", !message);
}

function authHeaders() {
  return state.token ? { Authorization: `Bearer ${state.token}` } : {};
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(errorMessage(data.detail));
  return data;
}

async function uploadFile(file) {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch("/api/upload", { method: "POST", headers: authHeaders(), body });
  const data = await response.json();
  if (!response.ok) throw new Error(errorMessage(data.detail) || "Не удалось загрузить файл");
  return data.url;
}

function formData(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function initials(user) {
  const name = user?.name || "?";
  return name.trim().slice(0, 1).toUpperCase();
}

function avatar(user, size = "avatar") {
  const url = safeUrl(user?.avatar_url);
  if (url) return `<img class="${size}" src="${url}" alt="">`;
  return `<span class="${size} avatar-fallback">${safeText(initials(user))}</span>`;
}

function showRoute(name) {
  $$(".route").forEach((route) => route.classList.add("hidden"));
  $(`#${name}Route`)?.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (name === "profile") loadProfilePage();
  if (name === "manageListings") loadMyListings();
  if (name === "calendar") loadCalendar();
  if (name === "chats") loadDialogs();
  if (name === "admin") loadAdminPanel();
}

function requireAuth(next) {
  if (!state.user) {
    openAuth("login");
    return false;
  }
  next?.();
  return true;
}

function renderAuth() {
  const authed = Boolean(state.user);
  $$(".auth-only").forEach((item) => item.classList.toggle("hidden", !authed));
  $$(".guest-only").forEach((item) => item.classList.toggle("hidden", authed));
  $$(".tutor-only").forEach((item) => item.classList.toggle("hidden", !["tutor", "admin"].includes(state.user?.role)));
  $$(".admin-only").forEach((item) => item.classList.toggle("hidden", state.user?.role !== "admin"));
  $("#roleBadge").textContent = state.user ? roleName(state.user.role) : "";
  $("#profileAvatarButton").innerHTML = authed ? avatar(state.user, "avatar-small") : "";
}

function roleName(role) {
  return { tutor: "Репетитор", student: "Ученик", admin: "Администратор" }[role] || role;
}

function renderProfilePreview() {
  if (!state.user) return;
  $("#profilePreview").innerHTML = `
    <div class="profile-card-head">
      ${avatar(state.user, "avatar-large")}
      <div>
        <h1>${safeText(state.user.name)}</h1>
        <div class="meta">${safeText(roleName(state.user.role))} · ${safeText(state.user.city, "город не указан")}</div>
      </div>
      <button class="primary edit-profile-btn" id="editProfileButton" type="button" title="Редактировать профиль">✎</button>
    </div>
    <p>${safeText(state.user.bio, "Расскажите о себе: цели, опыт, формат занятий или пожелания к преподавателю.")}</p>
  `;
}

function setProfileEditMode(isEditing) {
  $("#profilePreview").classList.toggle("hidden", isEditing);
  $("#profileForm").classList.toggle("hidden", !isEditing);
}

function setSession(payload) {
  state.token = payload.token;
  state.user = payload.user;
  localStorage.setItem("token", state.token);
  localStorage.setItem("user", JSON.stringify(state.user));
  renderAuth();
  loadNotifications();
}

function cardImage(listing) {
  const url = safeUrl(listing.image_url);
  if (url) return `<img src="${url}" alt="">`;
  return safeText(listing.subject.slice(0, 1).toUpperCase());
}

function renderListings() {
  $("#listingCount").textContent = `${state.listings.length} найдено`;
  $("#listingCards").innerHTML = state.listings.map((listing) => `
    <article class="card clickable" data-open-listing="${listing.id}">
      <div class="thumb">${cardImage(listing)}</div>
      <div>
        <h3>${safeText(listing.title)}</h3>
        <div class="meta">${safeText(listing.subject)} · ${safeText(listing.level, "любой уровень")} · ${safeText(listing.format)}</div>
        <p>${safeText(listing.description)}</p>
        <button class="link-button" data-open-profile="${listing.tutor_id}">${safeText(listing.tutor_name)}, ${safeText(listing.tutor_city, "город не указан")}</button>
      </div>
      <div class="card-actions">
        <div class="price">${money(listing.price)}</div>
        <button class="primary" data-book="${listing.id}">Записаться</button>
        <button class="ghost" data-message="${listing.tutor_id}" data-listing="${listing.id}">Написать</button>
      </div>
    </article>
  `).join("") || `<div class="panel">Пока ничего не найдено. Попробуйте изменить запрос или фильтры.</div>`;
}

async function loadListings() {
  const params = new URLSearchParams({
    q: $("#searchInput").value,
    city: $("#cityInput").value,
    subject: $("#subjectFilter").value,
  });
  state.listings = await api(`/api/listings?${params}`);
  renderListings();
}

async function openListing(id) {
  const listing = await api(`/api/listings/${id}`);
  state.activeListing = listing;
  $("#listingDetails").innerHTML = `
    <article class="listing-page">
      <div class="listing-media thumb-large">${cardImage(listing)}</div>
      <aside class="listing-side">
        <div class="price">${money(listing.price)}</div>
        <button class="primary" data-book="${listing.id}">Записаться</button>
        <button class="ghost" data-message="${listing.tutor_id}" data-listing="${listing.id}">Написать репетитору</button>
        <button class="ghost" data-review="${listing.tutor_id}">Оставить отзыв</button>
      </aside>
      <section class="listing-main">
        <h1>${safeText(listing.title)}</h1>
        <div class="meta">${safeText(listing.subject)} · ${safeText(listing.level, "любой уровень")} · ${safeText(listing.format)}</div>
        <p>${safeText(listing.description)}</p>
        <div class="tutor-strip">
          ${avatar({ name: listing.tutor_name, avatar_url: listing.tutor_avatar_url })}
          <div>
            <button class="link-button strong" data-open-profile="${listing.tutor_id}">${safeText(listing.tutor_name)}</button>
            <div class="meta">${safeText(listing.tutor_city, "Город не указан")} · рейтинг ${safeText(listing.rating || "нет")} · отзывов ${listing.reviews.length}</div>
          </div>
        </div>
        <h2>Доступное время</h2>
        <div class="slot-picker">${renderSlots(listing.calendar)}</div>
        <h2>Отзывы</h2>
        <div class="reviews">${renderReviews(listing.reviews)}</div>
      </section>
    </article>
  `;
  showRoute("listing");
}

function renderSlots(slots) {
  return slots?.length ? slots.map((slot) => `
    <button class="slot" type="button" data-pick-date="${safeText(slot.slot_date)}" data-pick-time="${safeText(slot.starts_at)}">
      ${new Date(slot.slot_date).toLocaleDateString("ru-RU")} · ${safeText(slot.starts_at)}-${safeText(slot.ends_at)}
    </button>
  `).join("") : `<span class="meta">Репетитор пока не выставил свободные окна.</span>`;
}

function renderReviews(reviews) {
  return reviews?.length ? reviews.map((review) => `
    <div class="list-row review">
      <div class="row-person">${avatar({ name: review.student_name, avatar_url: review.student_avatar_url }, "avatar-small")}<strong>${safeText(review.student_name)}</strong></div>
      <div class="stars">${"★".repeat(review.rating)}${"☆".repeat(5 - review.rating)}</div>
      <p>${safeText(review.body)}</p>
    </div>
  `).join("") : `<div class="meta">Отзывов пока нет.</div>`;
}

async function openPublicProfile(id) {
  const profile = await api(`/api/users/${id}`);
  $("#publicProfile").innerHTML = `
    <div class="profile-hero panel">
      ${avatar(profile, "avatar-large")}
      <div>
        <h1>${safeText(profile.name)}</h1>
        <div class="meta">${safeText(roleName(profile.role))} · ${safeText(profile.city, "город не указан")}</div>
        <p>${safeText(profile.bio, "Описание пока не заполнено.")}</p>
      </div>
      ${state.user && state.user.id !== profile.id ? `<button class="primary" data-message="${profile.id}">Написать</button>` : ""}
    </div>
    ${profile.role === "tutor" ? `
      <div class="section-title"><h2>Объявления</h2><span>Рейтинг ${safeText(profile.rating || "нет")} · отзывов ${profile.reviews_count || 0}</span></div>
      <div class="cards">${(profile.listings || []).map((item) => `
        <article class="mini-card" data-open-listing="${item.id}">
          <strong>${safeText(item.title)}</strong>
          <span class="meta">${safeText(item.subject)} · ${money(item.price)}</span>
        </article>
      `).join("") || `<div class="panel">Объявлений пока нет.</div>`}</div>
    ` : ""}
  `;
  showRoute("publicProfile");
}

function loadProfilePage() {
  if (!state.user) return;
  renderProfilePreview();
  setProfileEditMode(false);
  $("#profileForm").name.value = state.user.name || "";
  $("#profileForm").city.value = state.user.city || "";
  $("#profileForm").bio.value = state.user.bio || "";
  $("#profileForm").avatar_url.value = state.user.avatar_url || "";
  loadBookings();
}

async function loadNotifications() {
  if (!state.user) return;
  const items = await api("/api/notifications");
  const unread = items.filter((item) => !item.is_read).length;
  $("#notificationButton").textContent = unread;
  $("#notificationList").innerHTML = items.map((item) => `
    <div class="list-row">
      <strong>${safeText(item.title)}</strong>
      <span>${safeText(item.body)}</span>
      <span class="meta">${new Date(item.created_at).toLocaleString("ru-RU")}</span>
    </div>
  `).join("") || `<div class="meta">Пока уведомлений нет.</div>`;
}

async function loadBookings() {
  if (!state.user) return;
  const items = await api("/api/bookings");
  $("#bookingList").innerHTML = items.map((item) => `
    <div class="list-row">
      <strong>Заявка #${item.id}: ${safeText(item.requested_date)} ${safeText(item.requested_time)}</strong>
      <span class="status">Статус: ${safeText(item.status)}${item.alternative_date ? `, альтернатива ${safeText(item.alternative_date)} ${safeText(item.alternative_time)}` : ""}</span>
      <span>${safeText(item.note || "")}</span>
      ${state.user.role === "tutor" ? `
        <div class="row-actions">
          <button class="primary" data-booking-status="accepted" data-booking="${item.id}">Принять</button>
          <button class="ghost" data-booking-status="declined" data-booking="${item.id}">Отклонить</button>
          <button class="ghost" data-booking-status="alternative" data-booking="${item.id}">Предложить другое</button>
        </div>` : ""}
    </div>
  `).join("") || `<span class="meta">Заявок пока нет.</span>`;
}

function resetListingForm() {
  $("#listingForm").reset();
  $("#listingForm").id.value = "";
  $("#listingFormTitle").textContent = "Новое объявление";
}

async function loadMyListings() {
  if (!["tutor", "admin"].includes(state.user?.role)) return;
  const items = await api("/api/listings/mine");
  $("#myListings").innerHTML = items.map((item) => `
    <div class="list-row">
      <strong>${safeText(item.title)}</strong>
      <span class="meta">${safeText(item.subject)}, ${money(item.price)}</span>
      <div class="row-actions">
        <button class="ghost" data-edit-listing="${item.id}">Редактировать</button>
        <button class="ghost" data-delete-listing="${item.id}">Удалить</button>
        <button class="ghost" data-open-listing="${item.id}">Открыть</button>
      </div>
    </div>
  `).join("") || `<span class="meta">У вас пока нет объявлений.</span>`;
}

async function loadCalendar() {
  if (!["tutor", "admin"].includes(state.user?.role)) return;
  const items = await api("/api/calendar");
  $("#calendarGrid").innerHTML = items.map((slot) => `
    <div class="calendar-cell">
      <strong>${new Date(slot.slot_date).toLocaleDateString("ru-RU")}</strong>
      <span>${safeText(slot.starts_at)}-${safeText(slot.ends_at)}</span>
      <button class="ghost" data-delete-calendar="${slot.id}">Удалить</button>
    </div>
  `).join("") || `<span class="meta">Добавьте доступные даты для записи.</span>`;
}

async function loadAdminPanel() {
  if (state.user?.role !== "admin") return;
  const [users, listings, reviews] = await Promise.all([
    api("/api/admin/users"),
    api("/api/admin/listings"),
    api("/api/admin/reviews"),
  ]);
  $("#adminUsers").innerHTML = users.map((user) => `
    <div class="list-row">
      <div class="row-person">${avatar(user, "avatar-small")}<strong>${safeText(user.name)}</strong></div>
      <span class="meta">${safeText(user.email)} · ${safeText(roleName(user.role))}${user.is_blocked ? " · заблокирован" : ""}</span>
      <div class="row-actions">
        <button class="ghost" data-open-profile="${user.id}">Профиль</button>
        ${user.role !== "admin" ? `<button class="${user.is_blocked ? "primary" : "ghost"}" data-admin-block="${user.id}" data-block-value="${!user.is_blocked}">${user.is_blocked ? "Разблокировать" : "Заблокировать"}</button>` : ""}
      </div>
    </div>
  `).join("") || `<span class="meta">Пользователей пока нет.</span>`;
  $("#adminListings").innerHTML = listings.map((listing) => `
    <div class="list-row">
      <strong>${safeText(listing.title)}</strong>
      <span class="meta">${safeText(listing.subject)} · ${money(listing.price)} · ${safeText(listing.tutor_name)}</span>
      <div class="row-actions">
        <button class="ghost" data-open-listing="${listing.id}">Открыть</button>
        <button class="ghost" data-admin-delete-listing="${listing.id}">Удалить</button>
      </div>
    </div>
  `).join("") || `<span class="meta">Объявлений пока нет.</span>`;
  $("#adminReviews").innerHTML = reviews.map((review) => `
    <div class="list-row">
      <strong>${safeText(review.tutor_name)} · ${"★".repeat(review.rating)}${"☆".repeat(5 - review.rating)}</strong>
      <span>${safeText(review.body)}</span>
      <span class="meta">Автор: ${safeText(review.student_name)}</span>
      <button class="ghost" data-admin-delete-review="${review.id}">Удалить отзыв</button>
    </div>
  `).join("") || `<span class="meta">Отзывов пока нет.</span>`;
}

async function loadDialogs() {
  if (!state.user) return;
  const dialogs = await api("/api/dialogs");
  $("#dialogList").innerHTML = dialogs.map((dialog) => `
    <button class="dialog-item ${state.activeDialogUserId === dialog.user.id ? "active" : ""}" data-open-dialog="${dialog.user.id}">
      ${avatar(dialog.user, "avatar-small")}
      <span><strong>${safeText(dialog.user.name)}</strong><small>${safeText(dialog.last_message.body, "Фотография")}</small></span>
    </button>
  `).join("") || `<span class="meta">Диалогов пока нет.</span>`;
}

async function openDialog(otherId, listingId = "") {
  if (!requireAuth()) return;
  state.activeDialogUserId = Number(otherId);
  const other = await api(`/api/users/${otherId}`);
  const messages = await api(`/api/dialogs/${otherId}`);
  $("#messageForm").recipient_id.value = otherId;
  $("#messageForm").listing_id.value = listingId || "";
  $("#chatHead").innerHTML = `
    <button class="chat-profile-button" data-open-profile="${other.id}">
      ${avatar(other, "avatar-small")}
      <span><strong>${safeText(other.name)}</strong><small>Открыть профиль</small></span>
    </button>
  `;
  $("#chatMessages").innerHTML = messages.map((message) => `
    <div class="bubble ${message.sender_id === state.user.id ? "mine" : ""}">
      ${safeUrl(message.image_url) ? `<img src="${safeUrl(message.image_url)}" alt="">` : ""}
      ${message.body ? `<span>${safeText(message.body)}</span>` : ""}
      <small>${new Date(message.created_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</small>
    </div>
  `).join("") || `<span class="meta">Начните диалог.</span>`;
  showRoute("chats");
  await loadDialogs();
  $("#chatMessages").scrollTop = $("#chatMessages").scrollHeight;
}

function openAuth(mode) {
  state.authMode = mode;
  $("#authTitle").textContent = mode === "login" ? "Вход" : "Регистрация";
  $("#authSubmit").textContent = mode === "login" ? "Войти" : "Создать аккаунт";
  $$(".register-field").forEach((item) => item.classList.toggle("hidden", mode === "login"));
  $("#authDialog").showModal();
}

async function openBooking(listingId) {
  if (!requireAuth()) return;
  const listing = state.activeListing?.id == listingId ? state.activeListing : await api(`/api/listings/${listingId}`);
  $("#bookingForm").listing_id.value = listingId;
  $("#slotPicker").innerHTML = renderSlots(listing.calendar);
  $("#bookingDialog").showModal();
}

document.addEventListener("click", async (event) => {
  const target = event.target.closest("button, article, .mini-card");
  if (!target) return;

  if (target.dataset.closeDialog) {
    $(`#${target.dataset.closeDialog}`).close();
    setFormError("#authError");
    setFormError("#bookingError");
    setFormError("#reviewError");
    return;
  }
  if (target.dataset.route) {
    if (["profile", "manage-listings", "calendar", "chats", "admin"].includes(target.dataset.route) && !requireAuth()) return;
    if (target.dataset.route === "admin" && state.user?.role !== "admin") {
      showToast("Админ-панель доступна только администратору", "error");
      return;
    }
    showRoute(target.dataset.route.replace("-listings", "Listings"));
  }
  if (target.id === "editProfileButton") setProfileEditMode(true);
  if (target.id === "cancelProfileEdit") setProfileEditMode(false);
  if (target.id === "profileAvatarButton") showRoute("profile");
  if (target.id === "loginButton") openAuth("login");
  if (target.id === "registerButton") openAuth("register");
  if (target.id === "logoutButton") {
    localStorage.clear();
    state.token = "";
    state.user = null;
    renderAuth();
    showRoute("catalog");
  }
  if (target.dataset.openListing) await openListing(target.dataset.openListing);
  if (target.dataset.openProfile) await openPublicProfile(target.dataset.openProfile);
  if (target.dataset.book) await openBooking(target.dataset.book);
  if (target.dataset.message) await openDialog(target.dataset.message, target.dataset.listing || "");
  if (target.dataset.openDialog) await openDialog(target.dataset.openDialog);
  if (target.dataset.pickDate) {
    $("#bookingForm").requested_date.value = target.dataset.pickDate;
    $("#bookingForm").requested_time.value = target.dataset.pickTime;
  }
  if (target.dataset.review) {
    if (!requireAuth()) return;
    $("#reviewForm").tutor_id.value = target.dataset.review;
    $("#reviewDialog").showModal();
  }
  if (target.dataset.deleteListing) {
    await api(`/api/listings/${target.dataset.deleteListing}`, { method: "DELETE" });
    await Promise.all([loadMyListings(), loadListings()]);
  }
  if (target.dataset.editListing) {
    const item = (await api("/api/listings/mine")).find((listing) => listing.id == target.dataset.editListing);
    Object.entries(item).forEach(([key, value]) => {
      if ($("#listingForm")[key]) $("#listingForm")[key].value = value ?? "";
    });
    $("#listingFormTitle").textContent = "Редактирование объявления";
  }
  if (target.id === "resetListingForm") resetListingForm();
  if (target.dataset.deleteCalendar) {
    await api(`/api/calendar/${target.dataset.deleteCalendar}`, { method: "DELETE" });
    await loadCalendar();
  }
  if (target.dataset.adminBlock) {
    await api(`/api/admin/users/${target.dataset.adminBlock}/block`, {
      method: "PUT",
      body: JSON.stringify({ is_blocked: target.dataset.blockValue === "true" }),
    });
    await loadAdminPanel();
  }
  if (target.dataset.adminDeleteListing) {
    await api(`/api/admin/listings/${target.dataset.adminDeleteListing}`, { method: "DELETE" });
    await Promise.all([loadAdminPanel(), loadListings()]);
  }
  if (target.dataset.adminDeleteReview) {
    await api(`/api/admin/reviews/${target.dataset.adminDeleteReview}`, { method: "DELETE" });
    await loadAdminPanel();
  }
  if (target.dataset.bookingStatus) {
    const body = { status: target.dataset.bookingStatus };
    if (body.status === "alternative") {
      body.alternative_date = prompt("Дата альтернативы, ГГГГ-ММ-ДД") || "";
      body.alternative_time = prompt("Время альтернативы, ЧЧ:ММ") || "";
    }
    await api(`/api/bookings/${target.dataset.booking}`, { method: "PUT", body: JSON.stringify(body) });
    await loadBookings();
  }
  if (target.id === "notificationButton") {
    await loadNotifications();
    $("#notificationsDialog").showModal();
  }
  if (target.id === "closeNotifications") {
    await api("/api/notifications/read", { method: "PUT" });
    $("#notificationsDialog").close();
    await loadNotifications();
  }
});

$("#searchForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await loadListings();
});

$("#subjectFilter").addEventListener("change", loadListings);

$("#authForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  setFormError("#authError");
  try {
    const data = formData(form);
    if (state.authMode === "register" && data.password.length < 6) {
      setFormError("#authError", "Пароль должен быть не короче 6 символов.");
      return;
    }
    const path = state.authMode === "login" ? "/api/login" : "/api/register";
    const payload = state.authMode === "login" ? { email: data.email, password: data.password } : data;
    setSession(await api(path, { method: "POST", body: JSON.stringify(payload) }));
    $("#authDialog").close();
    showToast(state.authMode === "login" ? "Вы вошли в аккаунт" : "Аккаунт создан");
  } catch (error) {
    setFormError("#authError", error.message);
  }
});

$("#avatarUpload").addEventListener("change", async (event) => {
  if (!event.target.files[0]) return;
  try {
    $("#profileForm").avatar_url.value = await uploadFile(event.target.files[0]);
    showToast("Аватар загружен");
  } catch (error) {
    showToast(error.message, "error");
  }
});

$("#listingUpload").addEventListener("change", async (event) => {
  if (!event.target.files[0]) return;
  try {
    $("#listingForm").image_url.value = await uploadFile(event.target.files[0]);
    showToast("Фото объявления загружено");
  } catch (error) {
    showToast(error.message, "error");
  }
});

$("#profileForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    state.user = await api("/api/me", { method: "PUT", body: JSON.stringify(formData(form)) });
    localStorage.setItem("user", JSON.stringify(state.user));
    renderAuth();
    renderProfilePreview();
    setProfileEditMode(false);
    showToast("Профиль сохранен");
  } catch (error) {
    showToast(error.message, "error");
  }
});

$("#listingForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const data = formData(form);
    data.price = Number(data.price);
    const id = data.id;
    delete data.id;
    await api(id ? `/api/listings/${id}` : "/api/listings", {
      method: id ? "PUT" : "POST",
      body: JSON.stringify(data),
    });
    resetListingForm();
    await Promise.all([loadMyListings(), loadListings()]);
    showToast("Объявление сохранено");
  } catch (error) {
    showToast(error.message, "error");
  }
});

$("#calendarForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api("/api/calendar", { method: "POST", body: JSON.stringify(formData(form)) });
    form.reset();
    await loadCalendar();
    showToast("Окно добавлено");
  } catch (error) {
    showToast(error.message, "error");
  }
});

$("#bookingForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  setFormError("#bookingError");
  try {
    await api("/api/bookings", { method: "POST", body: JSON.stringify(formData(form)) });
    form.reset();
    $("#bookingDialog").close();
    await loadNotifications();
    showToast("Заявка отправлена");
  } catch (error) {
    setFormError("#bookingError", error.message);
  }
});

$("#reviewForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  setFormError("#reviewError");
  try {
    const data = formData(form);
    data.rating = Number(data.rating);
    data.tutor_id = Number(data.tutor_id);
    if (!data.body || data.body.trim().length < 3) {
      setFormError("#reviewError", "Напишите хотя бы пару слов об уроке.");
      return;
    }
    await api("/api/reviews", { method: "POST", body: JSON.stringify(data) });
    form.reset();
    $("#reviewDialog").close();
    showToast("Отзыв опубликован");
    if (state.activeListing) await openListing(state.activeListing.id);
  } catch (error) {
    setFormError("#reviewError", error.message);
  }
});

$("#messageForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const data = formData(form);
    const recipientId = Number(data.recipient_id);
    const listingId = data.listing_id ? Number(data.listing_id) : null;
    if (!recipientId) {
      showToast("Сначала выберите диалог", "error");
      return;
    }
    const file = $("#messageUpload").files[0];
    if (!data.body.trim() && !file) {
      showToast("Напишите сообщение или прикрепите фото", "error");
      return;
    }
    data.recipient_id = recipientId;
    data.listing_id = listingId;
    if (file) data.image_url = await uploadFile(file);
    await api("/api/messages", { method: "POST", body: JSON.stringify(data) });
    form.reset();
    form.recipient_id.value = recipientId;
    form.listing_id.value = listingId || "";
    await openDialog(recipientId, listingId || "");
  } catch (error) {
    showToast(error.message, "error");
  }
});

renderAuth();
showRoute("catalog");
loadListings().catch(console.error);
loadNotifications().catch(() => {});
