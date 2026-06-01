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

Memory, artifacts, registry, and MCP tools are not implemented yet.
