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

Stages 1–2: project setup, environment settings, DRF installation, PostgreSQL connection, and the `Room` and `Reservation` models with migrations and database constraints.
The initial migration installs `btree_gist` for the exclusion constraint. The local Compose database user has the required permissions.
Token authentication, API endpoints, the reservation service, and HTTP/concurrency tests for those paths will be added in the next stages. Working hours, configurable duration limits, inactive rooms, and capacity versus attendee count will be validated by that service.
Design decisions are in [docs/DECISIONS.md](docs/DECISIONS.md); the task is in [docs/task.pdf](docs/task.pdf).

## Model tests

With PostgreSQL running and the virtual environment active:

```bash
python manage.py test reservations.tests --noinput
```

These tests exercise database constraints, including 10 concurrent ORM inserts using separate PostgreSQL connections: one succeeds and nine are rejected by the exclusion constraint. This verifies the database safeguard; API responses, row locking in the service, and idempotency will be tested when those features are implemented. The database user must be able to create the separate test database.
