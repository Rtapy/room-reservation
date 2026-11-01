# Decisions

- A Django/DRF monolith with one `reservations` app is enough for this task. We use PostgreSQL for transactions, row locks, and overlap constraints, and DRF Token Authentication for simplicity.
- The duration limits were unspecified, so they come from `MIN_RESERVATION_MINUTES` and `MAX_RESERVATION_MINUTES` in `.env`, initially 15 and 180 minutes, inclusive.
- We assume the company timezone is `Asia/Tehran`. Datetimes need an offset or `Z`; sessions must fit within 08:00–18:00 on the same company date. Past starts and non-positive intervals are rejected. No weekday restriction is applied.
- Attendee counts must be positive. A room must be active and its capacity must be at least the attendee count. Availability search is advisory; creation checks again.
- Intervals are `[start_at, end_at)`, so back-to-back reservations are allowed. Only `confirmed` reservations block the interval.
- Creation runs inside `transaction.atomic()` and locks the room with `select_for_update()`. We recheck time, active status, capacity, and conflicts after the lock, serializing creation for each room. A PostgreSQL `ExclusionConstraint` with `btree_gist` also blocks overlapping confirmed writes outside the service; overlap returns `409`.
- Creation requires an `Idempotency-Key`: 1–255 visible ASCII characters without spaces, scoped to the user. The key, reservation, and response snapshot commit together. Concurrent identical requests create once; the same key and effective data replay the original `201`. Different data return `409`. Times are normalized to UTC for comparison.
- Successful keys have no automatic expiry; failed requests consume no key. Replay returns the original response even after the start time, room changes, or cancellation, and never reactivates a reservation.
- Employees can read and cancel only their own reservations; other users' IDs return `404`. Admins are identified by `is_staff` and can manage rooms and access all reservations. The server assigns the reservation owner and initial `confirmed` status. Django admin sessions do not authenticate API requests.
- Cancellation keeps the row, changes status to `cancelled`, records `cancelled_at`, and frees the interval. A conditional update preserves the first timestamp on repeats. Referenced rooms/users use `PROTECT` to preserve reservation history.
