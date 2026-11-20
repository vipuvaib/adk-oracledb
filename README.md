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

OracleArtifactService stores artifact payload content in Oracle BLOB columns
and keeps artifact JSON metadata separate from the payload. Practical artifact
size depends on the Oracle Database edition, storage configuration, and
application limits. `file_data` artifact parts are preserved as URI references;
the artifact service does not fetch external file URIs or guarantee external
URI durability.

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

Auto-created session and artifact tables use Oracle native JSON columns. Use an
Oracle Database release that supports the native JSON data type; Oracle Database
Free is recommended for local development.

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

`pool_min` and `pool_max` apply to `OracleMemoryService`.
`OracleSessionService` and `OracleArtifactService` currently use
per-operation Oracle connections. They prefer python-oracledb's async
connection APIs. With a synchronous-only driver, each complete database
operation runs in a worker thread so cursor and connection calls do not block
the ADK event loop.

`OracleSessionService` follows ADK state scoping: ordinary state keys are
session scoped, `user:` keys are shared across sessions for the same app/user,
`app:` keys are shared across users and sessions for the same app, and `temp:`
keys are not persisted.

## Examples

### OCI test demo quick start

From the repository root, launch the browser UI with:

```bash
.venv/bin/python examples/run_oci_demo.py
```

Open `http://127.0.0.1:8000` on the machine running the command and select
`oracle_travel_agent` for memory, itinerary, text, and PDF tools, or
`oracle_runtime_agent` for the basic runtime-services example.

The launcher reads a private OCI environment file. Its default location is
`~/.config/agno-oracle-demo/google-adk-python-test.env`. It uses OCI IAM signing
for the configured LLM and embedder, and passes credential-free `oracle://`
URIs for sessions, memory, and artifacts. No credentials are copied into the repo.

For a different private snapshot or isolated demo tables:

```bash
.venv/bin/python examples/run_oci_demo.py \
  --env-file /path/to/private.env \
  --table-prefix ADK_OCI_DEMO
```

The env file must be user-owned with permissions `600`. This is a development
demo. The server defaults to loopback; for a remote VM, forward the port from
your local machine:

```bash
ssh -N -L 18080:127.0.0.1:8000 your-user@your-vm-host
```

Replace `your-user` and `your-vm-host` with your SSH username and host.
Then open `http://127.0.0.1:18080` locally.

For the CLI:

```bash
.venv/bin/python examples/run_oci_demo.py run --agent oracle_travel_agent
```

The launcher requires the existing virtual environment, including the memory
and examples extras:

```bash
.venv/bin/python -m pip install -e ".[memory,examples]"
```

To check a running demo from a second terminal:

```bash
ADK_DEMO_URL=http://127.0.0.1:8000 .venv/bin/python -B -m pytest -q \
  tests/unit/test_demo_launcher.py \
  tests/unit/test_oci_model_configuration.py tests/functional/test_demo_web.py
```

The HTTP tests create isolated test users and sessions, verify streamed chat
and PDF/text artifact retrieval, and remove the records they create. The
existing smoke scripts additionally check live memory embeddings and search.

Use the same table prefix across restarts to reuse the same saved demo data.
For a first browser walkthrough, select `oracle_travel_agent` and try:

1. `Remember that I prefer quiet garden walks and vegetarian food.`
2. Start a new chat, then ask: `What are my saved travel preferences?`
3. `Generate a PDF named user:my_trip.pdf titled My Trip with this itinerary:
   Morning: garden walk. Afternoon: vegetarian lunch.`
4. Start another chat, then ask: `Load user:my_trip.txt.`

A `user:` artifact filename makes the file available across chats for that
same app and user. A filename without that prefix belongs to one chat.


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

Text and `inline_data` payloads are stored in Oracle BLOB-backed artifact
storage. `file_data` parts are stored as preserved URI references; Oracle does
not fetch or copy the referenced external file.

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
