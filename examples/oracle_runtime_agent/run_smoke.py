from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
import sys
from typing import NoReturn
from urllib.parse import urlencode
import uuid

from google.genai import types


EXAMPLE_DIR = Path(__file__).resolve().parent
EXAMPLES_DIR = EXAMPLE_DIR.parent
REPO_ROOT = EXAMPLES_DIR.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))
if str(EXAMPLES_DIR) not in sys.path:
  sys.path.insert(0, str(EXAMPLES_DIR))

from oracle_env import configure_genai_provider_env
from oracle_env import first_env
from oracle_env import load_repo_env
from oracle_env import require_env

from google.adk.cli.service_registry import get_service_registry
from google.adk.cli.service_registry import load_services_module
from google.adk.cli.utils.agent_loader import AgentLoader
from google.adk.memory.memory_entry import MemoryEntry


load_repo_env(__file__)
configure_genai_provider_env()

APP_NAME = "oracle_runtime_agent_smoke_app"
USER_ID = "oracle_runtime_agent_smoke_user"


def _fail(message: str) -> NoReturn:
  raise SystemExit(message)


def _dsn_parts(dsn: str) -> tuple[str, int, str]:
  match = re.fullmatch(r"([^:/]+):(\d+)/(.+)", dsn)
  if not match:
    _fail(
        "ORACLE_AI_DB_DSN must use host:port/service_name "
        "format for this smoke script, for example localhost:1521/FREEPDB1"
    )
  return match.group(1), int(match.group(2)), match.group(3)


def _oracle_uri(*, query: dict[str, str]) -> str:
  require_env("ORACLE_AI_DB_USER")
  require_env("ORACLE_AI_DB_PASSWORD")
  host, port, service_name = _dsn_parts(require_env("ORACLE_AI_DB_DSN"))
  return f"oracle://{host}:{port}/{service_name}?{urlencode(query)}"


def _session_uri() -> str:
  return _oracle_uri(
      query={
          "table_prefix": os.environ.get(
              "ORACLE_SESSION_TABLE_PREFIX", "ADK_RUNTIME_AGENT"
          )
      }
  )


def _memory_uri() -> str:
  require_env("EMBEDDING_MODEL")
  query = {
      "memory_table_prefix": os.environ.get(
          "ORACLE_MEMORY_TABLE_PREFIX", "ADK_RUNTIME_AGENT_MEMORY"
      ),
  }
  embedder_api_base = first_env("EMBEDDING_ENDPOINT")
  if embedder_api_base is not None:
    query["embedder_api_base"] = embedder_api_base
  embedder_encoding_format = first_env("EMBEDDING_ENCODING_FORMAT")
  if embedder_encoding_format is not None:
    query["embedder_encoding_format"] = embedder_encoding_format
  embedder_input_type = first_env("EMBEDDING_INPUT_TYPE")
  if embedder_input_type is not None:
    query["embedder_input_type"] = embedder_input_type
  embedder_query_input_type = first_env("EMBEDDING_QUERY_INPUT_TYPE")
  if embedder_query_input_type is not None:
    query["embedder_query_input_type"] = embedder_query_input_type
  embedder_document_input_type = first_env("EMBEDDING_DOCUMENT_INPUT_TYPE")
  if embedder_document_input_type is not None:
    query["embedder_document_input_type"] = embedder_document_input_type
  return _oracle_uri(query=query)


def _artifact_uri() -> str:
  return _oracle_uri(
      query={
          "artifact_table_prefix": os.environ.get(
              "ORACLE_ARTIFACT_TABLE_PREFIX",
              "ADK_RUNTIME_AGENT_ART",
          )
      }
  )


def _memory_text(memory: MemoryEntry) -> str:
  if not memory.content or not memory.content.parts:
    return ""
  return "\n".join(
      part.text for part in memory.content.parts if getattr(part, "text", None)
  )


def _metadata_text(memory: MemoryEntry) -> str:
  metadata = memory.custom_metadata or {}
  return " ".join(f"{key}={value}" for key, value in metadata.items())


def _looks_like_inserted_memory(memory: MemoryEntry, smoke_id: str) -> bool:
  text = _memory_text(memory).lower()
  metadata = _metadata_text(memory).lower()
  smoke_id = smoke_id.lower()
  return smoke_id in text or smoke_id in metadata


def _load_agent_and_services() -> None:
  load_services_module(str(EXAMPLE_DIR))
  agent_loader = AgentLoader(str(EXAMPLES_DIR))
  root_agent = agent_loader.load_agent("oracle_runtime_agent")
  if getattr(root_agent, "name", None) != "oracle_runtime_agent":
    _fail("ADK AgentLoader did not load the oracle_runtime_agent root_agent")
  print("oracle runtime agent services.py registration loaded")
  print(f"loaded ADK root agent: {root_agent.name}")


