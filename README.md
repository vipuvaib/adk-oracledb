# adk-oracledb

Oracle Database backend services for Google ADK Python.

`adk-oracledb` lets ADK agents use Oracle Database as the durable runtime
backend for sessions, long-term memory, and artifacts. Agents remain standard
Google ADK agents; Oracle is selected through ADK service configuration and the
`oracle://` service registry scheme.

## What it provides

- `OracleSessionService` for ADK sessions, state, and event history.
- `OracleMemoryService` for durable semantic memory through `oracleagentmemory`.
- `OracleArtifactService` for ADK artifacts such as text and generated PDFs,
  with versions and metadata.
- `oracle://` ServiceRegistry factories for ADK CLI and ADK Web.
- Example ADK agents that run with Oracle-backed sessions, memory, and
  artifacts.

## Why Oracle Database for ADK agents

Agent applications need more than a vector store. They need durable session
state, replayable event history, scoped long-term memory, generated files,
metadata, and enterprise database controls. Oracle Database brings these pieces
into one backend:

- Native JSON stores ADK session state, event payloads, and artifact metadata.
- Transactions keep session event append and state updates in one durable
  boundary.
- Oracle Agent Memory and Oracle vector capabilities support semantic memory
  retrieval.
- BLOB-backed artifact storage keeps generated files together with metadata
  and versions.
- A single Oracle schema can back multiple ADK apps through configurable table
  prefixes.

## How it operates

```text
ADK CLI / ADK Web
        |
        v
ADK Runner and Agent
        |
        v
ADK ServiceRegistry
        |
        v
oracle:// service factories
        |
        +--> OracleSessionService  --> Oracle Database
        +--> OracleMemoryService   --> Oracle Database / oracleagentmemory
        +--> OracleArtifactService --> Oracle Database
```

Register the Oracle services from an ADK `services.py` file:

```python
from adk_oracledb.registry import register_oracle_services

register_oracle_services()
```

Then pass `oracle://` service URIs to ADK:

```bash
adk web examples \
  --session_service_uri 'oracle://?table_prefix=ADK_AGENT' \
  --memory_service_uri 'oracle://?memory_table_prefix=ADK_AGENT_MEMORY' \
  --artifact_service_uri 'oracle://?artifact_table_prefix=ADK_AGENT_ART'
```

Credentials can come from environment variables, so the URI can stay free of
passwords and API keys.

## Installation

For local development:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[memory]"
```

The memory extra installs `oracleagentmemory`, which is used by
`OracleMemoryService`.

## Configuration

Create a repo-root `.env` from `.env.example`:

```bash
cp .env.example .env
```

Core Oracle settings:

```bash
ORACLE_AI_DB_USER=ADK_USER
ORACLE_AI_DB_PASSWORD=...
ORACLE_AI_DB_DSN=localhost:1521/FREEPDB1
```

Agent model settings:

```bash
GENAI_MODEL=...
GENAI_ENDPOINT=...
GENAI_API_KEY=...
```

Embedding settings for memory:

```bash
EMBEDDING_MODEL=...
EMBEDDING_ENDPOINT=...
EMBEDDING_API_KEY=...
```

Optional embedding request parameters are available for OpenAI-compatible
providers that require them:

```bash
EMBEDDING_ENCODING_FORMAT=float
EMBEDDING_INPUT_TYPE=
EMBEDDING_QUERY_INPUT_TYPE=query
EMBEDDING_DOCUMENT_INPUT_TYPE=passage
```

For symmetric embedding providers, leave the input-type fields blank. For
asymmetric providers, use the query/document split so search queries and stored
memory records are embedded with the provider's expected modes.

Optional table prefix defaults:

```bash
ORACLE_SESSION_TABLE_PREFIX=ADK
ORACLE_MEMORY_TABLE_PREFIX=ADK_MEMORY
ORACLE_ARTIFACT_TABLE_PREFIX=ADK_ART
```

Shell-exported variables take precedence over values loaded from `.env`.

## Service URI forms

Env-backed URI:

```text
oracle://?table_prefix=ADK_AGENT
```

Explicit database URI:

```text
oracle://ADK_USER:<url-encoded-password>@localhost:1521/FREEPDB1?table_prefix=ADK_AGENT
```

Service-specific table prefix parameters:

```text
table_prefix=ADK_AGENT
memory_table_prefix=ADK_AGENT_MEMORY
artifact_table_prefix=ADK_AGENT_ART
```

The memory service also accepts provider settings in the URI, including
`embedder_model`, `embedder_api_base`, `embedder_encoding_format`,
`embedder_input_type`, `embedder_query_input_type`, and
`embedder_document_input_type`.

## Examples

### Oracle runtime services agent

`examples/oracle_runtime_agent` shows the complete ADK runtime-service path:
ADK loads the agent, loads `services.py`, registers `oracle://`, and creates
Oracle-backed session, memory, and artifact services through ServiceRegistry.

