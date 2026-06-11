# Oracle Runtime Services Agent

This example shows the complete ADK runtime-service path with Oracle Database:

- ADK loads `root_agent` from `agent.py`.
- ADK loads `services.py`.
- `services.py` registers `oracle://` service factories from `adk-oracledb`.
- Session, memory, and artifact services are created through ADK
  `ServiceRegistry`.

The validation script exercises agent loading, service registration, Oracle
session persistence, memory add/search, and artifact save/load/version/delete
behavior through registry-created services.

## Required environment

The example loads a repo-root `.env` file when present. Use the canonical names
from `.env.example`:

```bash
ORACLE_AI_DB_USER=ADK_USER
ORACLE_AI_DB_PASSWORD=...
ORACLE_AI_DB_DSN=localhost:1521/FREEPDB1
GENAI_MODEL=...
GENAI_ENDPOINT=...
GENAI_API_KEY=...
EMBEDDING_MODEL=...
EMBEDDING_ENDPOINT=...
EMBEDDING_API_KEY=...
EMBEDDING_ENCODING_FORMAT=
EMBEDDING_INPUT_TYPE=
EMBEDDING_QUERY_INPUT_TYPE=
EMBEDDING_DOCUMENT_INPUT_TYPE=
```

Some OpenAI-compatible embedding endpoints require request parameters such as
`EMBEDDING_ENCODING_FORMAT=float`. For asymmetric providers, use
`EMBEDDING_QUERY_INPUT_TYPE` for search queries and
`EMBEDDING_DOCUMENT_INPUT_TYPE` for stored memory records.

Optional table prefixes:

```bash
export ORACLE_SESSION_TABLE_PREFIX=ADK_RUNTIME_AGENT
export ORACLE_MEMORY_TABLE_PREFIX=ADK_RUNTIME_AGENT_MEMORY
export ORACLE_ARTIFACT_TABLE_PREFIX=ADK_RUNTIME_AGENT_ART
```

## Run the validation flow

Install the memory extra first because this validation exercises
`OracleMemoryService`:

```bash
pip install -e ".[memory]"
.venv/bin/python examples/oracle_runtime_agent/run_smoke.py
```

The script does not print passwords or provider API keys.

## Run with ADK

Keep `services.py` in the directory ADK loads for this agent and pass
`oracle://` service URIs. If Oracle credentials are in `.env` or shell env, the
URIs can omit username/password.

```bash
adk run examples/oracle_runtime_agent \
  --session_service_uri 'oracle://?table_prefix=ADK_RUNTIME_AGENT' \
  --memory_service_uri 'oracle://?memory_table_prefix=ADK_RUNTIME_AGENT_MEMORY' \
  --artifact_service_uri 'oracle://?artifact_table_prefix=ADK_RUNTIME_AGENT_ART'
```

Interactive ADK runs use `GENAI_MODEL` for the agent LLM and
`EMBEDDING_MODEL` for memory embeddings.
