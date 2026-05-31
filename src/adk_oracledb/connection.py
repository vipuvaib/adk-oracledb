from __future__ import annotations

import inspect
from typing import Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from adk_oracledb.sessions.service import OracleSessionServiceConfig


def _load_oracledb() -> Any:
  try:
    import oracledb
  except ImportError as e:
    raise ImportError(
        "python-oracledb is required for adk-oracledb. "
        "Install it with: pip install oracledb"
    ) from e
  return oracledb


def _connect_kwargs(config: OracleSessionServiceConfig) -> dict[str, Any]:
  return {
      "user": config.user,
      "password": config.password,
      "dsn": config.dsn,
  }


def _pool_kwargs(config: OracleSessionServiceConfig) -> dict[str, Any]:
  return {
      **_connect_kwargs(config),
      "min": config.pool_min,
      "max": config.pool_max,
      "increment": 1,
  }


class OracleConnectionFactory:
  """Creates Oracle connections and pools from session service config."""

  def __init__(self, config: OracleSessionServiceConfig):
    self._config = config
    self._oracledb = _load_oracledb()

  @property
  def supports_async(self) -> bool:
    return hasattr(self._oracledb, "connect_async") and hasattr(
        self._oracledb, "create_pool_async"
    )

  async def create_connection(self) -> Any:
    """Create an Oracle connection, preferring python-oracledb async APIs."""
    if hasattr(self._oracledb, "connect_async"):
      connection = self._oracledb.connect_async(
          **_connect_kwargs(self._config)
      )
      if inspect.isawaitable(connection):
        connection = await connection
      return connection

    return self._oracledb.connect(**_connect_kwargs(self._config))

  async def create_pool(self) -> Any:
    """Create an Oracle connection pool, preferring async pool APIs."""
    if hasattr(self._oracledb, "create_pool_async"):
      pool = self._oracledb.create_pool_async(**_pool_kwargs(self._config))
      if inspect.isawaitable(pool):
        pool = await pool
      return pool

    return self._oracledb.create_pool(**_pool_kwargs(self._config))


async def create_oracle_connection(config: OracleSessionServiceConfig) -> Any:
  return await OracleConnectionFactory(config).create_connection()


async def create_oracle_pool(config: OracleSessionServiceConfig) -> Any:
  return await OracleConnectionFactory(config).create_pool()
