# Oracle ADK Tool Agent Example

This example is the tool-enabled companion to `examples/full_agent_oracle`.
The simpler example proves ADK loading and `oracle://` registry-backed services.
This example proves explicit agent tool usage of Oracle-backed memory and
artifacts:

- `remember_travel_preference` writes directly to `OracleMemoryService`.
- `recall_travel_preferences` searches `OracleMemoryService`.
- `plan_trip` creates a planning brief from recalled preferences so the model
  can write a rich itinerary using its own travel knowledge.
- `save_text_artifact` and `save_itinerary_artifact` save text artifacts.
- `generate_and_save_itinerary_pdf` stores a generated PDF artifact and a
  companion text artifact.
- `save_base64_artifact` stores PDF, image, or generic file bytes.
- `load_artifact` loads text and binary artifacts.
- `export_artifact_to_file` writes stored artifacts to local files under
  `examples/full_agent_oracle_tools/exports/`.

The tools use ADK `ToolContext` public APIs for memory and artifacts.

Long-term memory is app + user scoped by `OracleMemoryService`. Session context
is separate from long-term memory; session state/events remain in
`OracleSessionService`.

Normal artifact filenames are session scoped. Filenames beginning with `user:`
are user scoped and can be loaded across sessions for the same app/user. PDF,
image, and binary artifact support uses `inline_data` bytes stored by
`OracleArtifactService`.

The interactive agent can save PDFs/images only through tools that generate
bytes or receive base64 data. File upload support from ADK web UI is separate
future work and may require inspecting ADK file-upload pathways.

Generated PDFs are binary artifacts. The source itinerary text is saved
separately as a companion `.txt` artifact so the agent can retrieve and discuss
the itinerary later. Exported files are ignored by git through
`exports/.gitignore`.

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

The smoke covers:

- memory write/search
- preference-aware trip planning
- text artifact round-trip
- generated PDF artifact round-trip plus companion text
- local PDF export
- PNG image artifact round-trip plus local export
- generic binary artifact round-trip plus local export

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

## Interactive Prompts

Try prompts like:

```text
Remember that I prefer 8-day mid-budget trekking and cultural trips.
Plan an 8-day mid-budget trip to Nepal using my preferences with morning/afternoon/evening details.
Save that itinerary as user:nepal_itinerary.
Generate and save that itinerary as PDF named user:nepal_itinerary.pdf.
Load user:nepal_itinerary.pdf.
Export user:nepal_itinerary.pdf to nepal_itinerary.pdf.
Load user:nepal_itinerary.txt.
```
