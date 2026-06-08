# Full Oracle ADK Agent Example

This example shows the full package path:

- ADK loads `root_agent` from `agent.py`.
- ADK loads `services.py`.
- `services.py` registers `oracle://` service factories from `adk-oracledb`.
- Session, memory, and artifact services are created through ADK `ServiceRegistry`.

The noninteractive smoke script does not call an LLM. It verifies agent loading,
service registration, Oracle session persistence, memory add/search, and artifact
save/load/version/delete behavior through registry-created services.

## Required Environment

The example loads a repo-root `.env` file if present. Use the canonical names
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
```

Optional table prefixes:

```bash
export ORACLE_SESSION_TABLE_PREFIX=ADK_FULL_AGENT
export ORACLE_MEMORY_TABLE_PREFIX=ADK_FULL_AGENT_MEMORY
export ORACLE_ARTIFACT_TABLE_PREFIX=ADK_FULL_AGENT_ART
```

## Run The Smoke

Install the memory extra first because this smoke exercises
`OracleMemoryService`:

```bash
pip install -e ".[memory]"
.venv/bin/python examples/full_agent_oracle/run_smoke.py
```

The script does not print passwords or provider API keys.

## Run With ADK

The agent itself is intentionally small. To use it through ADK with Oracle-backed
services, keep `services.py` in the directory ADK loads for this agent and pass
`oracle://` service URIs. If Oracle credentials are in `.env` or shell env, the
URIs can omit username/password.

Example URI shape:

```bash
adk run examples/full_agent_oracle \
  --session_service_uri 'oracle://?table_prefix=ADK_FULL_AGENT' \
  --memory_service_uri 'oracle://?memory_table_prefix=ADK_FULL_AGENT_MEMORY' \
  --artifact_service_uri 'oracle://?artifact_table_prefix=ADK_FULL_AGENT_ART'
```

Interactive ADK runs may require normal model/provider credentials in addition
to the memory embedder credentials. `GENAI_MODEL` configures the agent LLM;
`EMBEDDING_MODEL` configures memory embeddings.
