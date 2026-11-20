"""Focused regression tests for the 2026-11-13 Proofread findings."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from adk_oracledb.connection import OracleConnectionFactory
from adk_oracledb.sessions import OracleSessionService, OracleSessionServiceConfig
from adk_oracledb.sessions import service as sessions_module


class ReviewConnectionDispatchTest(unittest.IsolatedAsyncioTestCase):
  def _driver(self, thin):
    return SimpleNamespace(
        is_thin_mode=Mock(return_value=thin),
        connect=Mock(return_value="sync-connection"),
        connect_async=AsyncMock(return_value="async-connection"),
        create_pool=Mock(return_value="sync-pool"),
        create_pool_async=Mock(return_value="async-pool"),
    )

  def _factory(self, driver):
    config = SimpleNamespace(user="test", password="test", dsn="test", pool_min=1, pool_max=2)
    with patch("adk_oracledb.connection._load_oracledb", return_value=driver):
      return OracleConnectionFactory(config)

  async def test_thick_connections_use_sync_despite_async_api_presence(self):
    driver = self._driver(False)
    factory = self._factory(driver)
    self.assertEqual(await factory.create_connection(), "sync-connection")
    self.assertFalse(factory.supports_async_connections)
    driver.connect_async.assert_not_called()

  async def test_thick_pools_use_sync_despite_async_api_presence(self):
    driver = self._driver(False)
    factory = self._factory(driver)
    self.assertEqual(await factory.create_pool(), "sync-pool")
    self.assertFalse(factory.supports_async)
    driver.create_pool_async.assert_not_called()

  async def test_thin_connections_and_pools_keep_using_async_apis(self):
    driver = self._driver(True)
    factory = self._factory(driver)
    self.assertTrue(factory.supports_async)
    self.assertTrue(factory.supports_async_connections)
    self.assertEqual(await factory.create_connection(), "async-connection")
    self.assertEqual(await factory.create_pool(), "async-pool")
    driver.connect.assert_not_called()
    driver.create_pool.assert_not_called()

  async def test_sync_only_driver_remains_supported(self):
    driver = SimpleNamespace(is_thin_mode=lambda: False,
        connect=Mock(return_value="sync-connection"),
        create_pool=Mock(return_value="sync-pool"))
    factory = self._factory(driver)
    self.assertFalse(factory.supports_async)
    self.assertFalse(factory.supports_async_connections)
    self.assertEqual(await factory.create_connection(), "sync-connection")
    self.assertEqual(await factory.create_pool(), "sync-pool")


class ReviewSessionIndexTest(unittest.IsolatedAsyncioTestCase):
  async def _initialize(self, rows, failure=None, table_rows=None, table_failure=None):
    self.cursor = Mock()
    index_rows = iter(rows)
    table_values = iter(table_rows) if table_rows is not None else None
    metadata_type = None

    async def fetchone():
      if metadata_type == "TABLE":
        return next(table_values) if table_values is not None else (1,)
      return next(index_rows)

    self.cursor.fetchone = AsyncMock(side_effect=fetchone)
    self.cursor.close = AsyncMock()

    async def execute(sql, *args):
      nonlocal metadata_type
      if sql.lstrip().startswith("SELECT"):
        metadata_type = args[0]["object_type"]
      if sql.lstrip().startswith("CREATE TABLE") and table_failure:
        raise table_failure
      if sql.lstrip().startswith("CREATE INDEX") and failure:
        raise failure

    self.cursor.execute = AsyncMock(side_effect=execute)
    self.connection = Mock()
    self.connection.cursor.return_value = self.cursor
    self.connection.commit = AsyncMock()
    self.connection.rollback = AsyncMock()
    self.connection.close = AsyncMock()
    service = OracleSessionService(OracleSessionServiceConfig(
        user="test", password="test", dsn="test"))
    with patch.object(sessions_module, "create_oracle_connection", AsyncMock(return_value=self.connection)):
      await service._initialize_schema_impl()

  def _index_creations(self):
    return [c for c in self.cursor.execute.call_args_list
            if c.args[0].lstrip().startswith("CREATE INDEX")]

  async def test_existing_index_is_skipped(self):
    await self._initialize([(1,)])
    self.assertEqual(self._index_creations(), [])
    self.assertFalse(any(c.args[0].lstrip().startswith("CREATE TABLE")
                         for c in self.cursor.execute.call_args_list))

  async def test_missing_index_is_created(self):
    await self._initialize([None])
    self.assertEqual(len(self._index_creations()), 1)

  async def test_creation_race_is_accepted_only_when_index_appears(self):
    await self._initialize([None, (1,)], RuntimeError("ORA-00054: resource busy"))
    self.connection.commit.assert_awaited_once()

  async def test_lock_error_with_missing_index_is_preserved(self):
    with self.assertRaisesRegex(RuntimeError, "ORA-00054"):
      await self._initialize([None, None], RuntimeError("ORA-00054: resource busy"))
    self.connection.rollback.assert_awaited_once()
    self.connection.close.assert_awaited_once()

  async def test_unrelated_ddl_error_is_preserved(self):
    with self.assertRaisesRegex(RuntimeError, "ORA-01031"):
      await self._initialize([None], RuntimeError("ORA-01031: insufficient privileges"))


  async def test_missing_table_is_created(self):
    await self._initialize([(1,)], table_rows=[None, (1,), (1,), (1,)])
    creates = [c for c in self.cursor.execute.call_args_list
               if c.args[0].lstrip().startswith("CREATE TABLE")]
    self.assertEqual(len(creates), 1)

  async def test_concurrent_table_creation_is_accepted_if_table_appears(self):
    await self._initialize([(1,)], table_rows=[None, (1,), (1,), (1,), (1,)],
                           table_failure=RuntimeError("ORA-00054: resource busy"))
    self.connection.commit.assert_awaited_once()

  async def test_missing_table_lock_remains_an_error(self):
    with self.assertRaisesRegex(RuntimeError, "ORA-00054"):
      await self._initialize([], table_rows=[None, None],
                             table_failure=RuntimeError("ORA-00054: resource busy"))
    self.connection.rollback.assert_awaited_once()

  async def test_unrelated_table_error_is_preserved(self):
    with self.assertRaisesRegex(RuntimeError, "ORA-01031"):
      await self._initialize([], table_rows=[None],
                             table_failure=RuntimeError("ORA-01031: insufficient privileges"))
