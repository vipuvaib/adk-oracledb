from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
from typing import NoReturn
from urllib.parse import quote
from urllib.parse import urlencode
import uuid


EXAMPLE_DIR = Path(__file__).resolve().parent
EXAMPLES_DIR = EXAMPLE_DIR.parent
REPO_ROOT = EXAMPLES_DIR.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))

from google.adk.cli.service_registry import get_service_registry
from google.adk.cli.service_registry import load_services_module
from google.adk.cli.utils.agent_loader import AgentLoader

from tools import load_itinerary_artifact
from tools import recall_travel_preferences
from tools import remember_travel_preference
from tools import save_itinerary_artifact


APP_NAME = "oracle_tools_agent_smoke_app"
USER_ID = "oracle_tools_agent_smoke_user"


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
              "ORACLE_TOOLS_AGENT_SESSION_TABLE_PREFIX", "ADK_TOOLS_AGENT"
          )
      }
  )


def _memory_uri() -> str:
  query = {
      "memory_table_prefix": os.environ.get(
          "ORACLE_TOOLS_AGENT_MEMORY_TABLE_PREFIX",
          "ADK_TOOLS_AGENT_MEMORY",
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
              "ORACLE_TOOLS_AGENT_ARTIFACT_TABLE_PREFIX",
              "ADK_TOOLS_AGENT_ART",
          )
      }
  )


def _memory_result_text(result: dict[str, object]) -> str:
  memories = result.get("memories", [])
  if not isinstance(memories, list):
    return ""
  snippets = []
  for memory in memories:
    if isinstance(memory, dict):
      snippets.append(str(memory.get("text", "")))
      snippets.append(str(memory.get("metadata", "")))
  return "\n".join(snippets).lower()


@dataclass
class SmokeToolContext:
  app_name: str
  user_id: str
  session_id: str
  memory_service: object
  artifact_service: object

  async def add_memory(self, *, memories, custom_metadata=None) -> None:
    await self.memory_service.add_memory(
        app_name=self.app_name,
        user_id=self.user_id,
        memories=memories,
        custom_metadata=custom_metadata,
    )

  async def search_memory(self, query: str):
    return await self.memory_service.search_memory(
        app_name=self.app_name,
        user_id=self.user_id,
        query=query,
    )

  async def save_artifact(
      self,
      filename: str,
      artifact,
      custom_metadata: dict[str, object] | None = None,
  ) -> int:
    return await self.artifact_service.save_artifact(
        app_name=self.app_name,
        user_id=self.user_id,
        session_id=self.session_id,
        filename=filename,
        artifact=artifact,
        custom_metadata=custom_metadata,
    )

  async def load_artifact(self, filename: str, version: int | None = None):
    return await self.artifact_service.load_artifact(
        app_name=self.app_name,
        user_id=self.user_id,
        session_id=self.session_id,
        filename=filename,
        version=version,
    )


def _load_agent_and_services() -> None:
  load_services_module(str(EXAMPLE_DIR))
  agent_loader = AgentLoader(str(EXAMPLES_DIR))
  root_agent = agent_loader.load_agent("full_agent_oracle_tools")
  if getattr(root_agent, "name", None) != "oracle_tools_agent":
    _fail("ADK AgentLoader did not load the oracle_tools_agent root_agent")
  tools = getattr(root_agent, "tools", []) or []
  if len(tools) != 4:
    _fail(f"Expected 4 tools on oracle_tools_agent, found {len(tools)}")
  print("oracle tools agent services.py registration loaded")
  print(f"loaded ADK root agent: {root_agent.name}")


async def _make_context(smoke_id: str) -> tuple[object, SmokeToolContext]:
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

  session = await session_service.create_session(
      app_name=APP_NAME,
      user_id=USER_ID,
      state={
          "source": "oracle-tools-agent-smoke",
          "smoke_id": smoke_id,
      },
  )
  context = SmokeToolContext(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session.id,
      memory_service=memory_service,
      artifact_service=artifact_service,
  )
  return session_service, context


async def _memory_tool_smoke(tool_context: SmokeToolContext, smoke_id: str) -> None:
  preference = (
      "prefers 5-day mid-budget nature and culture trips "
      f"with smoke id {smoke_id}"
  )
  remember_result = await remember_travel_preference(
      preference=preference,
      tool_context=tool_context,
  )
  if remember_result["status"] != "stored":
    _fail(f"remember_travel_preference failed: {remember_result}")

  recall_result = await recall_travel_preferences(
      query="travel preferences budget duration nature culture",
      tool_context=tool_context,
  )
  print(f"oracle tools memory result count: {recall_result['count']}")
  if recall_result["count"] < 1:
    _fail("recall_travel_preferences returned no memories")
  haystack = _memory_result_text(recall_result)
  if smoke_id.lower() not in haystack and "mid-budget nature" not in haystack:
    _fail("recall_travel_preferences did not return the stored preference")
  print("oracle tools memory tool smoke passed")


async def _artifact_tool_smoke(
    tool_context: SmokeToolContext, smoke_id: str
) -> None:
  filename = f"oracle-tools-itinerary-{smoke_id}"
  itinerary = (
      "Day 1: Arrive and walk the old quarter.\n"
      "Day 2: Nature trail and local food.\n"
      f"Smoke id: {smoke_id}"
  )

  save_result = await save_itinerary_artifact(
      filename=filename,
      itinerary=itinerary,
      tool_context=tool_context,
  )
  if save_result["status"] != "saved":
    _fail(f"save_itinerary_artifact failed: {save_result}")
  saved_filename = str(save_result["filename"])
  if not saved_filename.endswith(".txt"):
    _fail(f"save_itinerary_artifact did not normalize filename: {save_result}")

  load_result = await load_itinerary_artifact(
      filename=filename,
      tool_context=tool_context,
  )
  if load_result["status"] != "loaded":
    _fail(f"load_itinerary_artifact failed: {load_result}")
  if load_result["text"] != itinerary:
    _fail("load_itinerary_artifact did not return the saved itinerary")
  print("oracle tools artifact tool smoke passed")


async def main() -> None:
  _load_agent_and_services()
  smoke_id = f"adk-oracledb-tools-agent-smoke-{uuid.uuid4().hex}"
  session_service, tool_context = await _make_context(smoke_id)
  try:
    await _memory_tool_smoke(tool_context, smoke_id)
    await _artifact_tool_smoke(tool_context, smoke_id)
  finally:
    await session_service.delete_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=tool_context.session_id,
    )
  print("oracle tools agent smoke completed successfully")


if __name__ == "__main__":
  asyncio.run(main())
