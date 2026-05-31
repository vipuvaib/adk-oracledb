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


async def _read_db_value(value: Any) -> Any:
  read = getattr(value, "read", None)
  if read is not None:
    value = await _maybe_await(read())
  if isinstance(value, (bytes, bytearray)):
    return value.decode("utf-8")
  return value


async def _json_to_dict(value: Any) -> dict[str, Any]:
  value = await _read_db_value(value)
  if value is None:
    return {}
  if isinstance(value, str):
    value = json.loads(value) if value else {}
  if not isinstance(value, dict):
    raise ValueError("Expected JSON object from Oracle session state.")
  return value


async def _event_from_json(value: Any) -> Event:
  value = await _read_db_value(value)
  if isinstance(value, str):
    return Event.model_validate_json(value)
  return Event.model_validate(value)


def _timestamp_to_float(value: Any) -> float:
  if isinstance(value, datetime):
    if value.tzinfo is None:
      value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()
  return float(value)


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
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", table_prefix):
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
    sessions_table = self._table_name("SESSIONS")
    events_table = self._table_name("EVENTS")
    connection = await create_oracle_connection(self._config)
    cursor = None
    try:
      cursor = await _call(connection.cursor)
      await _call(
          cursor.execute,
          f"""
          SELECT state_json, last_update_time
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
      session_row = await _call(cursor.fetchone)
      if session_row is None:
        return None

      session_state = await _json_to_dict(session_row[0])
      last_update_time = _timestamp_to_float(session_row[1])

      event_rows = []
      if not (config and config.num_recent_events == 0):
        where_clauses = [
            "app_name = :app_name",
            "user_id = :user_id",
            "session_id = :session_id",
        ]
        params: dict[str, Any] = {
            "app_name": app_name,
            "user_id": user_id,
            "session_id": session_id,
        }
        if config and config.after_timestamp is not None:
          where_clauses.append("event_ts >= :after_timestamp")
          params["after_timestamp"] = datetime.fromtimestamp(
              config.after_timestamp, tz=timezone.utc
          )

        where_sql = " AND ".join(where_clauses)
        if config and config.num_recent_events is not None:
          params["num_recent_events"] = config.num_recent_events
          events_query = f"""
            SELECT event_json
            FROM (
              SELECT event_json, event_ts, event_id
              FROM {events_table}
              WHERE {where_sql}
              ORDER BY event_ts DESC, event_id DESC
            )
            WHERE ROWNUM <= :num_recent_events
          """
        else:
          events_query = f"""
            SELECT event_json
            FROM {events_table}
            WHERE {where_sql}
            ORDER BY event_ts ASC, event_id ASC
          """

        await _call(cursor.execute, events_query, params)
        event_rows = await _call(cursor.fetchall)
        if config and config.num_recent_events is not None:
          event_rows = list(reversed(event_rows))

      events = [await _event_from_json(row[0]) for row in event_rows]
      return Session(
          app_name=app_name,
          user_id=user_id,
          id=session_id,
          state=session_state,
          events=events,
          last_update_time=last_update_time,
      )
    finally:
      if cursor is not None:
        await _close(cursor)
      await _close(connection)

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
