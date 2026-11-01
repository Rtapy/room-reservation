# Meeting room reservations

Django REST Framework API with PostgreSQL for room availability, reservations, and soft cancellation.
See [design decisions](docs/DECISIONS.md) and the [task](docs/task.pdf).

## Run locally

Requires Python 3.12+ and Docker Compose.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
docker compose up -d --wait db
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

The API runs at `http://127.0.0.1:8000/`; Django admin is at `/admin/`.
PostgreSQL uses `127.0.0.1:55432` by default (`POSTGRES_PORT` in `.env`). Stop it with `docker compose stop` to keep its data.
The initial migration installs `btree_gist`; the Compose database user has the required permissions.

Settings load the root `.env`; existing environment variables take precedence. `.env.example` contains local development credentials.
`MIN_RESERVATION_MINUTES` and `MAX_RESERVATION_MINUTES` default to 15 and 180; both must be positive integers with minimum <= maximum.

## Users and Swagger

Use the superuser created above to add employees under **Django admin → Users → Add**.
Employees have `is_staff=False` and `is_superuser=False`. API admins need `is_staff=True`; managing users in Django admin requires separate permissions or a superuser. There is no registration endpoint.

Open [Swagger UI](http://127.0.0.1:8000/api/docs/):

1. Execute `POST /api/auth/token/` with the user's username and password.
2. Click **Authorize** and enter `Token YOUR_TOKEN`, replacing `YOUR_TOKEN` with the returned token. Include `Token` and one space; omit quotes and angle brackets.
3. Use **Try it out** to send requests. Logging into Django admin or obtaining a token does not automatically authorize Swagger.

Protected requests use `Authorization: Token YOUR_TOKEN`.
Swagger and [OpenAPI](http://127.0.0.1:8000/api/schema/) are public; Swagger's JavaScript/CSS need internet access to load from the CDN.

## Endpoints

| Method | Endpoint | Access / purpose |
| --- | --- | --- |
| POST | `/api/auth/token/` | Existing user credentials → token |
| GET | `/api/rooms/` | Authenticated; includes inactive rooms |
| POST | `/api/rooms/` | Staff; create a room |
| PATCH | `/api/rooms/{id}/` | Staff; edit or deactivate a room |
| GET | `/api/rooms/available/` | Authenticated; search available rooms |
| GET | `/api/reservations/` | Own reservations; staff see all |
| POST | `/api/reservations/` | Authenticated; create own reservation |
| GET | `/api/reservations/{id}/` | Owner or staff; read a reservation |
| POST | `/api/reservations/{id}/cancel/` | Owner or staff; soft cancellation, no body |

Create a room with `{"name":"Meeting room 1","capacity":8,"is_active":true}`. Name must be unique; capacity must be positive. `is_active` defaults to `true`.

Availability requires query parameters `start_at`, `end_at`, and `attendees_count`. It returns active rooms with enough capacity and no overlapping confirmed reservation; no matches returns `[]`. Search does not hold a room.

Create a reservation with a required `Idempotency-Key` header (for example, a UUID) and this JSON body:

```json
{
  "room": 1,
  "start_at": "2030-01-02T09:00:00+03:30",
  "end_at": "2030-01-02T10:00:00+03:30",
  "attendees_count": 3
}
```

Use an existing room ID and a future interval. Both datetimes need an offset or `Z`; URL-encode query values containing `+`. Time rules and replay behavior are in [DECISIONS.md](docs/DECISIONS.md).
Lists return JSON arrays; reservation `room` and `user` fields are IDs. Swagger documents the full request and response fields.

Creation and successful replay return `201`; cancellation and repeated cancellation return `200`.
Errors: `400` invalid input, inactive room, or insufficient capacity; `401` missing/invalid authentication; `403` employee room writes; `404` missing room/reservation or another employee's reservation; `409` overlap or reuse of a successful key with different data.

## Tests

With PostgreSQL running and the virtual environment active:

```bash
python manage.py test reservations.tests --noinput
```

The database user must be able to create the separate test database.
Tests cover time/capacity rules, conflicts, permissions, cancellation, idempotency, and API documentation. Concurrency tests use real PostgreSQL connections and local HTTP: 10 overlapping requests with different keys yield one `201` and nine `409`s; identical concurrent keys replay one successful creation.
