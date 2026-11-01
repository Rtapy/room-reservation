# Meeting room reservations

Django + Django REST Framework with PostgreSQL. Python 3.12+ and Docker Compose are required for the local setup below.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
docker compose up -d --wait db
python manage.py migrate
python manage.py check --database default
python manage.py createsuperuser
python manage.py runserver
```

Django runs on `http://127.0.0.1:8000/`. The built-in admin is at `/admin/`.
PostgreSQL is exposed only on `127.0.0.1:55432`; change `POSTGRES_PORT` in `.env` if that port is in use.
Use `docker compose stop` to stop PostgreSQL while keeping its data.

## Configuration

Settings load `.env` from the project root. Existing environment variables take precedence.
Use `.env.example` as the configuration reference; `.env` is ignored by Git.
The example credentials and secret key are for local development only.

`MIN_RESERVATION_MINUTES` and `MAX_RESERVATION_MINUTES` configure the session duration limits, initially 15 and 180 minutes. Both must be positive integers, with the minimum no greater than the maximum. Invalid values prevent startup.
The company timezone is `Asia/Tehran`; Django timezone support is enabled.

## Current scope

Stages 1–3: project setup, environment settings, PostgreSQL connection, `Room` and `Reservation` models with database constraints, token authentication, and access control for room management and reservation reads.
The initial migration installs `btree_gist` for the exclusion constraint. The local Compose database user has the required permissions.
Availability search, reservation creation with idempotency and row locking, and cancellation will be added in the next stages. Working hours, configurable duration limits, inactive rooms, and capacity versus attendee count will be validated by the reservation service.
Design decisions are in [docs/DECISIONS.md](docs/DECISIONS.md); the task is in [docs/task.pdf](docs/task.pdf).

## Authentication and endpoints

Create users with `createsuperuser` or Django admin; there is no registration endpoint.
Admin API permissions use `is_staff`, including staff users who are not superusers.

Get a token with existing user credentials:

```bash
curl -X POST http://127.0.0.1:8000/api/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"your-username","password":"your-password"}'
```

The response is `{"token":"..."}`. Send `Authorization: Token <token>` on other API requests.
Repeated login returns the same token. Invalid or inactive credentials return `400`.
Missing, invalid, or inactive-user tokens return `401` on protected endpoints; session login does not authenticate API requests.

| Method | Endpoint | Access |
| --- | --- | --- |
| POST | `/api/auth/token/` | User credentials; no token required |
| GET | `/api/rooms/` | Any authenticated user; includes inactive rooms |
| POST | `/api/rooms/` | Staff only |
| PATCH | `/api/rooms/{id}/` | Staff only; change name, capacity, or active status |
| GET | `/api/reservations/` | Own reservations, including cancelled; staff can see all |
| GET | `/api/reservations/{id}/` | Owner or staff; another employee's reservation returns `404` |

Room fields are `id`, `name`, `capacity`, and `is_active`. Creating a room requires a unique `name` and positive `capacity`; `is_active` defaults to `true`.
Reservation responses include `id`, `room`, `user`, `start_at`, `end_at`, `attendees_count`, `status`, `created_at`, and `cancelled_at`; `room` and `user` are IDs. Lists are JSON arrays.
Employees attempting room writes receive `403`. Room deletion and direct reservation updates/deletion are not exposed.

## Tests

With PostgreSQL running and the virtual environment active:

```bash
python manage.py test reservations.tests --noinput
```

Tests cover database constraints, token login and token-authenticated API access, staff-only room writes, and reservation list/detail isolation. API tests use DRF's APIClient with real tokens and PostgreSQL; they do not bypass authentication.
The database tests include 10 concurrent ORM inserts using separate PostgreSQL connections: one succeeds and nine are rejected by the exclusion constraint. Reservation creation/cancellation over HTTP, row locking in the service, and idempotency will be tested when those features are implemented. The database user must be able to create the separate test database.
