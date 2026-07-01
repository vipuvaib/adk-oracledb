from __future__ import annotations

import asyncio
from decimal import Decimal
from datetime import datetime
from datetime import timezone
import inspect
import json
from pathlib import Path
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
from google.adk.sessions.state import State
from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator
from typing_extensions import override


_ORACLE_ALREADY_EXISTS_CODE = 955
_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


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


async def _rollback(connection: Any) -> None:
  rollback = getattr(connection, "rollback", None)
  if rollback is not None:
    try:
      await _maybe_await(rollback())
    except Exception:
      pass


async def _read_db_value(value: Any) -> Any:
  read = getattr(value, "read", None)
  if read is not None:
    value = await _maybe_await(read())
  if isinstance(value, (bytes, bytearray)):
    return value.decode("utf-8")
  return value


def _normalize_json_value(value: Any) -> Any:
  if isinstance(value, dict):
    return {key: _normalize_json_value(item) for key, item in value.items()}
  if isinstance(value, list):
    return [_normalize_json_value(item) for item in value]
  if isinstance(value, Decimal):
    if value == value.to_integral_value():
      return int(value)
    return float(value)
  return value


async def _json_to_dict(value: Any) -> dict[str, Any]:
  value = await _read_db_value(value)
  if value is None:
    return {}
  if isinstance(value, str):
    value = json.loads(value) if value else {}
  value = _normalize_json_value(value)
  if not isinstance(value, dict):
    raise ValueError("Expected JSON object from Oracle session state.")
  return value


async def _json_row_to_dict(row: Any) -> tuple[bool, dict[str, Any]]:
  if row is None:
    return False, {}
  return True, await _json_to_dict(row[0])


async def _event_from_json(value: Any) -> Event:
  value = await _read_db_value(value)
  if isinstance(value, str):
    return Event.model_validate_json(value)
  return Event.model_validate(_normalize_json_value(value))


def _timestamp_to_float(value: Any) -> float:
  if isinstance(value, datetime):
    if value.tzinfo is None:
      value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()
  return float(value)


def _schema_statements(table_prefix: str) -> list[str]:
  schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
  schema_sql = schema_sql.replace("ADK_", f"{table_prefix}_")
  sql_lines = []
  for line in schema_sql.splitlines():
    if not line.strip().startswith("--"):
      sql_lines.append(line)
  return [
      statement.strip()
      for statement in "\n".join(sql_lines).split(";")
      if statement.strip()
  ]


def _is_oracle_already_exists_error(error: BaseException) -> bool:
  if f"ORA-{_ORACLE_ALREADY_EXISTS_CODE:05d}" in str(error):
    return True

  for arg in getattr(error, "args", ()):
    if getattr(arg, "code", None) == _ORACLE_ALREADY_EXISTS_CODE:
      return True
  return False


def _json_dump(value: dict[str, Any]) -> str:
  return json.dumps(value, allow_nan=False)


