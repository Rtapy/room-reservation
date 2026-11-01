# Stage 7: test audit and project status

Verified on 2026-11-01. Branch: `test/reservation-conflicts-permissions`, based directly on `feature/reservation-cancellation` at `3399bd5` as requested. This step changes tests and documentation; application behavior, API contracts, dependencies, settings, and migrations are unchanged.

## Results and counting

- Baseline: **93 passed**, 0 failures, 0 errors, 0 skips. Django reported 5.567 seconds.
- Curated suite: **58 passed**, 0 failures, 0 errors, 0 skips. Django reported 3.725 seconds.
- **39 old methods were removed or merged; 4 focused methods were introduced**, giving 35 fewer methods overall. Ten retained methods were renamed/reworked to describe their consolidated purpose.
- Test source size: **1271 -> 1067 lines**, excluding this report and README.
- Counts are test methods, not requests, assertions, subtest rows, or a coverage percentage. Consolidation alone is not a claim of less maintenance; the changes also remove secondary scenarios and duplicated setup/assertions.
- The timings are two local observations, not a benchmark or production performance evidence.

| File | Before | After |
| --- | ---: | ---: |
| [test_authentication.py](../reservations/tests/test_authentication.py) | 7 | 3 |
| [test_availability.py](../reservations/tests/test_availability.py) | 23 | 8 |
| [test_cancellation.py](../reservations/tests/test_cancellation.py) | 5 | 5 |
| [test_creation.py](../reservations/tests/test_creation.py) | 21 | 16 |
| [test_creation_concurrency.py](../reservations/tests/test_creation_concurrency.py) | 7 | 6 |
| [test_models.py](../reservations/tests/test_models.py) | 15 | 7 |
| [test_permissions.py](../reservations/tests/test_permissions.py) | 15 | 10 |
| [test_validation.py](../reservations/tests/test_validation.py) | 0 | 3 |
| **Total** | **93** | **58** |

## What actually ran

| Execution layer | Methods | Evidence and limits |
| --- | ---: | --- |
| DRF APIClient + PostgreSQL | 42 | Real token authentication, serializers, routes, permissions, services, and database writes. These are in-process requests, not network HTTP. |
| Model/constraint tests + PostgreSQL | 7 | Six transactional model tests plus one `TransactionTestCase` with 10 independently observed backend PIDs. |
| LiveServerTestCase + PostgreSQL | 6 | Actual local HTTP creation requests with real tokens. The two 10-request tests assert 10 distinct backend PIDs. Three tests observe blocked room `SELECT FOR UPDATE` queries through `pg_stat_activity`. |
| Shared validator, no database | 3 | Deterministic time/order/duration/company-date boundary matrices. |

The complete suite was run with:

```bash
.venv/bin/python manage.py test reservations.tests --noinput --verbosity 2
```

The test database was freshly created, all migrations including `reservations.0001_initial` and `0002_reservationrequest` were applied, and the test database was destroyed afterward. Time-dependent cases fix the clock. Authentication, PostgreSQL transactions, and row locks in the concurrency tests are real.

The conflict-fallback test mocks only the service preflight query so an actual PostgreSQL constraint violation occurs. The rollback test injects an exception when saving the response snapshot. Neither mocks the database transaction or exclusion constraint.

## Coverage against the task and approved decisions

| Requirement | Retained evidence |
| --- | --- |
| Room inventory and admin-only room management | Employee read; employee/guest write denial; staff create/edit/deactivate; invalid capacity/name input. |
| Active room, enough capacity, free interval | Main availability matrix includes inactive, undersized, exact-capacity, cancelled, conflicting, and mixed non-conflicting rows. |
| Time rules and environment-configured duration | One shared boundary matrix, API wiring tests for both flows, explicit offset/Z API tests, a valid Friday fixture, and post-lock time revalidation. |
| No overlapping reservations | Named database exclusion checks, five overlap shapes in the independent availability query, service 409, actual constraint fallback, 10 raw inserts, and 10 real HTTP users. |
| Employees see/cancel only their own reservations; staff exception | List/detail isolation, spoofed user query parameter, guessed-ID 404, owner/staff cancellation and unauthorized/guest denials. |
| Keep cancelled records and free the interval | Cancellation retains business fields; create/cancel/search/create workflow succeeds without deleting history. |
| Idempotency | Required key, normalized replay, different-data 409, user-scoped keys, immutable replay after cancellation/runtime changes, concurrent same-key replay, and same-key/different-room race. |
| Atomicity and fresh eligibility | Failed claims/reservations roll back; active status, capacity, and time are reread after observable lock waits. |