Run its validation flow:

```bash
.venv/bin/python examples/oracle_runtime_agent/run_smoke.py
```

Run it interactively:

```bash
adk run examples/oracle_runtime_agent \
  --session_service_uri 'oracle://?table_prefix=ADK_RUNTIME_AGENT' \
  --memory_service_uri 'oracle://?memory_table_prefix=ADK_RUNTIME_AGENT_MEMORY' \
  --artifact_service_uri 'oracle://?artifact_table_prefix=ADK_RUNTIME_AGENT_ART'
```

### Oracle travel agent

`examples/oracle_travel_agent` is a tool-enabled ADK travel planner. It uses
Oracle-backed memory to remember and recall preferences, then saves generated
itineraries and PDFs as Oracle-backed ADK artifacts.

Run its validation flow:

```bash
.venv/bin/python examples/oracle_travel_agent/run_smoke.py
```

Run it through ADK:

```bash
adk run examples/oracle_travel_agent \
  --session_service_uri 'oracle://?table_prefix=ADK_TRAVEL_AGENT' \
  --memory_service_uri 'oracle://?memory_table_prefix=ADK_TRAVEL_AGENT_MEMORY' \
  --artifact_service_uri 'oracle://?artifact_table_prefix=ADK_TRAVEL_AGENT_ART'
```

Useful prompts:

```text
Remember that I prefer 8-day mid-budget trekking and cultural trips.
Plan an 8-day mid-budget trip to Nepal using my preferences.
Save that itinerary as user:nepal_itinerary.
Generate and save that itinerary as PDF named user:nepal_itinerary.pdf.
List my saved artifacts.
Load user:nepal_itinerary.pdf.
Export user:nepal_itinerary.pdf to nepal_itinerary.pdf.
```

Use the `user:` filename prefix when an artifact should be available across
sessions for the same app and user.

## Artifact scope

ADK artifact names control visibility:

```text
filename.txt       session-scoped artifact
user:filename.txt  user-scoped artifact
```

Use user-scoped artifacts for durable files such as saved itineraries, reports,
and generated PDFs that should be available across sessions. The services
preserve ADK's filename-based scope semantics: plain filenames stay session
scoped, and `user:` filenames are user scoped.

## Validation scripts

The repository includes focused validation scripts for each service and the
registry path:

```bash
.venv/bin/python tests/smoke/session_smoke.py
.venv/bin/python tests/smoke/memory_smoke.py
.venv/bin/python tests/smoke/artifact_smoke.py
.venv/bin/python tests/smoke/registry_smoke.py
.venv/bin/python examples/oracle_runtime_agent/run_smoke.py
.venv/bin/python examples/oracle_travel_agent/run_smoke.py
```

The memory and end-to-end agent validation flows require the memory extra and an
embedding provider configuration.

## Secret handling

Keep local secrets in `.env` or shell environment variables. Do not commit
`.env`, API keys, or database passwords. If credentials are placed directly in
an `oracle://` URI, URL-encode passwords that contain special characters.
