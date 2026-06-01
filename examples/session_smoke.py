from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
from typing import NoReturn


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))

from adk_oracledb.sessions.service import OracleSessionService
from adk_oracledb.sessions.service import OracleSessionServiceConfig


APP_NAME = "smoke_app"
USER_ID = "smoke_user"


def _fail(message: str) -> NoReturn:
  raise SystemExit(message)


def _required_env(name: str) -> str:
  value = os.environ.get(name)
  if not value:
    _fail(f"Missing required environment variable: {name}")
  return value


def _config_from_env() -> OracleSessionServiceConfig:
  return OracleSessionServiceConfig(
      user=_required_env("ORACLE_USER"),
      password=_required_env("ORACLE_PASSWORD"),
      dsn=_required_env("ORACLE_DSN"),
      table_prefix=os.environ.get("ORACLE_TABLE_PREFIX", "ADK_SMOKE"),
      auto_create_tables=True,
  )


async def main() -> None:
  service = OracleSessionService(_config_from_env())

  created = await service.create_session(
      app_name=APP_NAME,
      user_id=USER_ID,
      state={"phase": "smoke", "step": 1},
  )
  print(f"created session id: {created.id}")

  loaded = await service.get_session(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=created.id,
  )
  if loaded is None:
    _fail("get_session returned None immediately after create_session")
  print(f"loaded session id: {loaded.id}")
  print(f"loaded state: {loaded.state}")
  print(f"loaded event count: {len(loaded.events)}")

  listed = await service.list_sessions(app_name=APP_NAME, user_id=USER_ID)
  print(f"listed session count: {len(listed.sessions)}")

  await service.delete_session(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=created.id,
  )
  print(f"deleted session id: {created.id}")

  deleted = await service.get_session(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=created.id,
  )
  if deleted is not None:
    _fail("get_session returned a session after delete_session")
  print("delete confirmed: get_session returned None")


if __name__ == "__main__":
  asyncio.run(main())