Full boundary matrices live in the shared-validator tests. API tests retain representative failures to detect missing validation wiring. Database overlap tests remain separate because a passing service test does not prove that writes bypassing the service are protected. Availability retains its own overlap matrix because its inverse `Exists` query can be wrong while the exclusion constraint is correct.

## Removed or superseded old methods: complete decision log

Old names below refer to base commit `3399bd5`. Each row states whether coverage was moved/merged or deliberately reduced. A reduction is not described as unchanged coverage.

### test_authentication.py

| Old method | Decision and rationale |
| --- | --- |
| `test_repeated_login_returns_the_same_token` | Remove: DRF built-in token reuse; no custom reservation logic. |
| `test_inactive_user_cannot_obtain_a_token` | Merge inactive credentials into invalid_or_missing_credentials. |
| `test_login_does_not_require_a_valid_existing_token` | Remove: stale login header compatibility is secondary to the task. |
| `test_session_login_does_not_replace_token_authentication` | Remove: dedicated session-vs-token configuration check is secondary; token authentication remains configured. |

### test_permissions.py

| Old method | Decision and rationale |
| --- | --- |
| `test_employee_cannot_create_a_room` | Merge employee POST and PATCH denials into one room-write policy test. |
| `test_staff_can_create_a_room` | Merge room creation and editing into one staff management workflow. |
| `test_query_parameter_cannot_expose_another_users_reservations` | Merge spoofed query parameter into employee list/detail isolation. |
| `test_employee_can_read_their_reservation` | Merge authorized detail retrieval into employee list/detail isolation. |
| `test_object_permission_allows_only_owner_or_staff` | Remove direct permission-class test; production endpoint ownership, staff, and denial tests retain behavioral coverage. |

### test_models.py

| Old method | Decision and rationale |
| --- | --- |
| `test_room_name_is_unique` | Remove separate built-in unique-field check; API duplicate-name rejection remains. |
| `test_room_capacity_must_be_positive` | Merge custom capacity and attendee zero-value checks into one database invariant test. |
| `test_confirmed_reservation_defaults` | Remove field-default assertions duplicated by successful API creation. |
| `test_adjacent_reservations_allowed_on_both_sides` | Merge accepted boundary intervals into the exclusion-constraint acceptance matrix. |
| `test_same_interval_in_different_rooms_allowed` | Merge different-room acceptance into the exclusion-constraint acceptance matrix. |
| `test_cancelling_existing_reservation_frees_interval` | Remove duplicate raw-ORM transition; cancel/search/create endpoint workflow retains this behavior. |
| `test_updating_time_cannot_create_overlap` | Remove dedicated rescheduling test: reservation editing is not exposed; direct insert constraint and API mutation rejection remain. |
| `test_cancelled_reservation_cannot_be_reactivated_over_existing_one` | Remove dedicated reactivation test: reactivation is not exposed; snapshot replay explicitly cannot reactivate. |

### test_availability.py

| Old method | Decision and rationale |
| --- | --- |
| `test_static_route_resolves_to_availability_action` | Remove implementation-level route inspection; actual availability API calls exercise routing. |
| `test_missing_or_invalid_token_is_rejected` | Merge availability into common unauthenticated read-endpoint matrix. |
| `test_staff_search_has_the_same_availability_rules` | Remove duplicate filtering matrix; staff has no special availability query path. |
| `test_invalid_dates_and_attendee_counts_are_rejected` | Merge malformed input cases into query-parameter validation. |
| `test_end_must_be_after_start` | Move full matrix to shared validator tests; API wiring checks remain. |
| `test_start_in_the_past_is_rejected` | Move full matrix to shared validator tests; API wiring checks remain. |
| `test_duration_bounds_include_exact_limits` | Move exact duration boundaries to shared validator tests. |
| `test_duration_validation_uses_configured_settings` | Move configured duration matrix to shared validator tests. |
| `test_working_hour_boundaries_in_tehran` | Move working-hour boundaries to shared validator tests. |
| `test_cross_company_date_interval_is_rejected` | Move company-date rule to shared validator tests. |
| `test_utc_and_other_offsets_describing_same_instants_return_same_rooms` | Merge UTC/Z equivalence into API timezone test; idempotency normalization test also remains. |
| `test_input_offset_does_not_override_company_working_hours` | Merge invalid UTC working hours into API timezone test and shared time matrix. |
| `test_non_conflicting_reservation_does_not_hide_the_room` | Merge mixed conflicting/non-conflicting rows into main availability fixture and filtering test. |
| `test_friday_is_allowed` | Use Friday in the successful availability fixture, eliminating a separate weekday-only test. |
| `test_shared_validator_rejects_naive_datetimes` | Remove duplicate helper-level naive-input check; both API input boundaries still reject naive datetimes. |
| `test_duration_uses_elapsed_time_across_foreign_timezone_dst_change` | Remove foreign DST transition scenario; company timezone is Tehran and foreign timezone activation is not a product flow. |

