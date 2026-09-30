# Development

## Quality gates

```bash
make check
```

This runs:

| Check | Command |
|---|---|
| Python lint and format | `ruff check src tests` · `ruff format --check src tests` |
| Python types (strict) | `mypy` |
| Backend tests | `pytest` (real PostgreSQL, migrated from scratch) |
| Migration drift | `alembic check`, which fails if the models and migrations disagree |
| Frontend lint | `npm run lint` |
| Frontend types (strict) | `npm run typecheck` (`next typegen && tsc --noEmit`) |
| Frontend tests | `npm test` (Vitest + Testing Library) |

## Conventions

### Backend
* **Routes are thin.** Validate, call a service, return a schema. Business rules live in `services/` or an engine package.
* **Money and prices are `Decimal`,** never `float`, in every engine and DTO.
* **Timestamps are timezone-aware UTC** (`DateTime(timezone=True)`).
* **Every safety-relevant state change writes an audit record** in the same transaction.
* **Errors:** raise `AppError` subclasses (`core/errors.py`). The client gets `{"error": {code, message, correlation_id}}` and never a stack trace.
* **Logging:** `logger.info("msg", extra={...})`. Keys that look sensitive (`password`, `token`, `secret`, `api_key`…) are masked automatically, but don't rely on it. Never log credentials.
* **Strategies never import `broker_engine` adapters.** They see only domain types and market-data DTOs.

### Frontend
* **No trading logic in React.** Components display backend state and call the API through `src/lib`.
* **Never show invented numbers.** If data doesn't exist, show `—` and explain why (see `StatCard` and `PlannedFeature`).
* **Explain jargon** with `<Term id="…">` (definitions live in `src/lib/glossary.ts`).
* **Colour is semantic:** `positive`/`negative` for P/L, `warning` for attention, and `live` **only** for LIVE mode.
* `src/lib/types.ts` mirrors the backend schemas. Update both together.

## Adding a database change

```bash
# 1. edit/add models in backend/src/fxrobot/models/, export them from models/__init__.py
cd backend
.venv/bin/alembic revision --autogenerate -m "add signals table" --rev-id 0002
# 2. REVIEW the generated file: server defaults, enums, data migrations, downgrade
.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
.venv/bin/alembic check
```

## Adding an API endpoint

1. Add request and response models in `schemas/`.
2. Add business logic to a service. Audit if it changes state.
3. Add a thin route in `api/v1/<domain>.py`. Use `OwnerDep` for mutations and `CurrentUserDep` for reads.
4. Include the router in `api/v1/__init__.py`.
5. Add tests for auth (401/403), CSRF (403) for mutations, validation (422) and the happy path.

## Test fixtures

`backend/tests/conftest.py` provides `client`, `app_factory(**settings_overrides)`, `db`, `owner`, `viewer`, `owner_client`, and `login(client, email)`.
