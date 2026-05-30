# Flow Design: PostgreSQL Relational Database Migration

This document defines the migration from a shared SQLite file to PostgreSQL for relational application state. Qdrant remains the vector database; PostgreSQL owns relational tables such as broker/TROIS registries, classification rules, audit logs, and calculation history.

---

## 1. Intent

* **User Goal:** Run SmartKeden with a reliable relational database that supports concurrent backend access and does not block parallel test execution.
* **Success Criteria:**
  - Docker development stack includes PostgreSQL.
  - Backend reads relational DB connection from `DATABASE_URL` and works with PostgreSQL.
  - SQLite remains available as a fallback/local default when `DATABASE_URL` is not set.
  - Existing SQLAlchemy models and DB-dependent APIs continue to work.
  - Test strategy can isolate DB-writing tests from the production/dev database.
* **Non-negotiables:**
  - Qdrant vector storage is not replaced by PostgreSQL.
  - No production-like code should hard-code SQLite-specific behavior.
  - Existing app startup table creation can remain for this slice, but must be compatible with PostgreSQL.
  - No destructive migration of user data is performed in this slice.

---

## 2. Scope

* **In Scope:**
  - Add PostgreSQL service and volume to Docker Compose.
  - Set backend `DATABASE_URL` to PostgreSQL inside Docker.
  - Add PostgreSQL Python driver dependency.
  - Make SQLAlchemy engine settings backend-agnostic.
  - Add documented test commands for parallel-safe split.
  - Verify DB-dependent tests against the configured local environment where possible.
* **Out of Scope / Deferred:**
  - Alembic migration framework.
  - Migrating existing `customs_ai.db` data into PostgreSQL.
  - Per-xdist-worker PostgreSQL database provisioning.
  - Replacing JSON config files (`data/config.json`) with PostgreSQL.

---

## 3. Actors and Permissions

| Actor | Can Do | Cannot Do |
| :--- | :--- | :--- |
| **Backend service** | Connect to configured relational database, create tables at startup, read/write ORM models | Choose a database different from `DATABASE_URL` |
| **Developer / CI** | Run Docker Compose with PostgreSQL and Qdrant, run tests with explicit DB URL | Accidentally run tests against production DB |
| **PostgreSQL service** | Persist relational state in `postgres_data` volume | Store vector embeddings; Qdrant remains owner |

---

## 4. Diagrams

### User / Operator Flow

```mermaid
flowchart TD
  A[Developer starts Docker Compose] --> B{PostgreSQL healthy?}
  B -->|No| C[Backend waits/fails visibly]
  B -->|Yes| D[Backend reads DATABASE_URL]
  D --> E{DATABASE_URL is PostgreSQL?}
  E -->|Yes| F[SQLAlchemy connects with pooling]
  E -->|No / unset| G[Fallback SQLite local mode]
  F --> H[Startup creates tables + seeds brokers]
  G --> H
  H --> I[APIs use SessionLocal]
```

### State Machine

```mermaid
stateDiagram-v2
  [*] --> Unconfigured
  Unconfigured --> SQLiteFallback: DATABASE_URL unset
  Unconfigured --> PostgresConfigured: DATABASE_URL postgresql+psycopg://...
  PostgresConfigured --> Ready: connection succeeds and tables exist
  PostgresConfigured --> Failed: connection/auth/schema failure
  SQLiteFallback --> Ready: local file usable
  Ready --> Ready: normal API reads/writes
  Failed --> [*]
```

### Data Flow

```mermaid
flowchart LR
  Compose[docker-compose.yml] --> Env[backend DATABASE_URL]
  Env --> Settings[Settings.DATABASE_URL]
  Settings --> Engine[SQLAlchemy engine]
  Engine --> Sessions[SessionLocal]
  Sessions --> APIs[Admin Rules / Registries / Orchestrator Tools]
  APIs --> PG[(PostgreSQL postgres_data)]
  APIs --> Qdrant[(Qdrant vector DB remains separate)]
```

---

## 5. State and Projections

### Authoritative State

