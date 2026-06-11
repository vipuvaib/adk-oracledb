# Oracle Travel Agent

This example is a tool-enabled ADK travel planner backed by Oracle Database. It
uses Oracle-backed ADK memory for durable travel preferences and Oracle-backed
ADK artifacts for generated itineraries and PDFs.

The tools demonstrate:

- `remember_travel_preference` writes durable preferences to
  `OracleMemoryService`.
- `recall_travel_preferences` searches `OracleMemoryService`.
- `plan_trip` builds a planning brief from recalled preferences so the agent can
  write a detailed itinerary.
- `save_text_artifact` saves text artifacts.
- `save_itinerary_artifact` saves durable itinerary text artifacts.
- `generate_and_save_itinerary_pdf` stores a generated PDF artifact and a
  companion text artifact.
- `list_saved_artifacts` lists artifacts visible to the current ADK context.
- `load_artifact` loads saved text artifacts and PDF companion metadata.
- `export_artifact_to_file` writes stored artifacts to local files under
  `examples/oracle_travel_agent/exports/`.

The tools use ADK `ToolContext` public APIs for memory and artifacts.

Long-term memory is app + user scoped by `OracleMemoryService`. Session context
is handled separately by `OracleSessionService` through session state and event
history.

Normal artifact filenames are session scoped. Filenames beginning with `user:`
are user scoped and can be loaded across sessions for the same app/user. The
tools preserve ADK's artifact scoping rules, so use the `user:` prefix when an
itinerary or PDF should be durable across sessions.

Generated PDFs are stored as Oracle-backed ADK artifacts. The source itinerary
text is saved as a companion `.txt` artifact so the agent can retrieve and
discuss the itinerary later. Exported files are ignored by git through
`exports/.gitignore`.

## Required environment

The example loads a repo-root `.env` file when present. Use the canonical names
from `.env.example`:

```bash
ORACLE_AI_DB_USER=
ORACLE_AI_DB_PASSWORD=
ORACLE_AI_DB_DSN=

GENAI_MODEL=
GENAI_ENDPOINT=
GENAI_API_KEY=

EMBEDDING_MODEL=
EMBEDDING_ENDPOINT=
EMBEDDING_API_KEY=
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
export ORACLE_SESSION_TABLE_PREFIX=ADK_TRAVEL_AGENT
export ORACLE_MEMORY_TABLE_PREFIX=ADK_TRAVEL_AGENT_MEMORY
export ORACLE_ARTIFACT_TABLE_PREFIX=ADK_TRAVEL_AGENT_ART
```

## Run the validation flow

Install the memory extra first because this validation exercises
`OracleMemoryService`:

```bash
pip install -e ".[memory]"
.venv/bin/python examples/oracle_travel_agent/run_smoke.py
```

The validation flow loads the agent, registers `oracle://` services through this
folder's `services.py`, creates services through ADK `ServiceRegistry`, and calls
the tool functions directly with a context adapter backed by the registry-created
Oracle services.

It covers:

- memory write/search
- preference-aware trip planning
- text artifact round-trip
- generated PDF artifact round-trip plus companion text
- artifact listing
- local PDF export

## Run with ADK

`adk run` loads this folder's `services.py`, so the Oracle factories are
registered before the service URIs are used:

```bash
adk run examples/oracle_travel_agent \
  --session_service_uri 'oracle://?table_prefix=ADK_TRAVEL_AGENT' \
  --memory_service_uri 'oracle://?memory_table_prefix=ADK_TRAVEL_AGENT_MEMORY' \
  --artifact_service_uri 'oracle://?artifact_table_prefix=ADK_TRAVEL_AGENT_ART'
```

If running `adk web examples`, ADK loads `services.py` from `examples`. In that
layout, ensure `examples/services.py` calls `register_oracle_services()` before
using the same URI flags:

```bash
adk web examples \
  --session_service_uri 'oracle://?table_prefix=ADK_TRAVEL_AGENT' \
  --memory_service_uri 'oracle://?memory_table_prefix=ADK_TRAVEL_AGENT_MEMORY' \
  --artifact_service_uri 'oracle://?artifact_table_prefix=ADK_TRAVEL_AGENT_ART'
```

Credentials can stay in `.env` or shell env. Passwords with special characters
should be URL-encoded when placed directly in a URI. Interactive ADK runs use
`GENAI_MODEL` for the agent LLM and `EMBEDDING_MODEL` for memory embeddings.

## Interactive prompts

Try prompts like:

```text
Remember that I prefer 8-day mid-budget trekking and cultural trips.
Plan an 8-day mid-budget trip to Nepal using my preferences with morning/afternoon/evening details.
Save that itinerary as user:nepal_itinerary.
Generate and save that itinerary as PDF named user:nepal_itinerary.pdf.
List my saved artifacts.
Load user:nepal_itinerary.pdf.
Export user:nepal_itinerary.pdf to nepal_itinerary.pdf.
Load user:nepal_itinerary.txt.
```
