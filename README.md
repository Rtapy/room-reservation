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

Stages 1–6: project setup, environment settings, PostgreSQL connection, models and database constraints, token authentication, access control, availability search, transactional reservation creation with idempotency, and soft cancellation.
The initial migration installs `btree_gist` for the exclusion constraint. The local Compose database user has the required permissions.
Availability and reservation creation share the time rules; creation rechecks the time, active status, capacity, and conflicts after locking the room inside a database transaction.
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
| GET | `/api/rooms/available/` | Any authenticated user; requires `start_at`, `end_at`, and `attendees_count` |
| POST | `/api/rooms/` | Staff only |
| PATCH | `/api/rooms/{id}/` | Staff only; change name, capacity, or active status |
| GET | `/api/reservations/` | Own reservations, including cancelled; staff can see all |
| POST | `/api/reservations/` | Any authenticated user; requires `Idempotency-Key`; creates their own reservation |
| GET | `/api/reservations/{id}/` | Owner or staff; another employee's reservation returns `404` |
| POST | `/api/reservations/{id}/cancel/` | Owner or staff; soft cancellation |

Room fields are `id`, `name`, `capacity`, and `is_active`. Creating a room requires a unique `name` and positive `capacity`; `is_active` defaults to `true`.
Reservation responses include `id`, `room`, `user`, `start_at`, `end_at`, `attendees_count`, `status`, `created_at`, and `cancelled_at`; `room` and `user` are IDs. Lists are JSON arrays.
Employees attempting room writes receive `403`. Room deletion and direct reservation updates/deletion are not exposed.

## Availability search

```bash
curl -G http://127.0.0.1:8000/api/rooms/available/ \
  -H 'Authorization: Token <token>' \
  --data-urlencode 'start_at=2030-01-02T09:00:00+03:30' \
  --data-urlencode 'end_at=2030-01-02T10:00:00+03:30' \
  --data-urlencode 'attendees_count=3'
```

Choose a future date when running this example. Both datetimes require an explicit timezone offset or `Z`; use URL encoding to preserve `+` in offsets. The attendee count must be a positive integer.
The start must be before the end and cannot be in the past. Duration must be within the configured limits, including their boundaries. The entire session must fit within 08:00–18:00 on the same date in `Asia/Tehran`, regardless of the input offset. There is no weekday restriction.

The response is a JSON array of active rooms with enough capacity and no overlapping confirmed reservation from any user. Cancelled reservations are ignored, and adjacent sessions do not overlap. No matches returns `200` with `[]`; invalid parameters return `400` with field errors or `non_field_errors`.
Search does not reserve or lock a room; another user may reserve it before creation, so the creation service will check again.

## Create a reservation

After pulling this feature, run `python manage.py migrate` to create the idempotency table.

```bash
curl -X POST http://127.0.0.1:8000/api/reservations/ \
  -H 'Authorization: Token <token>' \
  -H 'Idempotency-Key: your-unique-request-key' \
  -H 'Content-Type: application/json' \
  -d '{"room":1,"start_at":"2030-01-02T09:00:00+03:30","end_at":"2030-01-02T10:00:00+03:30","attendees_count":3}'
```

Use an existing room ID and a future interval. Required fields are `room`, `start_at`, `end_at`, and `attendees_count`; the same time rules as availability apply. The owner is the authenticated user, including for staff, and the initial status is `confirmed`. Client-supplied owner/status fields cannot override them.

Creation returns `201` with the reservation fields listed above. An inactive room or insufficient capacity returns `400`, a missing room `404`, and an overlapping confirmed reservation `409`. Other invalid input returns `400`.

`Idempotency-Key` is required: use 1–255 visible ASCII characters without spaces, for example a UUID. Keys are scoped to the authenticated user. Repeating the same key and effective data returns the original JSON response and `201`, including after the start time passes or the room/reservation changes. Changing the room, interval, or attendee count for a successful key returns `409`. Equivalent timezone offsets and numeric inputs are normalized before comparison.

The key claim, reservation, and response snapshot are saved in one transaction. Identical in-flight keys wait for the first transaction, even across different rooms. Failed requests roll back their key claims and can be retried; only successful responses are retained, with no automatic expiry. A temporary empty claim is never committed by the service.
Different keys targeting one room serialize on `select_for_update()`. The PostgreSQL exclusion constraint also protects against overlapping writes outside the service; only that constraint violation is translated to `409`.

## Cancel a reservation

```bash
curl -X POST http://127.0.0.1:8000/api/reservations/1/cancel/ \
  -H 'Authorization: Token <token>'
```

No request body or `Idempotency-Key` is needed. The owner or a staff user receives `200` with the reservation, its `cancelled` status, and `cancelled_at`. The row stays in the database and remains visible to authorized users; its interval is available for a new reservation.
Repeating cancellation returns the same state and preserves the first cancellation timestamp. A conditional status update makes the transition atomic. Another employee's reservation and a missing ID both return `404`; unauthenticated requests return `401`.
The original creation response snapshot is kept: replaying its creation key still returns that original response and does not reactivate the cancelled reservation.

## Tests

With PostgreSQL running and the virtual environment active:

```bash
python manage.py test reservations.tests --noinput
```

Tests cover database constraints, token login and token-authenticated API access, staff-only room writes, reservation list/detail isolation, and availability filtering and validation. Availability cases include configured duration limits, Tehran working hours, explicit timezones, all overlap shapes, adjacency, inactive/undersized rooms, and cancelled reservations. API tests use DRF's APIClient with real tokens and PostgreSQL; they do not bypass authentication.
The database tests include 10 concurrent ORM inserts using separate PostgreSQL connections: one succeeds and nine are rejected by the exclusion constraint.
Creation tests cover rollback, immutable response replay, and the database conflict fallback. `LiveServerTestCase` tests also use real local HTTP and PostgreSQL: 10 users get one `201` and nine `409`s; 10 identical keys get the same `201` response and one reservation. Separate backend PIDs are checked. Row-lock tests observe blocked `SELECT FOR UPDATE` queries via `pg_stat_activity` and verify that room changes and time are rechecked after waiting. The clock is fixed in these tests; authentication and database locking are real.
Cancellation adds five API tests for the owner, staff, another user/missing ID, unauthenticated access, and repeated cancellation. Existing creation tests also exercise the cancellation endpoint to verify that it frees the interval and preserves the creation response snapshot.
The database user must be able to create the separate test database.
