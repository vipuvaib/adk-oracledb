# Oracle ADK Tool Agent Example

This example is the tool-enabled companion to `examples/full_agent_oracle`.
The simpler example proves ADK loading and `oracle://` registry-backed services.
This example proves explicit agent tool usage of Oracle-backed memory and
artifacts:

- `remember_travel_preference` writes directly to `OracleMemoryService`.
- `recall_travel_preferences` searches `OracleMemoryService`.
- `save_itinerary_artifact` saves a text artifact with `OracleArtifactService`.
- `load_itinerary_artifact` loads the saved artifact.

The tools use ADK `ToolContext` public APIs for memory and artifacts.

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
export ORACLE_TOOLS_AGENT_SESSION_TABLE_PREFIX=ADK_TOOLS_AGENT
export ORACLE_TOOLS_AGENT_MEMORY_TABLE_PREFIX=ADK_TOOLS_AGENT_MEMORY
export ORACLE_TOOLS_AGENT_ARTIFACT_TABLE_PREFIX=ADK_TOOLS_AGENT_ART
```

Optional explicit embedder settings:

```bash
export ORACLE_MEMORY_EMBEDDER_API_BASE=...
export ORACLE_MEMORY_EMBEDDER_API_KEY=...
```

## Run The Noninteractive Smoke

Install the memory extra first because this smoke exercises
`OracleMemoryService`:

```bash
pip install -e ".[memory]"
.venv/bin/python examples/full_agent_oracle_tools/run_smoke.py
```

The smoke script does not call an LLM. It loads the agent, registers
`oracle://` services through this folder's `services.py`, creates services
through ADK `ServiceRegistry`, and calls the tool functions directly with a
minimal context adapter backed by the registry-created Oracle services.

## Run With ADK

`adk run` loads this folder's `services.py`, so the Oracle factories are
registered before the service URIs are used:

```bash
adk run examples/full_agent_oracle_tools \
  --session_service_uri 'oracle://ADK_USER:...@localhost:1521/FREEPDB1?table_prefix=ADK_TOOLS_AGENT' \
  --memory_service_uri 'oracle://ADK_USER:...@localhost:1521/FREEPDB1?memory_table_prefix=ADK_TOOLS_AGENT_MEMORY&embedder_model=embed-english-light-v3.0' \
  --artifact_service_uri 'oracle://ADK_USER:...@localhost:1521/FREEPDB1?artifact_table_prefix=ADK_TOOLS_AGENT_ART'
```

If running `adk web examples`, ADK loads `services.py` from `examples/`.
In that layout, ensure `examples/services.py` also calls
`register_oracle_services()` before using the same URI flags:

```bash
adk web examples \
  --session_service_uri 'oracle://ADK_USER:...@localhost:1521/FREEPDB1?table_prefix=ADK_TOOLS_AGENT' \
  --memory_service_uri 'oracle://ADK_USER:...@localhost:1521/FREEPDB1?memory_table_prefix=ADK_TOOLS_AGENT_MEMORY&embedder_model=embed-english-light-v3.0' \
  --artifact_service_uri 'oracle://ADK_USER:...@localhost:1521/FREEPDB1?artifact_table_prefix=ADK_TOOLS_AGENT_ART'
```

Passwords with special characters must be URL-encoded. Interactive ADK runs may
require normal model/provider credentials in addition to memory embedder
credentials.
