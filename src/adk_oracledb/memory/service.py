from __future__ import annotations

import asyncio
from collections.abc import Mapping
from collections.abc import Sequence
from datetime import datetime
from datetime import timezone
import hashlib
import inspect
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


def _load_oracledb() -> Any:
  try:
    import oracledb
  except ImportError as e:
    raise ImportError(
        "OracleMemoryService requires python-oracledb. Install adk-oracledb "
        "with its base dependencies."
    ) from e
  return oracledb


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


def _oracleagentmemory_thread_id(
    *,
    app_name: str,
    user_id: str,
    session_id: str,
) -> str:
  payload = "\0".join((app_name, user_id, session_id))
  digest = hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()
  return f"ADK_THREAD_{digest}"


def _is_missing_thread_error(exc: Exception) -> bool:
  if isinstance(exc, KeyError):
    return True

  class_name = exc.__class__.__name__.lower()
  message = str(exc).lower()
  text = f"{class_name} {message}"

  infrastructure_markers = (
      "table or view does not exist",
      "ora-00942",
      "ora-01017",
      "ora-01031",
      "ora-12514",
      "ora-12154",
      "connection lost",
      "connection refused",
      "permission",
      "privilege",
      "schema",
  )
  if any(marker in text for marker in infrastructure_markers):
    return False

  thread_markers = (
      "thread not found",
      "thread_not_found",
      "thread notfound",
      "thread missing",
      "thread does not exist",
      "no such thread",
  )
  if any(marker in text for marker in thread_markers):
    return True

  if "no data found" in text:
    return True

  if "thread" in text and (
      "not found" in text
      or "not_found" in text
      or "notfound" in text
  ):
    return True

  if "thread" in class_name and (
      "notfound" in class_name or "not_found" in class_name
  ):
    return True

  return False


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
    text = getattr(result, "content", None)
  if text is None:
    text = getattr(result, "formatted_content", None)
  if text is None:
    text = ""

  custom_metadata: dict[str, Any] = {}
  record_metadata = getattr(record, "metadata", None)
  if isinstance(record_metadata, Mapping):
    custom_metadata.update(record_metadata)

  result_metadata = getattr(result, "metadata", None)
  if isinstance(result_metadata, Mapping):
    custom_metadata.update(result_metadata)

  distance = getattr(result, "distance", None)
  if distance is not None:
    custom_metadata["distance"] = distance

  for key in ("record_type", "thread_id", "user_id", "agent_id", "role"):
    value = getattr(record, key, None)
    if value is not None:
      custom_metadata[key] = value

  return MemoryEntry(
      id=getattr(result, "id", None) or getattr(record, "id", None),
      content=types.Content(
          role="user", parts=[types.Part(text=str(text))]
      ),
      timestamp=getattr(record, "timestamp", None)
      or getattr(result, "timestamp", None),
      custom_metadata=custom_metadata,
  )


