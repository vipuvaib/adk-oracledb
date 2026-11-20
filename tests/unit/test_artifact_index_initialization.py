"""Index initialization must skip existing indexes and preserve real failures."""

from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from adk_oracledb.artifacts import OracleArtifactService, OracleArtifactServiceConfig
from adk_oracledb.artifacts import service as module


class ArtifactIndexInitializationTest(unittest.IsolatedAsyncioTestCase):
  async def _initialize(self, rows, failure=None):
    self.cursor = Mock()
    self.cursor.fetchone = AsyncMock(side_effect=rows)
    self.cursor.close = AsyncMock()

    async def execute(sql, *args):
      if sql.lstrip().startswith("CREATE INDEX") and failure is not None:
        raise failure

    self.cursor.execute = AsyncMock(side_effect=execute)
    self.connection = Mock()
    self.connection.cursor.return_value = self.cursor
    self.connection.commit = AsyncMock()
    self.connection.rollback = AsyncMock()
    self.connection.close = AsyncMock()
    service = OracleArtifactService(OracleArtifactServiceConfig(
        user="mock", password="mock", dsn="mock", table_prefix="ADK"
    ))
    with patch.object(module, "create_oracle_connection", AsyncMock(return_value=self.connection)):
      await service._ensure_schema_impl()

  def _index_creations(self):
    return [call for call in self.cursor.execute.call_args_list
            if call.args[0].lstrip().startswith("CREATE INDEX")]

  async def test_existing_index_is_not_recreated(self):
    await self._initialize([(1,)])
    self.assertEqual(self._index_creations(), [])
    self.connection.commit.assert_awaited_once()

  async def test_missing_index_is_created(self):
    await self._initialize([None])
    self.assertEqual(len(self._index_creations()), 1)

  async def test_concurrent_creator_lock_is_accepted_only_if_index_exists(self):
    await self._initialize([None, (1,)], RuntimeError("ORA-00054: resource busy"))
    self.assertEqual(len(self._index_creations()), 1)
    self.connection.commit.assert_awaited_once()

  async def test_lock_with_missing_index_remains_an_error(self):
    with self.assertRaisesRegex(RuntimeError, "ORA-00054"):
      await self._initialize([None, None], RuntimeError("ORA-00054: resource busy"))
    self.connection.rollback.assert_awaited_once()
    self.connection.close.assert_awaited_once()

  async def test_unrelated_ddl_error_is_not_suppressed(self):
    with self.assertRaisesRegex(RuntimeError, "ORA-01031"):
      await self._initialize([None], RuntimeError("ORA-01031: insufficient privileges"))
    self.connection.rollback.assert_awaited_once()


if __name__ == "__main__":
  unittest.main()
