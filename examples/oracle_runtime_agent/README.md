# Oracle Runtime Services Agent

## OCI test demo quick start

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
