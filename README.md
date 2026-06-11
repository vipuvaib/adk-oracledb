# adk-oracledb

Oracle Database integration package for Google ADK.

## Local .env Configuration

Local secrets and runtime settings can live in a repo-root `.env` file. The
examples load it without printing values. `.env` is ignored by git; use
`.env.example` as the safe template to copy from. `.venv` is for Python
packages, while `.env` is for runtime configuration and secrets.

The examples use these shared names:

- `ORACLE_AI_DB_USER`, `ORACLE_AI_DB_PASSWORD`, `ORACLE_AI_DB_DSN` for Oracle.
- `GENAI_MODEL`, `GENAI_ENDPOINT`, `GENAI_API_KEY` for the agent LLM.
- `EMBEDDING_MODEL`, `EMBEDDING_ENDPOINT`, `EMBEDDING_API_KEY` for memory embeddings.
- `EMBEDDING_ENCODING_FORMAT`, `EMBEDDING_INPUT_TYPE`,
  `EMBEDDING_QUERY_INPUT_TYPE`, and `EMBEDDING_DOCUMENT_INPUT_TYPE` for optional
  embedding request parameters.
- `ORACLE_SESSION_TABLE_PREFIX`, `ORACLE_MEMORY_TABLE_PREFIX`, and
  `ORACLE_ARTIFACT_TABLE_PREFIX` for optional table prefix defaults.

Avoid putting API keys or passwords in shell history. Explicit credentials in
`oracle://user:password@host:port/service` URIs are still supported, but the
examples prefer env-backed secret-free URIs.

## Smoke Test Commands

Core service smokes:

```bash
.venv/bin/python tests/smoke/session_smoke.py
.venv/bin/python tests/smoke/artifact_smoke.py
.venv/bin/python tests/smoke/memory_smoke.py
```

Example/e2e smokes:

```bash
.venv/bin/python examples/full_agent_oracle/run_smoke.py
.venv/bin/python examples/full_agent_oracle_tools/run_smoke.py
```

The memory and full-agent smokes require the memory extra plus embedding
provider configuration. `tests/smoke/artifact_smoke.py` directly tests
OracleArtifactService `inline_data`/binary support. The tool-agent example
intentionally demonstrates text and generated-PDF artifact flows only.

## OracleSessionService Smoke Tests

Current status: the `OracleSessionService` MVP works locally for basic session
storage against Oracle Database.

Required local setup:

- Oracle Database Free running locally, for example in Docker.
- An Oracle schema/user such as `ADK_USER` created with privileges to create
  tables, constraints, and indexes.

Configure the smoke tests with environment variables:

```bash
export ORACLE_AI_DB_USER=ADK_USER
export ORACLE_AI_DB_PASSWORD=...
export ORACLE_AI_DB_DSN=localhost:1521/FREEPDB1
export ORACLE_SESSION_TABLE_PREFIX=ADK_SMOKE
```

Run the manual smoke tests from the repository root:

```bash
.venv/bin/python tests/smoke/session_smoke.py
```

`tests/smoke/session_smoke.py` verifies automatic table creation, ServiceRegistry
construction, `create_session`, `get_session`, `list_sessions`,
`delete_session`, `append_event`, event reload as an ADK `Event`, and
persistence of event `actions.state_delta` into session state.

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
export ORACLE_AI_DB_USER=ADK_USER
export ORACLE_AI_DB_PASSWORD=...
export ORACLE_AI_DB_DSN=localhost:1521/FREEPDB1
export ORACLE_MEMORY_TABLE_PREFIX=ADK_MEMORY_SMOKE
export EMBEDDING_MODEL=...

.venv/bin/python tests/smoke/memory_smoke.py
```

Optional provider settings:

```bash
export EMBEDDING_ENDPOINT=...
export EMBEDDING_API_KEY=...
export EMBEDDING_ENCODING_FORMAT=float
export EMBEDDING_INPUT_TYPE=query
export GENAI_MODEL=...
export GENAI_ENDPOINT=...
export GENAI_API_KEY=...
```

Some OpenAI-compatible NIM embedding endpoints require
`EMBEDDING_ENCODING_FORMAT=float` and `EMBEDDING_INPUT_TYPE=query`. Leave these
unset for providers that do not need them. If a provider requires different
values for search-query embeddings and stored-memory embeddings, use
`EMBEDDING_QUERY_INPUT_TYPE` and `EMBEDDING_DOCUMENT_INPUT_TYPE` instead of the
single `EMBEDDING_INPUT_TYPE`.

MCP tools are not implemented yet.

## OracleArtifactService Status

`OracleArtifactService` has initial schema, save/load, list/delete, and version
metadata wiring. Manual artifact operation smoke has passed locally.

## OracleArtifactService Smoke Test

Configure Oracle connection settings:

```bash
export ORACLE_AI_DB_USER=ADK_USER
export ORACLE_AI_DB_PASSWORD=...
export ORACLE_AI_DB_DSN=localhost:1521/FREEPDB1
export ORACLE_ARTIFACT_TABLE_PREFIX=ADK_ART_SMOKE
```

Run the artifact smoke test from the repository root:

```bash
.venv/bin/python tests/smoke/artifact_smoke.py
```
The reusable OracleArtifactService smoke test has passed locally against Oracle Database Free.

The smoke script verifies text artifact versioning, binary `inline_data`
round-trip, ADK `user:` namespace behavior, key listing, version metadata, and
delete behavior.

## ServiceRegistry oracle:// Support

To use `oracle://` URIs with ADK CLI service options, register the Oracle
factories from your agent's `services.py`:

```python
from adk_oracledb.registry import register_oracle_services

register_oracle_services()
```

Then run ADK with Oracle-backed services:

```bash
adk web my_agent \
  --session_service_uri 'oracle://?table_prefix=ADK' \
  --memory_service_uri 'oracle://?memory_table_prefix=ADK_MEMORY' \
  --artifact_service_uri 'oracle://?artifact_table_prefix=ADK_ART'
```

Credentials and DSN may be omitted from `oracle://` URIs when
`ORACLE_AI_DB_USER`, `ORACLE_AI_DB_PASSWORD`, and `ORACLE_AI_DB_DSN` are set in
the environment. Passwords with special characters must be URL-encoded only
when they are included in the URI. Table prefixes can be supplied in URI query
parameters or with env vars such as `ORACLE_SESSION_TABLE_PREFIX`,
`ORACLE_MEMORY_TABLE_PREFIX`, and `ORACLE_ARTIFACT_TABLE_PREFIX`. If the default
prefixes are acceptable, bare `oracle://` URIs are also valid with env fallback.
The memory URI requires the memory extra and an embedder model from
`EMBEDDING_MODEL` or an explicit `embedder_model` query parameter. Registration
itself does not connect to Oracle.

For example:

```bash
.venv/bin/adk run examples/full_agent_oracle_tools \
  --session_service_uri 'oracle://?table_prefix=ADK_TOOLS_AGENT' \
  --memory_service_uri 'oracle://?memory_table_prefix=ADK_TOOLS_AGENT_MEMORY' \
  --artifact_service_uri 'oracle://?artifact_table_prefix=ADK_TOOLS_AGENT_ART'
```

## Full ADK Agent Examples

`examples/full_agent_oracle` shows registry-backed Oracle services with a small
loadable ADK agent. `examples/full_agent_oracle_tools` adds explicit
memory/artifact tool usage, travel planning, and text/generated-PDF artifact
round trips with local artifact export.
