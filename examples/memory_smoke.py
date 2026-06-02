from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
from typing import NoReturn
import uuid

from google.genai import types


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))

from adk_oracledb.memory import OracleMemoryService
from adk_oracledb.memory import OracleMemoryServiceConfig
from google.adk.memory.memory_entry import MemoryEntry


APP_NAME = "memory_smoke_app"
USER_ID = "memory_smoke_user"
MEMORY_TEXT_PREFIX = "User likes Goa trips and beach resorts."


def _fail(message: str) -> NoReturn:
  raise SystemExit(message)


def _required_env(name: str) -> str:
  value = os.environ.get(name)
  if not value:
    _fail(f"Missing required environment variable: {name}")
  return value


def _optional_env(name: str) -> str | None:
  value = os.environ.get(name)
  return value or None


def _config_from_env() -> OracleMemoryServiceConfig:
  return OracleMemoryServiceConfig(
      user=_required_env("ORACLE_USER"),
      password=_required_env("ORACLE_PASSWORD"),
      dsn=_required_env("ORACLE_DSN"),
      table_name_prefix=os.environ.get(
          "ORACLE_MEMORY_TABLE_PREFIX", "ADK_MEMORY_SMOKE"
      ),
      schema_policy="create_if_necessary",
      embedder_model=_required_env("ORACLE_MEMORY_EMBEDDER_MODEL"),
      embedder_api_base=_optional_env("ORACLE_MEMORY_EMBEDDER_API_BASE"),
      embedder_api_key=_optional_env("ORACLE_MEMORY_EMBEDDER_API_KEY"),
      llm_model=_optional_env("ORACLE_MEMORY_LLM_MODEL"),
      llm_api_base=_optional_env("ORACLE_MEMORY_LLM_API_BASE"),
      llm_api_key=_optional_env("ORACLE_MEMORY_LLM_API_KEY"),
      extract_memories=False,
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


async def main() -> None:
  service = OracleMemoryService(_config_from_env())
  smoke_id = f"adk-oracledb-memory-smoke-{uuid.uuid4().hex}"
  memory_text = f"{MEMORY_TEXT_PREFIX} Smoke id: {smoke_id}"

  memory = MemoryEntry(
      id=smoke_id,
      content=types.Content(
          role="user",
          parts=[types.Part.from_text(text=memory_text)],
      ),
      custom_metadata={
          "smoke_id": smoke_id,
          "source": "adk-oracledb-memory-smoke",
      },
  )

  # oracleagentmemory may call the configured embedding provider here.
  await service.add_memory(
      app_name=APP_NAME,
      user_id=USER_ID,
      memories=[memory],
  )
  print(f"added memory id: {smoke_id}")

  # oracleagentmemory may call the configured embedding provider here too.
  response = await service.search_memory(
      app_name=APP_NAME,
      user_id=USER_ID,
      query="Where does the user like to travel?",
  )

  print(f"returned memory count: {len(response.memories)}")
  for index, returned in enumerate(response.memories, start=1):
    print(f"memory {index} id: {returned.id}")
    print(f"memory {index} text: {_memory_text(returned)}")
    print(f"memory {index} metadata: {returned.custom_metadata}")

  if not response.memories:
    _fail("search_memory returned no memories after add_memory")

  if not any(_looks_like_inserted_memory(item, smoke_id) for item in response.memories):
    _fail("search_memory did not return evidence of the inserted memory")

  print("memory smoke completed successfully")


if __name__ == "__main__":
  asyncio.run(main())
