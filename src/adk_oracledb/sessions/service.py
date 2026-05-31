from __future__ import annotations

from datetime import datetime
from datetime import timezone
import inspect
import json
import re
from typing import Any

from adk_oracledb.connection import create_oracle_connection
from google.adk.errors.already_exists_error import AlreadyExistsError
from google.adk.events.event import Event
from google.adk.platform import time as platform_time
from google.adk.platform import uuid as platform_uuid
from google.adk.sessions.base_session_service import BaseSessionService
from google.adk.sessions.base_session_service import GetSessionConfig
from google.adk.sessions.base_session_service import ListSessionsResponse
from google.adk.sessions.session import Session
from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from typing_extensions import override


async def _maybe_await(value: Any) -> Any:
  if inspect.isawaitable(value):
    return await value
  return value


async def _call(method: Any, *args: Any, **kwargs: Any) -> Any:
  return await _maybe_await(method(*args, **kwargs))


async def _close(resource: Any) -> None:
  close = getattr(resource, "close", None)
  if close is not None:
    await _maybe_await(close())


class OracleSessionServiceConfig(BaseModel):
  """Configuration for Oracle-backed ADK session storage."""

  user: str
  password: str
  dsn: str
  table_prefix: str = "ADK"
  auto_create_tables: bool = True
  pool_min: int = Field(default=1, ge=1)
  pool_max: int = Field(default=4, ge=1)

  @field_validator("table_prefix")
  @classmethod
  def _validate_table_prefix(cls, value: str) -> str:
    table_prefix = value.strip().upper()
    if not table_prefix:
      raise ValueError("table_prefix must not be empty")
    if not re.fullmatch(r"[A-Z0-9_]+", table_prefix):
      raise ValueError(
          "table_prefix must contain only letters, numbers, and underscore"
      )
    return table_prefix


class OracleSessionService(BaseSessionService):
  """Minimal Oracle Database session service skeleton."""

  def __init__(self, config: OracleSessionServiceConfig):
    self._config = config

  def _table_name(self, suffix: str) -> str:
    return f"{self._config.table_prefix}_{suffix}"

  @override
  async def create_session(
      self,
      *,
      app_name: str,
      user_id: str,
      state: dict[str, Any] | None = None,
      session_id: str | None = None,
  ) -> Session:
    if session_id:
      session_id = session_id.strip()
    if not session_id:
      session_id = platform_uuid.new_uuid()

    session_state = dict(state or {})
    state_json = json.dumps(session_state, allow_nan=False)
    now_timestamp = platform_time.get_time()
    now = datetime.fromtimestamp(now_timestamp, tz=timezone.utc)
    sessions_table = self._table_name("SESSIONS")

    connection = await create_oracle_connection(self._config)
    cursor = None
    try:
      cursor = await _call(connection.cursor)
      await _call(
          cursor.execute,
          f"""
          SELECT 1
          FROM {sessions_table}
          WHERE app_name = :app_name
            AND user_id = :user_id
            AND session_id = :session_id
          """,
          {
              "app_name": app_name,
              "user_id": user_id,
              "session_id": session_id,
          },
      )
      if await _call(cursor.fetchone):
        raise AlreadyExistsError(
            f"Session with id {session_id} already exists."
        )

      await _call(
          cursor.execute,
          f"""
          INSERT INTO {sessions_table} (
            app_name,
            user_id,
            session_id,
            state_json,
            create_time,
            last_update_time
          )
          VALUES (
            :app_name,
            :user_id,
            :session_id,
            :state_json,
            :create_time,
            :last_update_time
          )
          """,
          {
              "app_name": app_name,
              "user_id": user_id,
              "session_id": session_id,
              "state_json": state_json,
              "create_time": now,
              "last_update_time": now,
          },
      )
      await _call(connection.commit)
    finally:
      if cursor is not None:
        await _close(cursor)
      await _close(connection)

    return Session(
        app_name=app_name,
        user_id=user_id,
        id=session_id,
        state=session_state,
        events=[],
        last_update_time=now_timestamp,
    )

  @override
  async def get_session(
      self,
      *,
      app_name: str,
      user_id: str,
      session_id: str,
      config: GetSessionConfig | None = None,
  ) -> Session | None:
    raise NotImplementedError

  @override
  async def list_sessions(
      self, *, app_name: str, user_id: str | None = None
  ) -> ListSessionsResponse:
    raise NotImplementedError

  @override
  async def delete_session(
      self, *, app_name: str, user_id: str, session_id: str
  ) -> None:
    raise NotImplementedError

  @override
  async def append_event(self, session: Session, event: Event) -> Event:
    raise NotImplementedError

  @override
  async def flush(self) -> None:
    pass
