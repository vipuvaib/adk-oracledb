from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
import sys
from typing import NoReturn
from urllib.parse import quote
from urllib.parse import urlencode
import uuid

from google.genai import types


EXAMPLE_DIR = Path(__file__).resolve().parent
EXAMPLES_DIR = EXAMPLE_DIR.parent
REPO_ROOT = EXAMPLES_DIR.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))

from google.adk.cli.service_registry import get_service_registry
from google.adk.cli.service_registry import load_services_module
from google.adk.cli.utils.agent_loader import AgentLoader
from google.adk.memory.memory_entry import MemoryEntry


APP_NAME = "full_agent_oracle_smoke_app"
USER_ID = "full_agent_oracle_smoke_user"


def _fail(message: str) -> NoReturn:
  raise SystemExit(message)


def _required_env(name: str) -> str:
  value = os.environ.get(name)
  if not value:
    _fail(f"Missing required environment variable: {name}")
  return value


def _optional_env(name: str) -> str | None:
  return os.environ.get(name) or None


def _dsn_parts(dsn: str) -> tuple[str, int, str]:
  match = re.fullmatch(r"([^:/]+):(\d+)/(.+)", dsn)
  if not match:
    _fail(
        "ORACLE_DSN must use host:port/service_name format for this smoke "
        "script, for example localhost:1521/FREEPDB1"
    )
  return match.group(1), int(match.group(2)), match.group(3)


def _oracle_uri(*, query: dict[str, str]) -> str:
  user = quote(_required_env("ORACLE_USER"), safe="")
  password = quote(_required_env("ORACLE_PASSWORD"), safe="")
  host, port, service_name = _dsn_parts(_required_env("ORACLE_DSN"))
  service_name = quote(service_name, safe="")
  return (
      f"oracle://{user}:{password}@{host}:{port}/{service_name}"
      f"?{urlencode(query)}"
  )


def _session_uri() -> str:
  return _oracle_uri(
      query={
          "table_prefix": os.environ.get(
              "ORACLE_FULL_AGENT_SESSION_TABLE_PREFIX", "ADK_FULL_AGENT"
          )
      }
  )


def _memory_uri() -> str:
  query = {
      "memory_table_prefix": os.environ.get(
          "ORACLE_FULL_AGENT_MEMORY_TABLE_PREFIX", "ADK_FULL_AGENT_MEMORY"
      ),
      "embedder_model": _required_env("ORACLE_MEMORY_EMBEDDER_MODEL"),
  }
  embedder_api_base = _optional_env("ORACLE_MEMORY_EMBEDDER_API_BASE")
  if embedder_api_base is not None:
    query["embedder_api_base"] = embedder_api_base
  embedder_api_key = _optional_env("ORACLE_MEMORY_EMBEDDER_API_KEY")
  if embedder_api_key is not None:
    query["embedder_api_key"] = embedder_api_key
  return _oracle_uri(query=query)


def _artifact_uri() -> str:
  return _oracle_uri(
      query={
          "artifact_table_prefix": os.environ.get(
              "ORACLE_FULL_AGENT_ARTIFACT_TABLE_PREFIX",
              "ADK_FULL_AGENT_ART",
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
  root_agent = agent_loader.load_agent("full_agent_oracle")
  if getattr(root_agent, "name", None) != "full_agent_oracle":
    _fail("ADK AgentLoader did not load the full_agent_oracle root_agent")
  print("full agent services.py registration loaded")
  print(f"loaded ADK root agent: {root_agent.name}")


async def _session_smoke(session_service: object, smoke_id: str) -> None:
  state = {
      "source": "full-agent-oracle-smoke",
      "smoke_id": smoke_id,
  }
  created = await session_service.create_session(
      app_name=APP_NAME,
      user_id=USER_ID,
      state=state,
  )
  print(f"created full-agent Oracle session id: {created.id}")

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
  print("full agent Oracle session smoke passed")


async def _memory_smoke(memory_service: object, smoke_id: str) -> None:
  memory_text = (
      "User likes Goa trips and beach resorts. "
      f"Full agent smoke id: {smoke_id}"
  )
  memory = MemoryEntry(
      id=smoke_id,
      content=types.Content(
          role="user",
          parts=[types.Part.from_text(text=memory_text)],
      ),
      custom_metadata={
          "smoke_id": smoke_id,
          "source": "adk-oracledb-full-agent-smoke",
      },
  )

  await memory_service.add_memory(
      app_name=APP_NAME,
      user_id=USER_ID,
      memories=[memory],
  )
  print(f"added full-agent Oracle memory id: {smoke_id}")

  response = await memory_service.search_memory(
      app_name=APP_NAME,
      user_id=USER_ID,
      query="Where does the user like to travel?",
  )
  print(f"full-agent Oracle memory result count: {len(response.memories)}")
  if not response.memories:
    _fail("Oracle memory search returned no results after add_memory")
  if not any(_looks_like_inserted_memory(item, smoke_id) for item in response.memories):
    _fail("Oracle memory search did not return the inserted memory")
  print("full agent Oracle memory smoke passed")


async def _artifact_smoke(artifact_service: object, smoke_id: str) -> None:
  session_id = f"full-agent-artifact-session-{smoke_id}"
  filename = f"full-agent-artifact-{smoke_id}.txt"
  text_v0 = f"full agent artifact version zero {smoke_id}"
  text_v1 = f"full agent artifact version one {smoke_id}"

  version0 = await artifact_service.save_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=filename,
      artifact=types.Part.from_text(text=text_v0),
      custom_metadata={"source": "full-agent-smoke", "version": 0},
  )
  version1 = await artifact_service.save_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=filename,
      artifact=types.Part.from_text(text=text_v1),
      custom_metadata={"source": "full-agent-smoke", "version": 1},
  )
  print(f"saved full-agent Oracle artifact versions: {version0}, {version1}")
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
  print("full agent Oracle artifact smoke passed")


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

  smoke_id = f"adk-oracledb-full-agent-smoke-{uuid.uuid4().hex}"
  await _session_smoke(session_service, smoke_id)
  await _memory_smoke(memory_service, smoke_id)
  await _artifact_smoke(artifact_service, smoke_id)
  print("full agent Oracle example smoke completed successfully")


if __name__ == "__main__":
  asyncio.run(main())