class _InputTypeAwareEmbedder:
  """Routes query and document embeddings to embedders with different kwargs."""

  def __init__(self, *, query_embedder: Any, document_embedder: Any):
    self._query_embedder = query_embedder
    self._document_embedder = document_embedder

  def __getattr__(self, name: str) -> Any:
    return getattr(self._document_embedder, name)

  def embed(self, texts: list[str], *, is_query: bool = False) -> Any:
    embedder = self._query_embedder if is_query else self._document_embedder
    return embedder.embed(texts, is_query=is_query)

  def embed_async(self, texts: list[str], *, is_query: bool = False) -> Any:
    embedder = self._query_embedder if is_query else self._document_embedder
    return embedder.embed_async(texts, is_query=is_query)


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
  embedder_encoding_format: str | None = None
  embedder_input_type: str | None = None
  embedder_query_input_type: str | None = None
  embedder_document_input_type: str | None = None
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

  @field_validator("embedder_encoding_format", mode="before")
  @classmethod
  def _validate_embedder_encoding_format(cls, value: object) -> str | None:
    if value is None:
      return None
    normalized = str(value).strip().lower()
    if not normalized:
      return None
    if normalized not in {"float", "base64"}:
      raise ValueError("embedder_encoding_format must be 'float' or 'base64'")
    return normalized

  @field_validator(
      "embedder_input_type",
      "embedder_query_input_type",
      "embedder_document_input_type",
      mode="before",
  )
  @classmethod
  def _validate_embedder_input_type(cls, value: object) -> str | None:
    if value is None:
      return None
    normalized = str(value).strip().lower()
    if not normalized:
      return None
    if normalized not in {"query", "passage", "document"}:
      raise ValueError(
          "embedder_input_type must be 'query', 'passage', or 'document'"
      )
    return normalized

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
    self._client_lock = asyncio.Lock()

  def _create_pool_sync(self) -> Any:
    oracledb = _load_oracledb()
    return oracledb.create_pool(
        user=self._config.user,
        password=self._config.password,
        dsn=self._config.dsn,
        min=self._config.pool_min,
        max=self._config.pool_max,
        increment=1,
    )

  def _embedder_kwargs(
      self, *, input_type: str | None | object = ...
  ) -> dict[str, Any]:
    if not self._config.embedder_model or not self._config.embedder_model.strip():
      raise ValueError(
          "OracleMemoryServiceConfig.embedder_model is required for "
          "oracleagentmemory search."
      )

    kwargs: dict[str, Any] = {"model": self._config.embedder_model}
    if self._config.embedder_api_base is not None:
      kwargs["api_base"] = self._config.embedder_api_base
    if self._config.embedder_api_key is not None:
      kwargs["api_key"] = self._config.embedder_api_key
    if self._config.embedder_encoding_format is not None:
      kwargs["encoding_format"] = self._config.embedder_encoding_format
    if input_type is ...:
      input_type = self._config.embedder_input_type
    if input_type is not None:
      kwargs["input_type"] = input_type
    return kwargs

  def _build_embedder(self, embedder_cls: Any) -> Any:
    query_input_type = (
        self._config.embedder_query_input_type
        or self._config.embedder_input_type
    )
    document_input_type = (
        self._config.embedder_document_input_type
        or self._config.embedder_input_type
    )

    if query_input_type == document_input_type:
      return embedder_cls(**self._embedder_kwargs(input_type=query_input_type))

    query_embedder = embedder_cls(
        **self._embedder_kwargs(input_type=query_input_type)
    )
    document_embedder = embedder_cls(
        **self._embedder_kwargs(input_type=document_input_type)
    )
    return _InputTypeAwareEmbedder(
        query_embedder=query_embedder,
        document_embedder=document_embedder,
    )

  def _build_llm(self, llm_cls: Any) -> Any | None:
    if not self._config.llm_model or not self._config.llm_model.strip():
      return None

    kwargs: dict[str, Any] = {"model": self._config.llm_model}
    if self._config.llm_api_base is not None:
      kwargs["api_base"] = self._config.llm_api_base
    if self._config.llm_api_key is not None:
      kwargs["api_key"] = self._config.llm_api_key
    return llm_cls(**kwargs)

  def _create_client_sync(self) -> Any:
    OracleAgentMemory, _, _, Embedder, Llm = _load_oracleagentmemory()
    embedder = self._build_embedder(Embedder)
    llm = self._build_llm(Llm)

    if self._pool is None:
      self._pool = self._create_pool_sync()

    kwargs: dict[str, Any] = {
        "connection": self._pool,
        "embedder": embedder,
        "extract_memories": self._config.extract_memories,
        "schema_policy": self._config.schema_policy,
        "table_name_prefix": self._config.table_name_prefix,
    }
    if llm is not None:
      kwargs["llm"] = llm

    return OracleAgentMemory(**kwargs)

  async def _get_client(self) -> Any:
    if self._client is not None:
      return self._client

    async with self._client_lock:
      if self._client is None:
        self._client = await asyncio.to_thread(self._create_client_sync)
      return self._client

  def _get_or_create_thread_sync(
      self,
      client: Any,
      *,
      app_name: str,
      user_id: str,
      session_id: str | None,
      metadata: Mapping[str, object] | None = None,
  ) -> Any:
    thread_metadata = dict(metadata or {})
    scoped_thread_id = None
    if session_id is not None:
      scoped_thread_id = _oracleagentmemory_thread_id(
          app_name=app_name,
          user_id=user_id,
          session_id=session_id,
      )
      thread_metadata["oracleagentmemory_thread_id"] = scoped_thread_id

    create_kwargs: dict[str, Any] = {
        "user_id": user_id,
        "agent_id": app_name,
        "metadata": thread_metadata,
        "extract_memories": self._config.extract_memories,
    }

    if scoped_thread_id is not None:
      try:
        thread = client.get_thread(scoped_thread_id)
      except Exception as exc:
        if not _is_missing_thread_error(exc):
          raise
      else:
        if thread is not None:
          return thread

      create_kwargs["thread_id"] = scoped_thread_id

    return client.create_thread(**create_kwargs)

  @override
  async def add_session_to_memory(self, session: Session) -> None:
    app_name = session.app_name.strip()
    user_id = session.user_id.strip()
    session_id = session.id.strip()
    if not app_name:
      raise ValueError("app_name must not be empty")
    if not user_id:
      raise ValueError("user_id must not be empty")
    if not session_id:
      raise ValueError("session.id must not be empty")
    if not session.events:
      return None

    metadata: dict[str, object] = {"adk_ingest_source": "session"}
    if session.last_update_time is not None:
      metadata["adk_session_last_update_time"] = (
          _timestamp_to_string(session.last_update_time)
          if isinstance(session.last_update_time, (int, float))
          else str(session.last_update_time)
      )

    await self.add_events_to_memory(
        app_name=app_name,
        user_id=user_id,
        events=session.events,
        session_id=session_id,
        custom_metadata=metadata,
    )
    return None

  @override
  async def search_memory(
      self, *, app_name: str, user_id: str, query: str
  ) -> SearchMemoryResponse:
    app_name = app_name.strip()
    user_id = user_id.strip()
    query = query.strip()
    if not app_name:
      raise ValueError("app_name must not be empty")
    if not user_id:
      raise ValueError("user_id must not be empty")
    if not query:
      raise ValueError("query must not be empty")

    client = await self._get_client()
    search_kwargs: dict[str, Any] = {
        "user_id": user_id,
        "agent_id": app_name,
        "exact_user_match": True,
        "exact_agent_match": True,
        "max_results": self._config.search_top_k,
    }
    if self._config.record_types is not None:
      search_kwargs["record_types"] = self._config.record_types

    search_async = getattr(client, "search_async", None)
    if search_async is not None and inspect.iscoroutinefunction(search_async):
      results = await search_async(query, **search_kwargs)
    else:
      results = await asyncio.to_thread(client.search, query, **search_kwargs)

    return SearchMemoryResponse(
        memories=[_search_result_to_memory_entry(result) for result in results]
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
    app_name = app_name.strip()
    user_id = user_id.strip()
    if not app_name:
      raise ValueError("app_name must not be empty")
    if not user_id:
      raise ValueError("user_id must not be empty")

    session_id = session_id.strip() if session_id is not None else None
    if not session_id:
      session_id = None
    if not events:
      return None

    text_events = []
    for event in events:
      if getattr(event, "partial", False):
        continue
      if _content_to_text(event.content).strip():
        text_events.append(event)
    if not text_events:
      return None

    thread_metadata: dict[str, object] = dict(custom_metadata or {})
    thread_metadata.update({
        "adk_app_name": app_name,
        "adk_user_id": user_id,
    })
    if session_id is not None:
      thread_metadata["adk_session_id"] = session_id
      thread_metadata["oracleagentmemory_thread_id"] = (
          _oracleagentmemory_thread_id(
              app_name=app_name,
              user_id=user_id,
              session_id=session_id,
          )
      )

    _, _, Message, _, _ = _load_oracleagentmemory()
    messages = []
    for event in text_events:
      message = _event_to_message(
          event, Message, extra_metadata=thread_metadata
      )
      if message is not None:
        messages.append(message)
    if not messages:
      return None

    client = await self._get_client()
    thread = await asyncio.to_thread(
        self._get_or_create_thread_sync,
        client,
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
        metadata=thread_metadata,
    )

    add_messages_async = getattr(thread, "add_messages_async", None)
    if (
        add_messages_async is not None
        and inspect.iscoroutinefunction(add_messages_async)
    ):
      await add_messages_async(messages)
    else:
      await asyncio.to_thread(thread.add_messages, messages)

    return None

  @override
  async def add_memory(
      self,
      *,
      app_name: str,
      user_id: str,
      memories: Sequence[MemoryEntry],
      custom_metadata: Mapping[str, object] | None = None,
  ) -> None:
    app_name = app_name.strip()
    user_id = user_id.strip()
    if not app_name:
      raise ValueError("app_name must not be empty")
    if not user_id:
      raise ValueError("user_id must not be empty")
    if not memories:
      return None

    pending_memories: list[tuple[MemoryEntry, str]] = []
    for memory in memories:
      text = _memory_entry_to_text(memory).strip()
      if text:
        pending_memories.append((memory, text))

    if not pending_memories:
      return None

    client = await self._get_client()
    for memory, text in pending_memories:
      add_kwargs: dict[str, Any] = {
          "user_id": user_id,
          "agent_id": app_name,
      }

      memory_id = memory.id.strip() if memory.id else None
      if memory_id:
        add_kwargs["memory_id"] = memory_id

      metadata: dict[str, object] = dict(custom_metadata or {})
      if memory.custom_metadata:
        metadata.update(memory.custom_metadata)
      if memory.id:
        metadata["adk_memory_id"] = memory.id
      if memory.author:
        metadata["adk_author"] = memory.author
      if memory.timestamp:
        metadata["adk_timestamp"] = memory.timestamp
      if metadata:
        add_kwargs["metadata"] = metadata

      await asyncio.to_thread(client.add_memory, text, **add_kwargs)

    return None
