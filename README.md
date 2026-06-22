# Tutorio - сайт для репетиторов

## Краткое описание

Tutorio - небольшое веб-приложение для поиска репетиторов и записи на занятия.
В приложении есть три роли: ученик, репетитор и администратор.

## Возможности

- Ученики могут искать репетиторов, смотреть объявления, записываться на свободное время, писать в чат и оставлять отзывы после принятой заявки.
- Репетиторы могут редактировать профиль, создавать объявления, добавлять свободные окна в календарь, отвечать на заявки и общаться с учениками.
- Администратор может смотреть пользователей, объявления и отзывы, блокировать пользователей и удалять нежелательный контент.

## Основные команды

Установка зависимостей:

```powershell
pip install -r requirements.txt
```

Запуск приложения:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Запуск с автообновлением во время разработки:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Открыть в браузере:

```text
http://127.0.0.1:8000
```

Запуск тестов:

```powershell
python -m pytest -q
```

Проверка Python-файлов на синтаксические ошибки:

```powershell
python -m compileall app
```

Проверка JavaScript-файла:

```powershell
node --check static/app.js
```

## Переменные окружения

- `DATABASE_URL` - строка подключения к базе данных. По умолчанию используется `sqlite:///./tutors.db`.
- `ADMIN_EMAIL` - email администратора. По умолчанию `admin@tutorio-school.ru`.
- `ADMIN_PASSWORD` - пароль администратора. Обязательно задайте на Render.
- `AUTO_SEED_ON_STARTUP` - если `true`, приложение при старте создаёт или обновляет администратора из `ADMIN_EMAIL`/`ADMIN_PASSWORD`.

## Deploy To Render

В проект добавлен `render.yaml`, поэтому Render может создать web service и PostgreSQL базу автоматически через Blueprint.

1. Залейте проект в GitHub без `.env`, локальной БД, кешей и файлов из `static/uploads`.
2. В Render выберите `New +` -> `Blueprint` и подключите GitHub-репозиторий.
3. Render создаст:
   - `tutorio` web service;
   - `tutorio-db` PostgreSQL database.
4. В Environment у web service задайте:
   - `ADMIN_EMAIL` - email администратора;
   - `ADMIN_PASSWORD` - сильный пароль администратора;
   - `AUTO_SEED_ON_STARTUP=true`;
   - `DATABASE_URL` подставится автоматически из Render PostgreSQL.

Если создаёте Web Service вручную:

```powershell
pip install -r requirements.txt
```

```powershell
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

На Render Free Shell может быть недоступен, поэтому отдельная команда seed не нужна: администратор создаётся/обновляется при старте приложения.

После деплоя проверьте:

```text
/healthz
/
```

Затем войдите через `ADMIN_EMAIL` и `ADMIN_PASSWORD`.

### Ограничения Render Free

- Первый запрос после простоя может быть медленным из-за cold start.
- Бесплатная PostgreSQL база на Render временная.
- Файлы из `static/uploads` на бесплатном web service не являются постоянным хранилищем. Для реального сайта используйте S3/Supabase Storage/Cloudinary/Cloudflare R2 или платный Render Disk.

## Файлы и данные

- `static/uploads` - загруженные изображения.
- `tutors.db` - локальная SQLite-база данных, создается автоматически при запуске.
- `requirements.txt` - зависимости Python.

## Администратор

Администратор создаётся или обновляется при старте приложения, если `AUTO_SEED_ON_STARTUP=true` и задан `ADMIN_PASSWORD`.
