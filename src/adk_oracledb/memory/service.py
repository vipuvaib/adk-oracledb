from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from datetime import datetime
from datetime import timezone
import re
from typing import Any
from typing import Literal

from google.adk.events.event import Event
from google.adk.memory.base_memory_service import BaseMemoryService
from google.adk.memory.base_memory_service import SearchMemoryResponse
from google.adk.memory.memory_entry import MemoryEntry
from google.adk.sessions.session import Session
from google.genai import types
from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator
from typing_extensions import override


SchemaPolicyLiteral = Literal[
    "require_existing",
    "create_if_empty",
    "create_if_necessary",
    "recreate",
]


def _load_oracleagentmemory() -> tuple[Any, Any, Any, Any, Any]:
  try:
    from oracleagentmemory.apis.thread import Message
    from oracleagentmemory.core import OracleAgentMemory
    from oracleagentmemory.core import SchemaPolicy
    from oracleagentmemory.core.embedders.embedder import Embedder
    from oracleagentmemory.core.llms.llm import Llm
  except ImportError as e:
    raise ImportError(
        "OracleMemoryService requires oracleagentmemory. Install it with:\n"
        'pip install "adk-oracledb[memory]" or pip install oracleagentmemory.'
    ) from e
  return OracleAgentMemory, SchemaPolicy, Message, Embedder, Llm


def _content_to_text(content: types.Content | None) -> str:
  if not content or not content.parts:
    return ""

  text_parts = []
  for part in content.parts:
    if getattr(part, "thought", False):
      continue
    text = getattr(part, "text", None)
    if text:
      text_parts.append(text)
  return "\n".join(text_parts)


def _normalize_message_role(
    role: str | None, author: str | None = None
) -> str:
  value = (role or author or "").strip().lower()
  if value == "user":
    return "user"
  if value in {"model", "assistant"}:
    return "assistant"
  if value == "tool":
    return "tool"
  if value == "system":
    return "system"
  return "assistant"


def _timestamp_to_string(timestamp: float | None) -> str | None:
  if timestamp is None:
    return None
  try:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
  except (OSError, OverflowError, ValueError):
    return str(timestamp)


def _event_to_message(
    event: Event,
    message_cls: Any,
    extra_metadata: Mapping[str, object] | None = None,
) -> Any | None:
  text = _content_to_text(event.content)
  if not text:
    return None

  metadata: dict[str, Any] = dict(extra_metadata or {})
  metadata.update({
      "adk_event_id": event.id,
      "adk_author": event.author,
      "adk_invocation_id": event.invocation_id,
  })
  role = _normalize_message_role(
      getattr(event.content, "role", None), event.author
  )

  return message_cls(
      role=role,
      content=text,
      timestamp=_timestamp_to_string(event.timestamp),
      metadata=metadata,
      id=event.id or None,
  )


def _memory_entry_to_text(memory: MemoryEntry) -> str:
  return _content_to_text(memory.content)


def _search_result_to_memory_entry(result: Any) -> MemoryEntry:
  record = getattr(result, "record", None)
  text = getattr(record, "content", None)
  if text is None:
    text = getattr(result, "content", "") or ""

  custom_metadata: dict[str, Any] = {}
  record_metadata = getattr(record, "metadata", None)
  if isinstance(record_metadata, Mapping):
    custom_metadata.update(record_metadata)

  distance = getattr(result, "distance", None)
  if distance is not None:
    custom_metadata["distance"] = distance

  record_type = getattr(record, "record_type", None)
  if record_type is not None:
    custom_metadata["record_type"] = record_type

  return MemoryEntry(
      id=getattr(record, "id", None) or getattr(result, "id", None),
      content=types.Content(
          role="user", parts=[types.Part(text=str(text))]
      ),
      timestamp=getattr(record, "timestamp", None)
      or getattr(result, "timestamp", None),
      custom_metadata=custom_metadata,
  )


class OracleMemoryServiceConfig(BaseModel):
  """Configuration for Oracle-backed ADK memory integration."""

  user: str
  password: str
  dsn: str
  pool_min: int = Field(default=1, ge=1)
  pool_max: int = Field(default=4, ge=1)
  table_name_prefix: str = "ADK_MEMORY"
  schema_policy: SchemaPolicyLiteral = "create_if_necessary"
  embedder_model: str | None = None
  embedder_api_base: str | None = None
  embedder_api_key: str | None = None
  llm_model: str | None = None
  llm_api_base: str | None = None
  llm_api_key: str | None = None
  extract_memories: bool = False
  search_top_k: int = Field(default=10, ge=1)
  record_types: list[str] | None = None

  @field_validator("table_name_prefix")
  @classmethod
  def _validate_table_name_prefix(cls, value: str) -> str:
    table_name_prefix = value.strip().upper()
    if not table_name_prefix:
      raise ValueError("table_name_prefix must not be empty")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", table_name_prefix):
      raise ValueError(
          "table_name_prefix must contain only letters, numbers, and "
          "underscore"
      )
    return table_name_prefix

  @model_validator(mode="after")
  def _validate_pool_bounds(self) -> OracleMemoryServiceConfig:
    if self.pool_max < self.pool_min:
      raise ValueError("pool_max must be greater than or equal to pool_min")
    return self


class OracleMemoryService(BaseMemoryService):
  """Skeleton ADK memory service backed by oracleagentmemory."""

  def __init__(self, config: OracleMemoryServiceConfig):
    self._config = config
    self._client = None
    self._pool = None

  @override
  async def add_session_to_memory(self, session: Session) -> None:
    raise NotImplementedError(
        "OracleMemoryService.add_session_to_memory is pending "
        "oracleagentmemory client wiring."
    )

  @override
  async def search_memory(
      self, *, app_name: str, user_id: str, query: str
  ) -> SearchMemoryResponse:
    raise NotImplementedError(
        "OracleMemoryService.search_memory is pending oracleagentmemory "
        "search wiring."
    )

  @override
  async def add_events_to_memory(
      self,
      *,
      app_name: str,
      user_id: str,
      events: Sequence[Event],
      session_id: str | None = None,
      custom_metadata: Mapping[str, object] | None = None,
  ) -> None:
    raise NotImplementedError(
        "OracleMemoryService.add_events_to_memory is pending "
        "oracleagentmemory client wiring."
    )

  @override
  async def add_memory(
      self,
      *,
      app_name: str,
      user_id: str,
      memories: Sequence[MemoryEntry],
      custom_metadata: Mapping[str, object] | None = None,
  ) -> None:
    raise NotImplementedError(
        "OracleMemoryService.add_memory is pending oracleagentmemory "
        "client wiring."
    )
