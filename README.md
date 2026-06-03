# adk-oracledb

Oracle Database integration package for Google ADK.

## OracleSessionService Smoke Tests

Current status: the `OracleSessionService` MVP works locally for basic session
storage against Oracle Database.

Required local setup:

- Oracle Database Free running locally, for example in Docker.
- An Oracle schema/user such as `ADK_USER` created with privileges to create
  tables, constraints, and indexes.

Configure the smoke tests with environment variables:

```bash
export ORACLE_USER=ADK_USER
export ORACLE_PASSWORD=...
export ORACLE_DSN=localhost:1521/FREEPDB1
export ORACLE_TABLE_PREFIX=ADK_SMOKE
```

Run the manual smoke tests from the repository root:

```bash
.venv/bin/python examples/session_smoke.py
.venv/bin/python examples/session_append_event_smoke.py
```

`examples/session_smoke.py` verifies automatic table creation plus
`create_session`, `get_session`, `list_sessions`, and `delete_session`.

`examples/session_append_event_smoke.py` verifies `append_event`, event reload as
an ADK `Event`, and persistence of event `actions.state_delta` into session
state.

OracleSessionService smoke tests have passed locally against Oracle Database Free with `python-oracledb` 4.0.1 and 3.4.2.
The 3.4.2 check is useful because Oracle memory work will integrate through `oracleagentmemory`, which currently uses the `python-oracledb` 3.x dependency line.

## OracleMemoryService Status

`OracleMemoryService` has initial search, direct `add_memory`, event ingestion,
and session ingestion wiring. Real Oracle/oracleagentmemory smoke tests are
still pending.

Install memory dependencies with:

```bash
pip install "adk-oracledb[memory]"
```

## OracleMemoryService Smoke Test

`OracleMemoryService` has initial method wiring for search, direct memory writes,
event ingestion, and session ingestion. The current manual memory smoke test
only verifies direct `add_memory` plus `search_memory`.

The manual OracleMemoryService smoke test has passed locally using
`oracleagentmemory` 26.4.0, `python-oracledb` 3.4.2, Oracle Database Free,
and Cohere `embed-english-light-v3.0`.

Install the memory extra in a local development checkout:

```bash
pip install -e ".[memory]"
```

`oracleagentmemory` 26.4.0 currently requires `oracledb>=3.4.2,<4`.

The Oracle user may need additional privileges beyond the session smoke tests.
Run grants like these as `SYSTEM` or another admin user if needed:

```sql
GRANT CREATE SESSION TO ADK_USER;
GRANT CREATE TABLE TO ADK_USER;
GRANT CREATE SEQUENCE TO ADK_USER;
GRANT CREATE VIEW TO ADK_USER;
GRANT CREATE PROCEDURE TO ADK_USER;
```

The memory smoke test requires an embedding model configuration. Depending on
the model/provider, `oracleagentmemory` may call an external embedding service.

```bash
export ORACLE_USER=ADK_USER
export ORACLE_PASSWORD=...
export ORACLE_DSN=localhost:1521/FREEPDB1
export ORACLE_MEMORY_TABLE_PREFIX=ADK_MEMORY_SMOKE
export ORACLE_MEMORY_EMBEDDER_MODEL=...

.venv/bin/python examples/memory_smoke.py
```

Optional provider settings:

```bash
export ORACLE_MEMORY_EMBEDDER_API_BASE=...
export ORACLE_MEMORY_EMBEDDER_API_KEY=...
export ORACLE_MEMORY_LLM_MODEL=...
export ORACLE_MEMORY_LLM_API_BASE=...
export ORACLE_MEMORY_LLM_API_KEY=...
```

Artifacts, registry, and MCP tools are not implemented yet.

## OracleArtifactService Status

`OracleArtifactService` has initial schema, save/load, list/delete, and version
metadata wiring. Manual artifact operation smoke has passed locally. A reusable
artifact smoke script is not added yet.
