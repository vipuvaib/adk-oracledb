"""Behavioral regressions for the two repaired functional-test defects.

These checks require no database or model provider. The separate functional
suite exercises the real Oracle adapter and database.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def _load_cases(name, filename):
  spec = importlib.util.spec_from_file_location(
      name, ROOT / "tests/functional" / filename
  )
  module = importlib.util.module_from_spec(spec)
  sys.modules[name] = module
  spec.loader.exec_module(module)
  return module


fixtures = _load_cases("_adk_proofread_fixtures", "conftest.py")
memory_cases = _load_cases("_adk_proofread_memory_cases", "test_memory.py")


class ReplacingCursor:
  """Model the DB-API behavior: executing DDL invalidates SELECT results."""

  def __init__(self, names):
    self.names = names
    self.active = None
    self.dropped = []

  def __enter__(self):
    return self

  def __exit__(self, *args):
    pass

  def execute(self, statement, **kwargs):
    if statement.startswith("SELECT"):
      self.active = iter((name,) for name in self.names)
    else:
      self.active = None
      self.dropped.append(statement.split()[2])

  def __iter__(self):
    return self

  def __next__(self):
    if self.active is None:
      raise RuntimeError("The active cursor statement is no longer a query")
    return next(self.active)

  def fetchall(self):
    return list(self)


class MemoryCleanupRegressionTest(unittest.TestCase):
  def test_all_selected_tables_are_dropped_before_closing_connection(self):
    for count in (0, 1, 3):
      with self.subTest(table_count=count):
        names = [f"ADKTEST_T{index}" for index in range(count)]
        cursor = ReplacingCursor(names)
        connection = Mock()
        connection.cursor.return_value = cursor
        with (
            patch("oracledb.connect", return_value=connection),
            patch.dict("os.environ", {
                "ORACLE_AI_DB_USER": "unused-mocked-user",
                "ORACLE_AI_DB_PASSWORD": "unused-mocked-password",
                "ORACLE_AI_DB_DSN": "unused-mocked-dsn",
            }),
        ):
          fixtures._drop_memory_tables("ADKTEST")
        self.assertEqual(cursor.dropped, names)
        connection.commit.assert_called_once()
        connection.close.assert_called_once()


class ConcurrentMemoryRegressionTest(unittest.IsolatedAsyncioTestCase):
  async def test_original_case_starts_both_writes_concurrently(self):
    class RecordingService:
      def __init__(self):
        self.started = set()
        self.rows = {}
        self.both_started = asyncio.Event()

      async def add_memory(self, *, app_name, user_id, memories):
        self.started.add(user_id)
        if len(self.started) == 2:
          self.both_started.set()
        await asyncio.wait_for(self.both_started.wait(), timeout=2)
        self.rows[(app_name, user_id)] = memories

      async def search_memory(self, *, app_name, user_id, query):
        return SimpleNamespace(memories=self.rows[(app_name, user_id)])

    service = RecordingService()
    await memory_cases.test_memory_client_initialization_is_shared_across_concurrent_calls(
        (service, "UNUSED_MOCKED_PREFIX")
    )
    self.assertEqual(service.started, {"user-0", "user-1"})
    self.assertEqual(len(service.rows), 2)


if __name__ == "__main__":
  unittest.main()
