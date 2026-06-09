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
EXAMPLES_DIR = REPO_ROOT / "examples"
if str(EXAMPLES_DIR) not in sys.path:
  sys.path.insert(0, str(EXAMPLES_DIR))

from oracle_env import first_env
from oracle_env import load_repo_env
from oracle_env import require_env

from adk_oracledb.memory import OracleMemoryService
from adk_oracledb.memory import OracleMemoryServiceConfig
from google.adk.memory.memory_entry import MemoryEntry


load_repo_env(__file__)

APP_NAME = "memory_smoke_app"
USER_ID = "memory_smoke_user"
MEMORY_TEXT_PREFIX = "User likes Goa trips and beach resorts."


def _fail(message: str) -> NoReturn:
  raise SystemExit(message)


def _config_from_env() -> OracleMemoryServiceConfig:
  return OracleMemoryServiceConfig(
      user=require_env("ORACLE_AI_DB_USER"),
      password=require_env("ORACLE_AI_DB_PASSWORD"),
      dsn=require_env("ORACLE_AI_DB_DSN"),
      table_name_prefix=os.environ.get(
          "ORACLE_MEMORY_TABLE_PREFIX", "ADK_MEMORY_SMOKE"
      ),
      schema_policy="create_if_necessary",
      embedder_model=require_env("EMBEDDING_MODEL"),
      embedder_api_base=first_env("EMBEDDING_ENDPOINT"),
      embedder_api_key=first_env("EMBEDDING_API_KEY"),
      embedder_encoding_format=first_env("EMBEDDING_ENCODING_FORMAT"),
      embedder_input_type=first_env("EMBEDDING_INPUT_TYPE"),
      embedder_query_input_type=first_env("EMBEDDING_QUERY_INPUT_TYPE"),
      embedder_document_input_type=first_env("EMBEDDING_DOCUMENT_INPUT_TYPE"),
      llm_model=first_env("GENAI_MODEL"),
      llm_api_base=first_env("GENAI_ENDPOINT"),
      llm_api_key=first_env("GENAI_API_KEY"),
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