| State | Owner | Description |
| :--- | :--- | :--- |
| Relational tables | PostgreSQL | Brokers, TROIS, classification rules, audit logs, calculation history |
| Vector indexes | Qdrant | Legal RAG, HS code vectors, risk profiles |
| Local fallback DB | SQLite | Developer-only fallback if `DATABASE_URL` not set |

### Configuration Contract

| Variable | Example | Required In Docker | Notes |
| :--- | :--- | :--- | :--- |
| `DATABASE_URL` | `postgresql+psycopg://smartkeden:smartkeden@postgres:5432/smartkeden` | yes | Backend relational DB |
| `POSTGRES_DB` | `smartkeden` | yes | PostgreSQL database name |
| `POSTGRES_USER` | `smartkeden` | yes | Dev username |
| `POSTGRES_PASSWORD` | `smartkeden` | yes | Dev password; production must override |

---

## 6. Events/Actions

| Direction | Name | Source/Target | Payload | Allowed When | Reject/Failure Reason |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Incoming | `database:configured` | Docker/env → Backend | `{DATABASE_URL}` | Backend startup | Invalid URL/driver missing |
| Internal | `database:engine_created` | Settings → SQLAlchemy | `{url, connect_args, pool_options}` | Config loaded | Unsupported dialect |
| Internal | `database:schema_initialized` | Backend lifespan → DB | `Base.metadata.create_all` | DB reachable | Auth/network/schema failure |
| Outgoing | `database:session_requested` | API/tool → SessionLocal | `Session` | Request processing | DB unavailable |

---

## 7. Edge Cases

* **PostgreSQL container not ready:** backend startup should fail visibly or wait via Compose dependency; this slice uses Compose dependency and SQLAlchemy failure visibility.
* **SQLite fallback still used outside Docker:** allowed only when `DATABASE_URL` is unset; useful for isolated local scripts.
* **Tests accidentally hit dev Postgres:** test command must set an explicit test DB URL or use the existing sequential split until per-worker DBs exist.
* **Parallel xdist DB tests:** not fully solved until per-worker DB isolation is implemented; this slice removes runtime SQLite but does not automatically make DB-writing tests parallel-safe.
* **Existing SQLite data:** not migrated; developers must re-seed or migrate manually in a later data migration.
* **Driver missing:** backend container must install `psycopg[binary]`.

---

## 8. Side Effects

* Docker Compose creates a persistent `postgres_data` volume.
* Backend relational writes go to PostgreSQL in Docker instead of `customs_ai.db`.
* Local fallback may still create `customs_ai.db` when running outside Docker without `DATABASE_URL`.
* DB-dependent tests may need explicit environment variables when run against PostgreSQL.

---

## 9. Schemas Touched

* `docker-compose.yml` — add PostgreSQL service, volume, backend dependency and `DATABASE_URL`.
* `backend/requirements.txt` — add PostgreSQL driver.
* `backend/app/core/database.py` — dialect-aware engine options.
* `backend/app/core/config.py` — keep default fallback and document relational DB config.
* `backend/pytest.ini` — optional markers for sequential DB-writing tests if implemented.
* `backend/tests/test_database.py`, `backend/tests/test_admin_rules_api.py` — optional sequential markers if implemented.

---

## 10. Targeted Tests

| Layer | Behavior | File/Command | Status |
| :--- | :--- | :--- | :--- |
| Unit | SQLite fallback engine still imports | `.venv/Scripts/pytest backend/tests/test_database.py backend/tests/test_admin_rules_api.py` with default SQLite fallback | Passed: `30 passed, 2 warnings` |
| Integration | PostgreSQL Docker backend can create tables and seed brokers | `wsl.exe -d Ubuntu --cd /mnt/e/projects/smartkeden -- docker compose up -d --build` + backend health check | Passed: services up, Postgres healthy, backend `/` healthy |
| Regression | DB CRUD tests still pass against PostgreSQL in container | `docker compose exec -T backend pytest tests/test_database.py tests/test_admin_rules_api.py` | Passed: `30 passed, 2 warnings` |
| Test Infra | Parallel-safe tests can run with DB-writing files excluded | `docker compose exec -T backend pytest -n 2 --dist loadscope -m \"not sequential\" tests/test_database.py tests/test_admin_rules_api.py tests/test_calculation.py` | Passed: `4 passed, 5 warnings` |

