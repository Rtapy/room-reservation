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

Stage 1: project setup, environment settings, DRF installation, and PostgreSQL connection.
Reservation models, token authentication, API endpoints, and business/concurrency tests will be added in the next stages.
Design decisions are in [docs/DECISIONS.md](docs/DECISIONS.md); the task is in [docs/task.pdf](docs/task.pdf).
