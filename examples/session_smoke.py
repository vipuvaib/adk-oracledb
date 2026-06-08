from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))
EXAMPLES_DIR = REPO_ROOT / "examples"
if str(EXAMPLES_DIR) not in sys.path:
  sys.path.insert(0, str(EXAMPLES_DIR))

from oracle_env import load_repo_env
from oracle_env import require_env

from adk_oracledb.sessions.service import OracleSessionService
from adk_oracledb.sessions.service import OracleSessionServiceConfig


load_repo_env(__file__)

APP_NAME = "smoke_app"
USER_ID = "smoke_user"


def _config_from_env() -> OracleSessionServiceConfig:
  return OracleSessionServiceConfig(
      user=require_env("ORACLE_AI_DB_USER"),
      password=require_env("ORACLE_AI_DB_PASSWORD"),
      dsn=require_env("ORACLE_AI_DB_DSN"),
      table_prefix=os.environ.get("ORACLE_SESSION_TABLE_PREFIX", "ADK_SMOKE"),
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
    raise SystemExit("get_session returned None immediately after create_session")
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
    raise SystemExit("get_session returned a session after delete_session")
  print("delete confirmed: get_session returned None")


if __name__ == "__main__":
  asyncio.run(main())