---

## 11. Implementation Plan

1. Add `postgres` service and `postgres_data` volume to `docker-compose.yml`.
2. Add `DATABASE_URL` to backend environment and make backend depend on PostgreSQL.
3. Add `psycopg[binary]` to backend requirements.
4. Adjust `database.py` to use SQLite-specific connect args only for SQLite and pooling options for PostgreSQL.
5. Optionally mark DB-writing tests as sequential and document the split.
6. Rebuild backend container and run DB-targeted tests.
7. Fill implementation trace.

---

## 12. Implementation Trace

* **Flow Review:** Approved before implementation. The flow keeps SQLite fallback, moves Docker runtime to PostgreSQL, and leaves full per-worker DB isolation deferred.
* **Code / Config Files:**
  - `docker-compose.yml` — added PostgreSQL service, healthcheck, `postgres_data` volume, and backend `DATABASE_URL`.
  - `backend/requirements.txt` — added `psycopg[binary]` and explicit `pytest-asyncio`.
  - `backend/app/core/database.py` — added dialect-aware SQLAlchemy engine options.
  - `backend/pytest.ini` — added `sequential` marker.
  - `backend/tests/test_database.py` and `backend/tests/test_admin_rules_api.py` — marked DB-writing tests as sequential.
* **Validation:**
  - `.venv/Scripts/ruff check backend/app/core/database.py backend/tests/test_database.py backend/tests/test_admin_rules_api.py` → `OK`.
  - `.venv/Scripts/pytest backend/tests/test_database.py backend/tests/test_admin_rules_api.py` with default SQLite fallback → `30 passed, 2 warnings`.
  - `wsl.exe -d Ubuntu --cd /mnt/e/projects/smartkeden -- docker compose up -d --build` → built and started `postgres`, `qdrant`, `backend`, `frontend`.
  - `wsl.exe -d Ubuntu --cd /mnt/e/projects/smartkeden -- docker compose ps` → `smartkeden-postgres` healthy, backend/frontend/qdrant up.
  - `python -c \"import urllib.request; ... http://localhost:8000/\"` → backend health JSON returned.
  - `wsl.exe -d Ubuntu --cd /mnt/e/projects/smartkeden -- docker compose exec -T backend pytest tests/test_database.py tests/test_admin_rules_api.py` → `30 passed, 2 warnings`.
  - `wsl.exe -d Ubuntu --cd /mnt/e/projects/smartkeden -- docker compose exec -T backend pytest -n 2 --dist loadscope -m \"not sequential\" tests/test_database.py tests/test_admin_rules_api.py tests/test_calculation.py` → `4 passed, 5 warnings`.
* **Observed Local Limitation:** Windows-local `DATABASE_URL=postgresql+psycopg://...@localhost:5432/smartkeden` connected to a different/local PostgreSQL listener where role `smartkeden` did not exist. Docker/container verification is authoritative for this slice.

---

## 13. Open Questions

* **Deferred:** Should existing `customs_ai.db` data be migrated into PostgreSQL? This slice does not migrate historical local data.
* **Deferred:** Should tests provision per-worker PostgreSQL DBs for full xdist? This slice keeps the safe split.
* **Deferred:** Should Alembic replace `Base.metadata.create_all()`? Recommended next step after PostgreSQL runtime is stable.

---

## 14. Review Checklist

| Item | Status |
| :--- | :--- |
| Intent describes intended behavior, not current implementation | Ready |
| Diagrams include decisions and rejection paths | Ready |
| Forbidden paths and permissions are explicit | Ready |
| Edge cases are concrete and testable | Ready |
| Schemas/files expected to change are named | Ready |
| Tests map to behavior paths | Ready |
| Cross-flow boundaries declared | Ready |
| Open questions are explicit/deferred | Ready |