def _extract_state_delta(state: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
  deltas: dict[str, dict[str, Any]] = {
      "app": {},
      "user": {},
      "session": {},
  }
  for key, value in dict(state or {}).items():
    if key.startswith(State.APP_PREFIX):
      deltas["app"][key.removeprefix(State.APP_PREFIX)] = value
    elif key.startswith(State.USER_PREFIX):
      deltas["user"][key.removeprefix(State.USER_PREFIX)] = value
    elif not key.startswith(State.TEMP_PREFIX):
      deltas["session"][key] = value
  return deltas


def _merge_state(
    app_state: dict[str, Any],
    user_state: dict[str, Any],
    session_state: dict[str, Any],
) -> dict[str, Any]:
  merged = dict(session_state)
  for key, value in app_state.items():
    merged[f"{State.APP_PREFIX}{key}"] = value
  for key, value in user_state.items():
    merged[f"{State.USER_PREFIX}{key}"] = value
  return merged


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

  @model_validator(mode="after")
  def _validate_pool_bounds(self) -> OracleSessionServiceConfig:
    if self.pool_max < self.pool_min:
      raise ValueError("pool_max must be greater than or equal to pool_min")
    return self


class OracleSessionService(BaseSessionService):
  """ADK session service backed by Oracle Database."""

  def __init__(self, config: OracleSessionServiceConfig):
    self._config = config
    self._schema_initialized = False
    self._schema_init_lock = asyncio.Lock()

  def _table_name(self, suffix: str) -> str:
    return f"{self._config.table_prefix}_{suffix}"

  async def _get_app_state_from_cursor(
      self,
      cursor: Any,
      app_name: str,
      *,
      for_update: bool = False,
  ) -> tuple[bool, dict[str, Any]]:
    suffix = " FOR UPDATE" if for_update else ""
    await _call(
        cursor.execute,
        f"""
        SELECT state_json
        FROM {self._table_name("APP_STATES")}
        WHERE app_name = :app_name
        {suffix}
        """,
        {"app_name": app_name},
    )
    row = await _call(cursor.fetchone)
    return await _json_row_to_dict(row)

  async def _get_user_state_from_cursor(
      self,
      cursor: Any,
      app_name: str,
      user_id: str,
      *,
      for_update: bool = False,
  ) -> tuple[bool, dict[str, Any]]:
    suffix = " FOR UPDATE" if for_update else ""
    await _call(
        cursor.execute,
        f"""
        SELECT state_json
        FROM {self._table_name("USER_STATES")}
        WHERE app_name = :app_name
          AND user_id = :user_id
        {suffix}
        """,
        {"app_name": app_name, "user_id": user_id},
    )
    row = await _call(cursor.fetchone)
    return await _json_row_to_dict(row)

  async def _load_app_state(
      self,
      cursor: Any,
      app_name: str,
      *,
      for_update: bool = False,
  ) -> dict[str, Any]:
    _, state = await self._get_app_state_from_cursor(
        cursor, app_name, for_update=for_update
    )
    return state

  async def _load_user_state(
      self,
      cursor: Any,
      app_name: str,
      user_id: str,
      *,
      for_update: bool = False,
  ) -> dict[str, Any]:
    _, state = await self._get_user_state_from_cursor(
        cursor, app_name, user_id, for_update=for_update
    )
    return state

  async def _upsert_app_state(
      self,
      cursor: Any,
      app_name: str,
      delta: dict[str, Any],
      update_time: datetime,
  ) -> dict[str, Any]:
    exists, existing = await self._get_app_state_from_cursor(
        cursor, app_name, for_update=True
    )
    if not delta:
      return existing

    merged = {**existing, **delta}
    if exists:
      await _call(
          cursor.execute,
          f"""
          UPDATE {self._table_name("APP_STATES")}
          SET state_json = :state_json,
              update_time = :update_time
          WHERE app_name = :app_name
          """,
          {
              "state_json": _json_dump(merged),
              "update_time": update_time,
              "app_name": app_name,
          },
      )
    else:
      await _call(
          cursor.execute,
          f"""
          INSERT INTO {self._table_name("APP_STATES")} (
            app_name,
            state_json,
            update_time
          )
          VALUES (
            :app_name,
            :state_json,
            :update_time
          )
          """,
          {
              "app_name": app_name,
              "state_json": _json_dump(merged),
              "update_time": update_time,
          },
      )
    return merged

  async def _upsert_user_state(
      self,
      cursor: Any,
      app_name: str,
      user_id: str,
      delta: dict[str, Any],
      update_time: datetime,
  ) -> dict[str, Any]:
    exists, existing = await self._get_user_state_from_cursor(
        cursor, app_name, user_id, for_update=True
    )
    if not delta:
      return existing

    merged = {**existing, **delta}
    if exists:
      await _call(
          cursor.execute,
          f"""
          UPDATE {self._table_name("USER_STATES")}
          SET state_json = :state_json,
              update_time = :update_time
          WHERE app_name = :app_name
            AND user_id = :user_id
          """,
          {
              "state_json": _json_dump(merged),
              "update_time": update_time,
              "app_name": app_name,
              "user_id": user_id,
          },
      )
    else:
      await _call(
          cursor.execute,
          f"""
          INSERT INTO {self._table_name("USER_STATES")} (
            app_name,
            user_id,
            state_json,
            update_time
          )
          VALUES (
            :app_name,
            :user_id,
            :state_json,
            :update_time
          )
          """,
          {
              "app_name": app_name,
              "user_id": user_id,
              "state_json": _json_dump(merged),
              "update_time": update_time,
          },
      )
    return merged

  async def _initialize_schema(self) -> None:
    if not self._config.auto_create_tables or self._schema_initialized:
      return

    async with self._schema_init_lock:
      if self._schema_initialized:
        return

      connection = await create_oracle_connection(self._config)
      cursor = None
      try:
        cursor = await _call(connection.cursor)
        for statement in _schema_statements(self._config.table_prefix):
          try:
            await _call(cursor.execute, statement)
          except Exception as e:
            if _is_oracle_already_exists_error(e):
              continue
            raise
        await _call(connection.commit)
        self._schema_initialized = True
      except BaseException:
        await _rollback(connection)
        raise
      finally:
        if cursor is not None:
          await _close(cursor)
        await _close(connection)

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

    state_deltas = _extract_state_delta(state)
    app_state_delta = state_deltas["app"]
    user_state_delta = state_deltas["user"]
    session_state = state_deltas["session"]
    state_json = _json_dump(session_state)
    now_timestamp = platform_time.get_time()
    now = datetime.fromtimestamp(now_timestamp, tz=timezone.utc)
    sessions_table = self._table_name("SESSIONS")

    await self._initialize_schema()
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

      app_state = await self._upsert_app_state(
          cursor, app_name, app_state_delta, now
      )
      user_state = await self._upsert_user_state(
          cursor, app_name, user_id, user_state_delta, now
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
    except BaseException:
      await _rollback(connection)
      raise
    finally:
      if cursor is not None:
        await _close(cursor)
      await _close(connection)

    return Session(
        app_name=app_name,
        user_id=user_id,
        id=session_id,
        state=_merge_state(app_state, user_state, session_state),
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
    if (
        config
        and config.num_recent_events is not None
        and config.num_recent_events < 0
    ):
      raise ValueError("num_recent_events must be non-negative.")

    sessions_table = self._table_name("SESSIONS")
    events_table = self._table_name("EVENTS")
    await self._initialize_schema()
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
      app_state = await self._load_app_state(cursor, app_name)
      user_state = await self._load_user_state(
          cursor, app_name, user_id
      )

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
          state=_merge_state(app_state, user_state, session_state),
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
    sessions_table = self._table_name("SESSIONS")
    where_clauses = ["app_name = :app_name"]
    params: dict[str, Any] = {"app_name": app_name}
    if user_id is not None:
      where_clauses.append("user_id = :user_id")
      params["user_id"] = user_id

    await self._initialize_schema()
    connection = await create_oracle_connection(self._config)
    cursor = None
    try:
      cursor = await _call(connection.cursor)
      await _call(
          cursor.execute,
          f"""
          SELECT user_id, session_id, state_json, last_update_time
          FROM {sessions_table}
          WHERE {" AND ".join(where_clauses)}
          ORDER BY last_update_time DESC, user_id ASC, session_id ASC
          """,
          params,
      )
      rows = await _call(cursor.fetchall)
      sessions = []
      app_state = await self._load_app_state(cursor, app_name)
      for row in rows:
        session_user_id = row[0]
        session_id = row[1]
        session_state = await _json_to_dict(row[2])
        last_update_time = _timestamp_to_float(row[3])
        user_state_for_session = await self._load_user_state(
            cursor, app_name, session_user_id
        )
        sessions.append(
            Session(
                app_name=app_name,
                user_id=session_user_id,
                id=session_id,
                state=_merge_state(
                    app_state, user_state_for_session, session_state
                ),
                events=[],
                last_update_time=last_update_time,
            )
        )
      return ListSessionsResponse(sessions=sessions)
    finally:
      if cursor is not None:
        await _close(cursor)
      await _close(connection)

  @override
  async def delete_session(
      self, *, app_name: str, user_id: str, session_id: str
  ) -> None:
    sessions_table = self._table_name("SESSIONS")
    await self._initialize_schema()
    connection = await create_oracle_connection(self._config)
    cursor = None
    try:
      cursor = await _call(connection.cursor)
      await _call(
          cursor.execute,
          f"""
          DELETE FROM {sessions_table}
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
      await _call(connection.commit)
    finally:
      if cursor is not None:
        await _close(cursor)
      await _close(connection)

  @override
  async def append_event(self, session: Session, event: Event) -> Event:
    if event.partial:
      return event

    await self._initialize_schema()
    self._apply_temp_state(session, event)
    event = self._trim_temp_delta_state(event)

    event_timestamp = event.timestamp or platform_time.get_time()
    event.timestamp = event_timestamp
    event_time = datetime.fromtimestamp(event_timestamp, tz=timezone.utc)
    state_delta = event.actions.state_delta or {}
    sessions_table = self._table_name("SESSIONS")
    events_table = self._table_name("EVENTS")

    connection = await create_oracle_connection(self._config)
    cursor = None
    try:
      cursor = await _call(connection.cursor)
      await _call(
          cursor.execute,
          f"""
          SELECT state_json
          FROM {sessions_table}
          WHERE app_name = :app_name
            AND user_id = :user_id
            AND session_id = :session_id
          FOR UPDATE
          """,
          {
              "app_name": session.app_name,
              "user_id": session.user_id,
              "session_id": session.id,
          },
      )
      session_row = await _call(cursor.fetchone)
      if session_row is None:
        raise ValueError(f"Session {session.id} not found.")

      stored_state = await _json_to_dict(session_row[0])
      state_deltas = _extract_state_delta(state_delta)
      app_state_delta = state_deltas["app"]
      user_state_delta = state_deltas["user"]
      session_state_delta = state_deltas["session"]
      if app_state_delta:
        await self._upsert_app_state(
            cursor, session.app_name, app_state_delta, event_time
        )
      if user_state_delta:
        await self._upsert_user_state(
            cursor,
            session.app_name,
            session.user_id,
            user_state_delta,
            event_time,
        )
      if session_state_delta:
        stored_state.update(session_state_delta)

      await _call(
          cursor.execute,
          f"""
          UPDATE {sessions_table}
          SET state_json = :state_json,
              last_update_time = :last_update_time
          WHERE app_name = :app_name
            AND user_id = :user_id
            AND session_id = :session_id
          """,
          {
              "state_json": _json_dump(stored_state),
              "last_update_time": event_time,
              "app_name": session.app_name,
              "user_id": session.user_id,
              "session_id": session.id,
          },
      )
      await _call(
          cursor.execute,
          f"""
          INSERT INTO {events_table} (
            app_name,
            user_id,
            session_id,
            event_id,
            event_ts,
            event_json
          )
          VALUES (
            :app_name,
            :user_id,
            :session_id,
            :event_id,
            :event_ts,
            :event_json
          )
          """,
          {
              "app_name": session.app_name,
              "user_id": session.user_id,
              "session_id": session.id,
              "event_id": event.id,
              "event_ts": event_time,
              "event_json": event.model_dump_json(exclude_none=True),
          },
      )
      await _call(connection.commit)
    except BaseException:
      await _rollback(connection)
      raise
    finally:
      if cursor is not None:
        await _close(cursor)
      await _close(connection)

    session.last_update_time = event_timestamp
    return await super().append_event(session, event)

  @override
  async def flush(self) -> None:
    pass

  async def get_user_state(self, app_name: str, user_id: str) -> dict[str, Any]:
    await self._initialize_schema()
    connection = await create_oracle_connection(self._config)
    cursor = None
    try:
      cursor = await _call(connection.cursor)
      state = await self._load_user_state(cursor, app_name, user_id)
      return dict(state)
    finally:
      if cursor is not None:
        await _close(cursor)
      await _close(connection)

  async def get_app_state(self, app_name: str) -> dict[str, Any]:
    await self._initialize_schema()
    connection = await create_oracle_connection(self._config)
    cursor = None
    try:
      cursor = await _call(connection.cursor)
      state = await self._load_app_state(cursor, app_name)
      return dict(state)
    finally:
      if cursor is not None:
        await _close(cursor)
      await _close(connection)