### test_creation.py

| Old method | Decision and rationale |
| --- | --- |
| `test_staff_also_creates_their_own_reservation` | Merge employee/staff owner enforcement into one server-assigned ownership test. |
| `test_repeated_request_returns_original_response_without_duplicate` | Remove simpler repeat already exercised by normalized replay, immutable replay, and real HTTP concurrent replay. |
| `test_replay_is_snapshot_even_if_reservation_is_cancelled` | Merge cancellation and changed runtime state into one immutable response replay workflow. |
| `test_missing_room_returns_404_without_consuming_key` | Merge missing, inactive, and insufficient room conditions into key-rollback eligibility test. |
| `test_creation_uses_configured_duration_limits` | Move full limits matrix to shared validator tests; creation still tests shared-validator wiring and post-lock time revalidation. |

### test_creation_concurrency.py

| Old method | Decision and rationale |
| --- | --- |
| `test_different_rooms_with_different_keys_can_both_be_reserved` | Remove duplicate success case; sequential API covers other-room acceptance, while this test did not prove independent lock progress. |

### Retained methods renamed during consolidation

These ten methods are retained workflows, not additional deletions. Together with the 39 decisions above and the unchanged method names, they account for the entire baseline.

| Old method | Current method |
| --- | --- |
| `test_employee_cannot_edit_or_deactivate_a_room` | `test_employee_cannot_create_edit_or_deactivate_rooms` |
| `test_staff_can_edit_and_deactivate_a_room` | `test_staff_can_create_edit_and_deactivate_a_room` |
| `test_employee_list_contains_only_their_reservations` | `test_employee_list_and_detail_are_scoped_to_their_reservations` |
| `test_attendee_count_must_be_positive` | `test_custom_positive_checks_reject_zero_capacity_and_attendees` |
| `test_cancelled_reservations_are_retained_and_do_not_block` | `test_exclusion_allows_adjacent_different_room_and_cancelled_intervals` |
| `test_all_search_parameters_are_required` | `test_query_parameters_are_required_and_validated` |
| `test_datetime_inputs_require_explicit_timezone` | `test_timezone_inputs_require_offsets_and_use_company_time` |
| `test_replay_survives_past_time_room_changes_and_new_duration_settings` | `test_replay_survives_cancellation_and_changed_runtime_rules` |
| `test_inactive_or_insufficient_room_rejected_without_consuming_key` | `test_rejected_room_conditions_do_not_consume_key` |
| `test_shared_time_rules_are_enforced_during_creation` | `test_creation_applies_shared_time_validation` |

The suite no longer has dedicated checks for repeated token issuance, stale login headers, session-authentication exclusion, foreign activated-timezone DST transitions, raw reservation rescheduling/reactivation, or the room-name database unique field in isolation. These are secondary/framework-level or unsupported-flow cases for this task. The API still rejects duplicate room names and direct reservation edits/deletion. This is a deliberate scope tradeoff, not proof that the omitted cases are impossible to break.

## Why each remaining method stays

### test_authentication.py

