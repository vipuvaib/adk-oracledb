from __future__ import annotations

from datetime import datetime
from datetime import timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))

from adk_oracledb.sessions import OracleSessionService
from adk_oracledb.sessions import OracleSessionServiceConfig


class _Cursor:

  def __init__(self) -> None:
    self.statements: list[tuple[str, dict[str, object]]] = []
    self.execute = AsyncMock(side_effect=self._execute)

  async def _execute(self, statement: str, params: dict[str, object]) -> None:
    self.statements.append((statement, params))
    if "INSERT INTO" in statement:
      raise RuntimeError("ORA-00001: unique constraint violated")


class OracleSessionStateUpsertTest(unittest.IsolatedAsyncioTestCase):

  def _service(self) -> OracleSessionService:
    return OracleSessionService(
        OracleSessionServiceConfig(
            user="test_user",
            password="test_password",
            dsn="localhost:1521/FREEPDB1",
        )
    )

  async def test_app_state_recovers_from_first_row_insert_conflict(self) -> None:
    service = self._service()
    service._get_app_state_from_cursor = AsyncMock(
        side_effect=[
            (False, {}),
            (True, {"first_writer": "one"}),
        ]
    )
    cursor = _Cursor()

    result = await service._upsert_app_state(
        cursor,
        "test_app",
        {"second_writer": "two"},
        datetime.now(timezone.utc),
    )

    self.assertEqual(
        result,
        {"first_writer": "one", "second_writer": "two"},
    )
    self.assertEqual(service._get_app_state_from_cursor.await_count, 2)
    self.assertEqual(len(cursor.statements), 2)
    self.assertIn("INSERT INTO ADK_APP_STATES", cursor.statements[0][0])
    self.assertIn("UPDATE ADK_APP_STATES", cursor.statements[1][0])
    self.assertEqual(
        json.loads(str(cursor.statements[1][1]["state_json"])),
        {"first_writer": "one", "second_writer": "two"},
    )

  async def test_user_state_recovers_from_first_row_insert_conflict(self) -> None:
    service = self._service()
    service._get_user_state_from_cursor = AsyncMock(
        side_effect=[
            (False, {}),
            (True, {"first_writer": "one"}),
        ]
    )
    cursor = _Cursor()

    result = await service._upsert_user_state(
        cursor,
        "test_app",
        "test_user",
        {"second_writer": "two"},
        datetime.now(timezone.utc),
    )

    self.assertEqual(
        result,
        {"first_writer": "one", "second_writer": "two"},
    )
    self.assertEqual(service._get_user_state_from_cursor.await_count, 2)
    self.assertEqual(len(cursor.statements), 2)
    self.assertIn("INSERT INTO ADK_USER_STATES", cursor.statements[0][0])
    self.assertIn("UPDATE ADK_USER_STATES", cursor.statements[1][0])
    self.assertEqual(
        json.loads(str(cursor.statements[1][1]["state_json"])),
        {"first_writer": "one", "second_writer": "two"},
    )


if __name__ == "__main__":
  unittest.main()
