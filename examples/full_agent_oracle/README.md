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

```bash
export ORACLE_USER=ADK_USER
export ORACLE_PASSWORD=...
export ORACLE_DSN=localhost:1521/FREEPDB1
export ORACLE_MEMORY_EMBEDDER_MODEL=embed-english-light-v3.0
export COHERE_API_KEY=...
```

Optional table prefixes:

```bash
export ORACLE_FULL_AGENT_SESSION_TABLE_PREFIX=ADK_FULL_AGENT
export ORACLE_FULL_AGENT_MEMORY_TABLE_PREFIX=ADK_FULL_AGENT_MEMORY
export ORACLE_FULL_AGENT_ARTIFACT_TABLE_PREFIX=ADK_FULL_AGENT_ART
```

Optional explicit embedder settings:

```bash
export ORACLE_MEMORY_EMBEDDER_API_BASE=...
export ORACLE_MEMORY_EMBEDDER_API_KEY=...
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
`oracle://` service URIs. Passwords with special characters must be URL-encoded.

Example URI shape:

```bash
adk run examples/full_agent_oracle \
  --session_service_uri 'oracle://ADK_USER:...@localhost:1521/FREEPDB1?table_prefix=ADK_FULL_AGENT' \
  --memory_service_uri 'oracle://ADK_USER:...@localhost:1521/FREEPDB1?memory_table_prefix=ADK_FULL_AGENT_MEMORY&embedder_model=embed-english-light-v3.0' \
  --artifact_service_uri 'oracle://ADK_USER:...@localhost:1521/FREEPDB1?artifact_table_prefix=ADK_FULL_AGENT_ART'
```

Interactive ADK runs may require normal model/provider credentials in addition
to the memory embedder credentials.
