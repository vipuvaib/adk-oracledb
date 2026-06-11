from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
from typing import NoReturn
from urllib.parse import urlencode
import uuid


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

from tools import export_artifact_to_file
from tools import generate_and_save_itinerary_pdf
from tools import list_saved_artifacts
from tools import load_artifact
from tools import load_itinerary_artifact
from tools import plan_trip
from tools import recall_travel_preferences
from tools import remember_travel_preference
from tools import save_itinerary_artifact
from tools import save_text_artifact


load_repo_env(__file__)
configure_genai_provider_env()

APP_NAME = "oracle_travel_agent_smoke_app"
USER_ID = "oracle_travel_agent_smoke_user"


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
              "ORACLE_SESSION_TABLE_PREFIX", "ADK_TRAVEL_AGENT"
          )
      }
  )


def _memory_uri() -> str:
  require_env("EMBEDDING_MODEL")
  query = {
      "memory_table_prefix": os.environ.get(
          "ORACLE_MEMORY_TABLE_PREFIX",
          "ADK_TRAVEL_AGENT_MEMORY",
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
              "ADK_TRAVEL_AGENT_ART",
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


def _preview(value: object, *, limit: int = 180) -> str:
  text = "" if value is None else str(value)
  text = text.replace("\n", "\\n")
  if len(text) > limit:
    return f"{text[:limit]}..."
  return text


def _result_keys(result: object) -> str:
  if not isinstance(result, dict):
    return f"<{type(result).__name__}>"
  return ", ".join(sorted(str(key) for key in result.keys()))


def _artifact_text_failure(
    *,
    message: str,
    original_filename: str,
    saved_filename: str,
    load_result: object,
    expected_text: str,
) -> str:
  status = load_result.get("status") if isinstance(load_result, dict) else None
  loaded_text = load_result.get("text") if isinstance(load_result, dict) else None
  return (
      f"{message}\n"
      f"original filename: {original_filename}\n"
      f"saved filename: {saved_filename}\n"
      f"load_result status: {status}\n"
      f"load_result keys: {_result_keys(load_result)}\n"
      f"expected text length: {len(expected_text)}\n"
      f"loaded text length: {len(loaded_text) if loaded_text is not None else 'None'}\n"
      f"expected text preview: {_preview(expected_text)}\n"
      f"loaded text preview: {_preview(loaded_text)}"
  )


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

  async def list_artifacts(self) -> list[str]:
    return await self.artifact_service.list_artifact_keys(
        app_name=self.app_name,
        user_id=self.user_id,
        session_id=self.session_id,
    )


def _load_agent_and_services() -> None:
  load_services_module(str(EXAMPLE_DIR))
  agent_loader = AgentLoader(str(EXAMPLES_DIR))
  root_agent = agent_loader.load_agent("oracle_travel_agent")
  if getattr(root_agent, "name", None) != "oracle_travel_agent":
    _fail("ADK AgentLoader did not load the oracle_travel_agent root_agent")
  tools = getattr(root_agent, "tools", []) or []
  if len(tools) < 10:
    _fail(f"Expected at least 10 tools on oracle_travel_agent, found {len(tools)}")
  print("oracle travel agent services.py registration loaded")
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
          "source": "oracle-travel-agent-validation",
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
  print(f"oracle travel agent memory result count: {recall_result['count']}")
  if recall_result["count"] < 1:
    _fail("recall_travel_preferences returned no memories")
  haystack = _memory_result_text(recall_result)
  if smoke_id.lower() not in haystack and "mid-budget nature" not in haystack:
    _fail("recall_travel_preferences did not return the stored preference")
  print("oracle travel agent memory tool validation passed")


async def _planning_smoke(
    tool_context: SmokeToolContext, smoke_id: str
) -> str:
  result = await plan_trip(
      destination="Nepal",
      days=8,
      budget="mid-budget",
      interests="trekking and cultural experiences",
      tool_context=tool_context,
  )
  planning_brief = str(result["planning_brief"])
  lower_brief = planning_brief.lower()
  if "nepal" not in lower_brief:
    _fail("plan_trip planning brief did not mention Nepal")
  if "8-day" not in lower_brief:
    _fail("plan_trip planning brief did not include the requested duration")
  if "trekking" not in lower_brief:
    _fail("plan_trip planning brief did not include trekking")
  if "cultural" not in lower_brief and "culture" not in lower_brief:
    _fail("plan_trip planning brief did not include cultural interests")
  if int(result["used_memory_count"]) < 1 and smoke_id.lower() not in lower_brief:
    _fail("plan_trip did not use the stored travel preference")
  itinerary = (
      "8-day mid-budget Nepal itinerary using stored preferences\n\n"
      f"{planning_brief}\n\n"
      "Detailed itinerary:\n"
      "Day 1: Morning arrival in Kathmandu; afternoon Thamel orientation; "
      "evening Nepali dinner.\n"
      "Day 2: Morning Swayambhunath; afternoon Patan Durbar Square; evening "
      "Newari food walk.\n"
      "Day 3: Morning drive toward Pokhara; afternoon lakeside walk; evening "
      "trek briefing.\n"
      "Day 4: Morning foothill trek; afternoon village homestay; evening local "
      "meal.\n"
      "Day 5: Morning sunrise viewpoint; afternoon return to Pokhara; evening "
      "rest by Phewa Lake.\n"
      "Day 6: Morning peace pagoda or cave visit; afternoon free buffer; "
      "evening casual lakeside dinner.\n"
      "Day 7: Morning return to Kathmandu; afternoon Boudhanath; evening "
      "packing and tea.\n"
      "Day 8: Morning low-effort market visit; afternoon departure buffer; "
      "evening flight or final dinner.\n"
  )
  print("oracle travel agent planning validation passed")
  return itinerary


async def _text_artifact_smoke(
    tool_context: SmokeToolContext, smoke_id: str, itinerary: str
) -> str:
  filename = f"user:oracle-travel-text-itinerary-{smoke_id}"
  save_result = await save_text_artifact(
      filename=filename,
      text=itinerary,
      tool_context=tool_context,
  )
  if save_result["status"] != "saved":
    _fail(f"save_text_artifact failed: {save_result}")
  saved_filename = str(save_result["filename"])
  if not saved_filename.endswith(".txt"):
    _fail(f"save_text_artifact did not normalize filename: {save_result}")
  if save_result.get("scope") != "user":
    _fail(f"save_text_artifact did not report user scope: {save_result}")

  load_result = await load_artifact(
      filename=saved_filename,
      tool_context=tool_context,
  )
  if load_result["status"] != "loaded":
    _fail(
        _artifact_text_failure(
            message="load_artifact failed for text artifact",
            original_filename=filename,
            saved_filename=saved_filename,
            load_result=load_result,
            expected_text=itinerary,
        )
    )
  if load_result["kind"] != "text":
    _fail(
        _artifact_text_failure(
            message="load_artifact returned wrong kind for text artifact",
            original_filename=filename,
            saved_filename=saved_filename,
            load_result=load_result,
            expected_text=itinerary,
        )
    )
  if load_result["text"] != itinerary:
    _fail(
        _artifact_text_failure(
            message="load_artifact did not return the saved text itinerary",
            original_filename=filename,
            saved_filename=saved_filename,
            load_result=load_result,
            expected_text=itinerary,
        )
    )
  if load_result.get("filename") != saved_filename:
    _fail(f"load_artifact did not report the saved filename: {load_result}")
  if load_result.get("scope") != "user":
    _fail(f"load_artifact did not report user scope: {load_result}")

  itinerary_filename = f"user:oracle-travel-itinerary-{smoke_id}"
  itinerary_result = await save_itinerary_artifact(
      filename=itinerary_filename,
      itinerary=itinerary,
      tool_context=tool_context,
  )
  resolved_text_filename = str(itinerary_result.get("resolved_filename", ""))
  if resolved_text_filename != f"{itinerary_filename}.txt":
    _fail(f"save_itinerary_artifact did not normalize expected filename: {itinerary_result}")
  if itinerary_result.get("scope") != "user":
    _fail(f"save_itinerary_artifact did not report user scope: {itinerary_result}")

  loaded_itinerary = await load_itinerary_artifact(
      filename=resolved_text_filename,
      tool_context=tool_context,
  )
  if loaded_itinerary["text"] != itinerary:
    _fail("load_itinerary_artifact did not return the saved itinerary")
  if loaded_itinerary.get("resolved_filename") != resolved_text_filename:
    _fail(f"load_itinerary_artifact did not report expected file: {loaded_itinerary}")
  if loaded_itinerary.get("scope") != "user":
    _fail(f"load_itinerary_artifact did not report user scope: {loaded_itinerary}")
  print("oracle travel agent text artifact validation passed")
  return resolved_text_filename


async def _pdf_artifact_smoke(
    tool_context: SmokeToolContext, smoke_id: str, itinerary: str
) -> str:
  pdf_filename = f"user:oracle-travel-itinerary-{smoke_id}.pdf"
  save_result = await generate_and_save_itinerary_pdf(
      filename=pdf_filename,
      title="Nepal Itinerary",
      itinerary=itinerary,
      tool_context=tool_context,
  )
  if save_result["status"] != "saved":
    _fail(f"generate_and_save_itinerary_pdf failed: {save_result}")
  saved_filename = str(save_result["filename"])
  if saved_filename != pdf_filename:
    _fail(f"generate_and_save_itinerary_pdf saved an unexpected filename: {save_result}")
  if save_result.get("scope") != "user":
    _fail(f"PDF save did not report user scope: {save_result}")

  companion_filename = str(save_result["companion_text_filename"])
  if companion_filename != f"user:oracle-travel-itinerary-{smoke_id}.txt":
    _fail(f"PDF companion text filename was not returned as expected: {save_result}")

  load_result = await load_artifact(
      filename=saved_filename,
      tool_context=tool_context,
  )
  if load_result["status"] != "loaded":
    _fail(f"load_artifact failed for PDF: {load_result}")
  if load_result["kind"] != "inline_data":
    _fail(f"PDF artifact loaded with wrong kind: {load_result}")
  if load_result.get("resolved_filename") != saved_filename:
    _fail(f"PDF load did not report the saved artifact name: {load_result}")
  if load_result.get("scope") != "user":
    _fail(f"PDF load did not report user scope: {load_result}")
  if load_result["mime_type"] != "application/pdf":
    _fail(f"PDF artifact loaded with wrong MIME type: {load_result}")
  if load_result.get("companion_text_filename") != companion_filename:
    _fail("PDF load did not include the companion text filename")
  if load_result.get("companion_text") != itinerary:
    _fail("PDF load did not include the companion text")
  print("oracle travel agent PDF artifact validation passed")
  return saved_filename


async def _list_artifacts_smoke(
    tool_context: SmokeToolContext, expected_names: list[str]
) -> None:
  result = await list_saved_artifacts(tool_context=tool_context)
  if result["status"] != "listed":
    _fail(f"list_saved_artifacts failed: {result}")
  artifact_names = result.get("artifact_names")
  if not isinstance(artifact_names, list):
    _fail(f"list_saved_artifacts did not return a list: {result}")
  for expected in expected_names:
    if expected not in artifact_names:
      _fail(f"list_saved_artifacts did not include {expected}: {result}")
  print("oracle travel agent artifact list validation passed")


async def _pdf_export_smoke(
    tool_context: SmokeToolContext, smoke_id: str, saved_filename: str
) -> None:
  export_result = await export_artifact_to_file(
      filename=saved_filename,
      output_filename=f"oracle-travel-itinerary-{smoke_id}.pdf",
      tool_context=tool_context,
  )
  if export_result["status"] != "exported":
    _fail(f"export_artifact_to_file failed for PDF: {export_result}")
  if export_result.get("resolved_filename") != saved_filename:
    _fail(f"export_artifact_to_file did not report source filename: {export_result}")
  if export_result.get("scope") != "user":
    _fail(f"export_artifact_to_file did not report user scope: {export_result}")
  output_path = Path(str(export_result["output_path"]))
  if not output_path.exists():
    _fail(f"PDF export path does not exist: {output_path}")
  if not output_path.read_bytes().startswith(b"%PDF"):
    _fail("exported PDF bytes did not start with %PDF")
  print("oracle travel agent PDF export validation passed")


async def main() -> None:
  _load_agent_and_services()
  smoke_id = f"adk-oracledb-travel-agent-smoke-{uuid.uuid4().hex}"
  session_service, tool_context = await _make_context(smoke_id)
  try:
    await _memory_tool_smoke(tool_context, smoke_id)
    itinerary = await _planning_smoke(tool_context, smoke_id)
    text_filename = await _text_artifact_smoke(tool_context, smoke_id, itinerary)
    saved_pdf_filename = await _pdf_artifact_smoke(
        tool_context, smoke_id, itinerary
    )
    await _list_artifacts_smoke(
        tool_context,
        [text_filename, saved_pdf_filename],
    )
    await _pdf_export_smoke(
        tool_context,
        smoke_id,
        saved_pdf_filename,
    )
  finally:
    await session_service.delete_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=tool_context.session_id,
    )
  print("oracle travel agent validation completed successfully")


if __name__ == "__main__":
  asyncio.run(main())
