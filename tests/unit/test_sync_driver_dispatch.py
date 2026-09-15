from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from collections.abc import Coroutine
from datetime import datetime
from datetime import timezone
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import AsyncMock
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))

from adk_oracledb.artifacts import OracleArtifactService
from adk_oracledb.artifacts import OracleArtifactServiceConfig
from adk_oracledb.sessions import OracleSessionService
from adk_oracledb.sessions import OracleSessionServiceConfig


class _SyncCursor:

  def __init__(self, rows: list[tuple[object, ...]]) -> None:
    self._rows = rows
    self._last_statement = ""
    self.operation_started = threading.Event()
    self.thread_ids: list[int] = []

  def execute(self, statement: str, params: object = None) -> None:
    del params
    self.thread_ids.append(threading.get_ident())
    self._last_statement = statement
    self.operation_started.set()
    time.sleep(0.05)

  def fetchone(self) -> tuple[object, ...] | None:
    self.thread_ids.append(threading.get_ident())
    if "FROM ADK_SESSIONS" in self._last_statement:
      return ("{}", datetime.now(timezone.utc))
    return None

  def fetchall(self) -> list[tuple[object, ...]]:
    self.thread_ids.append(threading.get_ident())
    return self._rows

  def close(self) -> None:
    self.thread_ids.append(threading.get_ident())


class _SyncConnection:

  def __init__(self, cursor: _SyncCursor) -> None:
    self._cursor = cursor
    self.thread_ids: list[int] = []

  def cursor(self) -> _SyncCursor:
    self.thread_ids.append(threading.get_ident())
    return self._cursor

  def commit(self) -> None:
    self.thread_ids.append(threading.get_ident())

  def close(self) -> None:
    self.thread_ids.append(threading.get_ident())


class SyncDriverDispatchTest(unittest.IsolatedAsyncioTestCase):

  async def _assert_runs_off_event_loop(
      self,
      operation: Coroutine[object, object, object],
      connection: _SyncConnection,
      cursor: _SyncCursor,
      service_module: str,
  ) -> None:
    event_loop_thread = threading.get_ident()
    with (
        patch(f"{service_module}.supports_async_connections", return_value=False),
        patch(
            f"{service_module}.create_oracle_connection",
            new=AsyncMock(return_value=connection),
        ),
    ):
      task = asyncio.create_task(operation)
      await asyncio.wait_for(
          asyncio.to_thread(cursor.operation_started.wait), timeout=1
      )
      await asyncio.sleep(0)
      self.assertFalse(task.done())
      await task

    thread_ids = cursor.thread_ids + connection.thread_ids
    self.assertTrue(thread_ids)
    self.assertTrue(all(thread_id != event_loop_thread for thread_id in thread_ids))

  async def _assert_schema_runs_off_event_loop(
      self,
      initialize_schema: Awaitable[object],
      connection: _SyncConnection,
      cursor: _SyncCursor,
      service_module: str,
  ) -> None:
    event_loop_thread = threading.get_ident()
    with (
        patch(f"{service_module}.supports_async_connections", return_value=False),
        patch(
            f"{service_module}.create_oracle_connection",
            new=AsyncMock(return_value=connection),
        ),
    ):
      await initialize_schema

    thread_ids = cursor.thread_ids + connection.thread_ids
    self.assertTrue(thread_ids)
    self.assertTrue(all(thread_id != event_loop_thread for thread_id in thread_ids))

  async def test_session_reads_use_worker_thread_for_sync_driver(self) -> None:
    service = OracleSessionService(
        OracleSessionServiceConfig(
            user="test_user",
            password="test_password",
            dsn="localhost:1521/FREEPDB1",
            auto_create_tables=False,
        )
    )
    cursor = _SyncCursor(rows=[])
    connection = _SyncConnection(cursor)

    await self._assert_runs_off_event_loop(
        service.get_session(
            app_name="test_app", user_id="test_user", session_id="test_session"
        ),
        connection,
        cursor,
        "adk_oracledb.sessions.service",
    )

  async def test_artifact_reads_use_worker_thread_for_sync_driver(self) -> None:
    service = OracleArtifactService(
        OracleArtifactServiceConfig(
            user="test_user",
            password="test_password",
            dsn="localhost:1521/FREEPDB1",
            auto_create_tables=False,
        )
    )
    cursor = _SyncCursor(rows=[("report.pdf",)])
    connection = _SyncConnection(cursor)

    await self._assert_runs_off_event_loop(
        service.list_artifact_keys(app_name="test_app", user_id="test_user"),
        connection,
        cursor,
        "adk_oracledb.artifacts.service",
    )

  async def test_session_schema_creation_uses_worker_thread_for_sync_driver(
      self,
  ) -> None:
    service = OracleSessionService(
        OracleSessionServiceConfig(
            user="test_user",
            password="test_password",
            dsn="localhost:1521/FREEPDB1",
        )
    )
    cursor = _SyncCursor(rows=[])
    connection = _SyncConnection(cursor)

    await self._assert_schema_runs_off_event_loop(
        service._initialize_schema(),
        connection,
        cursor,
        "adk_oracledb.sessions.service",
    )
    self.assertTrue(service._schema_initialized)

  async def test_artifact_schema_creation_uses_worker_thread_for_sync_driver(
      self,
  ) -> None:
    service = OracleArtifactService(
        OracleArtifactServiceConfig(
            user="test_user",
            password="test_password",
            dsn="localhost:1521/FREEPDB1",
        )
    )
    cursor = _SyncCursor(rows=[])
    connection = _SyncConnection(cursor)

    await self._assert_schema_runs_off_event_loop(
        service._ensure_schema(),
        connection,
        cursor,
        "adk_oracledb.artifacts.service",
    )
    self.assertTrue(service._schema_initialized)


if __name__ == "__main__":
  unittest.main()