| Method | Fault it is intended to detect |
| --- | --- |
| [`test_valid_credentials_issue_a_token`](../reservations/tests/test_authentication.py#L19) | The public token route must issue a stored token for valid credentials. |
| [`test_invalid_or_missing_credentials_do_not_issue_a_token`](../reservations/tests/test_authentication.py#L28) | Wrong, missing, unknown-user, and inactive-user credentials must not grant access. |
| [`test_inactive_user_token_cannot_access_the_api`](../reservations/tests/test_authentication.py#L42) | An already-issued token must stop authorizing an inactive account. |

### test_availability.py

| Method | Fault it is intended to detect |
| --- | --- |
| [`test_search_returns_only_active_rooms_with_enough_capacity_and_no_conflict`](../reservations/tests/test_availability.py#L65) | Exercise filtering, exact capacity, cancelled rows, mixed conflicting/non-conflicting rows, response fields, and a valid Friday. |
| [`test_no_matching_rooms_returns_empty_array`](../reservations/tests/test_availability.py#L72) | The documented empty search is a successful empty list, not an error. |
| [`test_query_parameters_are_required_and_validated`](../reservations/tests/test_availability.py#L77) | Required query fields and malformed input must fail before executing a valid search. |
| [`test_timezone_inputs_require_offsets_and_use_company_time`](../reservations/tests/test_availability.py#L94) | Reject naive times; accept equivalent Z instants and enforce Tehran hours regardless of offset. |
| [`test_availability_applies_shared_time_validation`](../reservations/tests/test_availability.py#L111) | Keep a small API wiring check so removing the shared validator from search cannot silently pass. |
| [`test_all_overlap_shapes_exclude_the_room`](../reservations/tests/test_availability.py#L120) | Availability uses a separate inverse SQL query; a correct exclusion constraint does not prove that query is correct. |
| [`test_adjacent_intervals_on_either_side_do_not_conflict`](../reservations/tests/test_availability.py#L130) | Availability must use strict overlap comparisons at both interval boundaries. |
| [`test_search_does_not_write_or_hold_a_reservation`](../reservations/tests/test_availability.py#L137) | Searching must not reserve anything; later creation can change the next search result. |

### test_cancellation.py

| Method | Fault it is intended to detect |
| --- | --- |
| [`test_owner_cancels_without_deleting_reservation_history`](../reservations/tests/test_cancellation.py#L37) | The owner can soft-cancel, retain unchanged business fields, and read the saved history. |
| [`test_staff_can_cancel_another_users_reservation`](../reservations/tests/test_cancellation.py#L61) | Preserve the administrator cancellation exception. |
| [`test_other_user_and_missing_reservation_return_404_without_changes`](../reservations/tests/test_cancellation.py#L69) | Reject unauthorized cancellation without leaking existence or changing the record. |
| [`test_unauthenticated_user_cannot_cancel`](../reservations/tests/test_cancellation.py#L78) | The cancellation write endpoint must reject guests without side effects. |
| [`test_repeated_cancellation_preserves_first_timestamp_and_response`](../reservations/tests/test_cancellation.py#L84) | Repeated authorized cancellation must retain the first timestamp and response state. |

### test_creation.py

| Method | Fault it is intended to detect |
| --- | --- |
| [`test_success_creates_reservation_and_response_record`](../reservations/tests/test_creation.py#L59) | Verify the successful transaction persists the reservation and its matching replay snapshot. |
| [`test_owner_and_initial_state_are_always_assigned_by_server`](../reservations/tests/test_creation.py#L72) | Neither employees nor staff can spoof the owner or create a cancelled reservation through client fields. |
| [`test_unauthenticated_creation_is_rejected`](../reservations/tests/test_creation.py#L85) | Creation must reject absent/invalid tokens without writing reservations or key claims. |
| [`test_idempotency_key_is_required_and_validated`](../reservations/tests/test_creation.py#L92) | The custom key format and required-header contract must reject invalid claims without writes. |
| [`test_equivalent_timezone_and_numeric_inputs_replay_same_response`](../reservations/tests/test_creation.py#L100) | The custom fingerprint must compare normalized effective data and replay without duplicates. |
| [`test_same_key_with_different_effective_data_returns_409`](../reservations/tests/test_creation.py#L112) | Changing any effective creation field must not silently reuse a successful key. |
| [`test_keys_are_scoped_to_each_user`](../reservations/tests/test_creation.py#L124) | One user key must not block another user using the same key for a different reservation. |
| [`test_replay_survives_cancellation_and_changed_runtime_rules`](../reservations/tests/test_creation.py#L133) | An immutable snapshot must survive cancellation, changed room eligibility/limits, and elapsed time without reactivating the row. |
| [`test_overlapping_reservation_returns_409_and_rolls_back_key`](../reservations/tests/test_creation.py#L148) | The service must report 409 and leave no failed key claim when another user already owns the interval. |
| [`test_adjacent_and_other_room_reservations_are_allowed`](../reservations/tests/test_creation.py#L156) | Service-level conflict logic must allow boundary-adjacent and different-room creation. |
| [`test_cancelled_reservation_does_not_block_new_creation`](../reservations/tests/test_creation.py#L167) | Exercise the documented create/cancel/search/create workflow across actual API actions. |
| [`test_rejected_room_conditions_do_not_consume_key`](../reservations/tests/test_creation.py#L182) | Missing, inactive, and insufficient rooms must fail atomically; the same key can succeed after a failed attempt. |
| [`test_invalid_creation_fields_are_rejected`](../reservations/tests/test_creation.py#L195) | Validate creation-specific room input, required fields, and representative shared input-boundary errors. |
| [`test_creation_applies_shared_time_validation`](../reservations/tests/test_creation.py#L214) | Keep API wiring checks for the shared rules; the full boundary matrix lives in test_validation.py. |
| [`test_database_exclusion_violation_is_also_translated_to_409`](../reservations/tests/test_creation.py#L223) | Bypass only the preflight check and verify a real PostgreSQL exclusion violation is handled as 409. |
| [`test_response_persistence_failure_rolls_back_reservation_and_key`](../reservations/tests/test_creation.py#L233) | Inject a response-save error to prove all-or-nothing writes and avoid masking unrelated errors as booking conflicts. |

### test_creation_concurrency.py

| Method | Fault it is intended to detect |
| --- | --- |
| [`test_ten_users_same_interval_only_one_creation_and_nine_409s`](../reservations/tests/test_creation_concurrency.py#L76) | Required optional challenge and accepted decision: real HTTP with 10 users gives one 201, nine 409s, one row, and 10 backend PIDs. |
| [`test_ten_identical_keys_replay_one_creation_with_same_response`](../reservations/tests/test_creation_concurrency.py#L94) | Real concurrent retries must all return the same 201 body and create only one reservation/key. |
| [`test_same_user_key_for_different_rooms_cannot_create_two_reservations`](../reservations/tests/test_creation_concurrency.py#L108) | Room locks alone cannot serialize an identical key across different rooms; the per-user key constraint must do so. |
| [`test_room_deactivated_while_request_waits_is_rejected`](../reservations/tests/test_creation_concurrency.py#L152) | Observe a real room lock wait and confirm active status is reread after commit. |
| [`test_capacity_reduced_while_request_waits_is_rejected`](../reservations/tests/test_creation_concurrency.py#L155) | Observe a real room lock wait and confirm capacity is reread after commit. |
| [`test_start_time_is_revalidated_after_waiting_for_room_lock`](../reservations/tests/test_creation_concurrency.py#L158) | A pre-lock time check is insufficient if the start time passes during the wait. |

### test_models.py

| Method | Fault it is intended to detect |
| --- | --- |
| [`test_custom_positive_checks_reject_zero_capacity_and_attendees`](../reservations/tests/test_models.py#L42) | PositiveIntegerField accepts zero; our stricter database checks must reject it. |
| [`test_end_must_be_strictly_after_start`](../reservations/tests/test_models.py#L48) | The database must reject empty/reversed intervals even if API validation is bypassed. |
| [`test_status_and_cancellation_timestamp_must_agree`](../reservations/tests/test_models.py#L54) | The custom state constraint protects consistent reportable reservation history. |
| [`test_overlapping_reservations_rejected_for_any_user`](../reservations/tests/test_models.py#L66) | The exclusion constraint must reject all five overlap shapes across different owners. |
| [`test_exclusion_allows_adjacent_different_room_and_cancelled_intervals`](../reservations/tests/test_models.py#L78) | The same constraint must allow its three documented exceptions; this guards overly broad exclusion expressions. |
| [`test_room_and_user_with_reservation_cannot_be_deleted`](../reservations/tests/test_models.py#L90) | PROTECT must preserve reservation history when referenced rooms or admin-managed users are deleted. |
| [`test_only_one_of_ten_concurrent_overlapping_inserts_succeeds`](../reservations/tests/test_models.py#L100) | Verify the independent database safeguard when writers bypass the room-locking service, using 10 PostgreSQL backend PIDs. |

### test_permissions.py

| Method | Fault it is intended to detect |
| --- | --- |
| [`test_missing_or_invalid_token_cannot_read_resources`](../reservations/tests/test_permissions.py#L42) | Protect all read entry points, including availability, with 401 and the Token challenge. |
| [`test_anonymous_user_cannot_write_rooms`](../reservations/tests/test_permissions.py#L57) | Unauthenticated room writes must have no effect. |
| [`test_employee_can_list_rooms_including_inactive_rooms`](../reservations/tests/test_permissions.py#L70) | Employees must be able to discover the room inventory; availability has separate active-room filtering. |
| [`test_employee_cannot_create_edit_or_deactivate_rooms`](../reservations/tests/test_permissions.py#L76) | Employees cannot perform either room write operation or change stored room data. |
| [`test_staff_can_create_edit_and_deactivate_a_room`](../reservations/tests/test_permissions.py#L91) | A staff user, without superuser privileges, can complete the room management workflow. |
| [`test_room_api_rejects_invalid_capacity_and_duplicate_names`](../reservations/tests/test_permissions.py#L105) | Reject invalid room definitions at the API boundary. |
| [`test_employee_list_and_detail_are_scoped_to_their_reservations`](../reservations/tests/test_permissions.py#L119) | Prevent list leakage and query-parameter impersonation while allowing own detail/history reads. |
| [`test_other_users_reservation_and_missing_id_both_return_404`](../reservations/tests/test_permissions.py#L134) | Do not expose another employee reservation through a guessed ID. |
| [`test_staff_can_list_and_read_everyones_reservations`](../reservations/tests/test_permissions.py#L141) | Preserve the explicitly required administrator exception. |
| [`test_reservation_read_endpoints_do_not_allow_direct_mutation`](../reservations/tests/test_permissions.py#L150) | Prevent unsupported owner/status editing and hard deletion outside the controlled actions. |

### test_validation.py

| Method | Fault it is intended to detect |
| --- | --- |
| [`test_time_order_and_past_start_are_rejected`](../reservations/tests/test_validation.py#L24) | Centralize the order and past-start rules used by both API flows. |
| [`test_duration_boundaries_follow_configured_settings`](../reservations/tests/test_validation.py#L35) | Exercise non-default limits and exact microsecond boundaries once, catching hardcoded durations. |
| [`test_company_date_and_working_hours`](../reservations/tests/test_validation.py#L51) | Centralize inclusive opening/closing boundaries and same-company-date validation using UTC inputs. |

## Overall project status

The backend for stages 1–7 is implemented: Django/DRF monolith, PostgreSQL Compose setup, core room/reservation models and internal idempotency record, token authentication, role/ownership permissions, availability, safe creation, and soft cancellation. All nine documented method/path combinations are exercised by API tests. Creation concurrency is additionally exercised over real local HTTP.

The checkout includes README setup/endpoint instructions, `.env.example`, short decisions, two application migrations, and this review report. Stage 8's final documentation/handoff review has not been performed as a separate delivery. Swagger is optional in the PDF and is not implemented. No frontend is part of this backend delivery, and no committed CI workflow is present.

Additional verification in this run:

| Check | Result |
| --- | --- |
| `python manage.py check --database default` | No issues |
| `python manage.py makemigrations --check --dry-run` | No changes detected |
| `python manage.py migrate --check` | Exit 0; no pending migrations |
| Live development database query | PostgreSQL 16.15; database `reservations`; `read committed` isolation |
| Live schema | `btree_gist`, `reservation_no_overlap`, `reservation_request_user_key`, and `reservation_request_response_pair` exist |
| Applied application migrations | `0001_initial`, `0002_reservationrequest` |
| Installed backend versions | Django 5.2.18, DRF 3.16.1, psycopg 3.3.6 |

## Limits of this evidence

- This is local PostgreSQL and Django's test HTTP server. Production deployment, a mobile client, load capacity, and frontend consumption were not verified.
- Cancellation tests use APIClient and verify sequential repeated cancellation. There is no separate simultaneous-cancellation stress test; creation concurrency results must not be attributed to cancellation.
- The cancellation conditional-update implementation is unchanged. No proof of all possible thread/process schedules is claimed by a finite concurrency test.
- Shared time tests are deterministic; they do not exercise every IANA timezone transition or every parser input.
- No code-coverage percentage or mutation score was measured. This report maps concrete behavior to named tests.
- No production code or public-contract change, new migration, or merge into develop is part of this step. Review the test-only branch relative to its cancellation parent; merging remains with the user.