async def _session_smoke(session_service: object, smoke_id: str) -> None:
  state = {
      "source": "oracle-runtime-agent-validation",
      "smoke_id": smoke_id,
  }
  created = await session_service.create_session(
      app_name=APP_NAME,
      user_id=USER_ID,
      state=state,
  )
  print(f"created oracle runtime agent session id: {created.id}")

  loaded = await session_service.get_session(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=created.id,
  )
  if loaded is None:
    _fail("Oracle session get_session returned None after create_session")
  if loaded.state.get("smoke_id") != smoke_id:
    _fail("Oracle session state did not round-trip")

  await session_service.delete_session(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=created.id,
  )
  deleted = await session_service.get_session(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=created.id,
  )
  if deleted is not None:
    _fail("Oracle session get_session returned a session after delete")
  print("oracle runtime agent session validation passed")


async def _memory_smoke(memory_service: object, smoke_id: str) -> None:
  memory_text = (
      "User likes Goa trips and beach resorts. "
      f"Oracle runtime agent validation id: {smoke_id}"
  )
  memory = MemoryEntry(
      id=smoke_id,
      content=types.Content(
          role="user",
          parts=[types.Part.from_text(text=memory_text)],
      ),
      custom_metadata={
          "smoke_id": smoke_id,
          "source": "adk-oracledb-runtime-agent-validation",
      },
  )

  await memory_service.add_memory(
      app_name=APP_NAME,
      user_id=USER_ID,
      memories=[memory],
  )
  print(f"added oracle runtime agent memory id: {smoke_id}")

  response = await memory_service.search_memory(
      app_name=APP_NAME,
      user_id=USER_ID,
      query="Where does the user like to travel?",
  )
  print(f"oracle runtime agent memory result count: {len(response.memories)}")
  if not response.memories:
    _fail("Oracle memory search returned no results after add_memory")
  if not any(_looks_like_inserted_memory(item, smoke_id) for item in response.memories):
    _fail("Oracle memory search did not return the inserted memory")
  print("oracle runtime agent memory validation passed")


async def _artifact_smoke(artifact_service: object, smoke_id: str) -> None:
  session_id = f"oracle-runtime-artifact-session-{smoke_id}"
  filename = f"oracle-runtime-artifact-{smoke_id}.txt"
  text_v0 = f"oracle runtime artifact version zero {smoke_id}"
  text_v1 = f"oracle runtime artifact version one {smoke_id}"

  version0 = await artifact_service.save_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=filename,
      artifact=types.Part.from_text(text=text_v0),
      custom_metadata={"source": "oracle-runtime-agent-validation", "version": 0},
  )
  version1 = await artifact_service.save_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=filename,
      artifact=types.Part.from_text(text=text_v1),
      custom_metadata={"source": "oracle-runtime-agent-validation", "version": 1},
  )
  print(f"saved oracle runtime agent artifact versions: {version0}, {version1}")
  assert [version0, version1] == [0, 1]

  loaded = await artifact_service.load_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=filename,
  )
  if loaded is None or loaded.text != text_v1:
    _fail("Oracle artifact latest load did not return version 1 content")

  versions = await artifact_service.list_versions(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=filename,
  )
  if versions != [0, 1]:
    _fail(f"Oracle artifact versions mismatch: {versions}")

  await artifact_service.delete_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=filename,
  )
  deleted = await artifact_service.load_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=filename,
  )
  if deleted is not None:
    _fail("Oracle artifact load returned data after delete")
  print("oracle runtime agent artifact validation passed")


async def main() -> None:
  _load_agent_and_services()
  registry = get_service_registry()

  session_service = registry.create_session_service(_session_uri())
  memory_service = registry.create_memory_service(_memory_uri())
  artifact_service = registry.create_artifact_service(_artifact_uri())

  if session_service is None:
    _fail("registry did not create Oracle session service")
  if memory_service is None:
    _fail("registry did not create Oracle memory service")
  if artifact_service is None:
    _fail("registry did not create Oracle artifact service")

  smoke_id = f"adk-oracledb-runtime-agent-validation-{uuid.uuid4().hex}"
  await _session_smoke(session_service, smoke_id)
  await _memory_smoke(memory_service, smoke_id)
  await _artifact_smoke(artifact_service, smoke_id)
  print("oracle runtime agent validation completed successfully")


if __name__ == "__main__":
  asyncio.run(main())
