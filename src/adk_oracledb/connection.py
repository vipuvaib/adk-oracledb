from __future__ import annotations

import inspect
from typing import Any
from typing import Protocol


class OracleDatabaseConfig(Protocol):
  """Configuration shape shared by Oracle-backed service implementations."""

  user: str
  password: str
  dsn: str
  pool_min: int
  pool_max: int


def _load_oracledb() -> Any:
  try:
    import oracledb
  except ImportError as e:
    raise ImportError(
        "python-oracledb is required for adk-oracledb. "
        "Install it with: pip install oracledb"
    ) from e
  return oracledb


def _connect_kwargs(config: OracleDatabaseConfig) -> dict[str, Any]:
  return {
      "user": config.user,
      "password": config.password,
      "dsn": config.dsn,
  }


def _pool_kwargs(config: OracleDatabaseConfig) -> dict[str, Any]:
  return {
      **_connect_kwargs(config),
      "min": config.pool_min,
      "max": config.pool_max,
      "increment": 1,
  }


class OracleConnectionFactory:
  """Creates Oracle connections and pools from shared service config."""

  def __init__(self, config: OracleDatabaseConfig):
    self._config = config
    self._oracledb = _load_oracledb()

  @property
  def supports_async(self) -> bool:
    return hasattr(self._oracledb, "connect_async") and hasattr(
        self._oracledb, "create_pool_async"
    )

  @property
  def supports_async_connections(self) -> bool:
    """Whether this driver exposes the asynchronous connection API."""
    return hasattr(self._oracledb, "connect_async")

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


async def create_oracle_connection(config: OracleDatabaseConfig) -> Any:
  return await OracleConnectionFactory(config).create_connection()


async def create_oracle_pool(config: OracleDatabaseConfig) -> Any:
  return await OracleConnectionFactory(config).create_pool()

def supports_async_connections(config: OracleDatabaseConfig) -> bool:
  """Return whether connections for ``config`` can use async driver APIs."""
  return OracleConnectionFactory(config).supports_async_connections