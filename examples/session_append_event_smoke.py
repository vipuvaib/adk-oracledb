from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import time
import uuid


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))
EXAMPLES_DIR = REPO_ROOT / "examples"
if str(EXAMPLES_DIR) not in sys.path:
  sys.path.insert(0, str(EXAMPLES_DIR))

from oracle_env import load_repo_env
from oracle_env import require_env

from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

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


def _new_event() -> Event:
  return Event(
      id=f"smoke-event-{uuid.uuid4().hex}",
      invocation_id=f"smoke-invocation-{uuid.uuid4().hex}",
      author="user",
      timestamp=time.time(),
      content=types.Content(
          role="user",
          parts=[
              types.Part.from_text(
                  text="Please plan a short trip to Goa for two days."
              ),
          ],
      ),
      actions=EventActions(state_delta={"destination": "Goa", "days": 2}),
  )


async def main() -> None:
  service = OracleSessionService(_config_from_env())

  session = await service.create_session(
      app_name=APP_NAME,
      user_id=USER_ID,
      state={"phase": "append_smoke"},
  )
  print(f"created session id: {session.id}")

  event = _new_event()
  appended = await service.append_event(session=session, event=event)
  print(f"appended event id: {appended.id}")

  loaded = await service.get_session(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session.id,
  )
  if loaded is None:
    raise SystemExit("get_session returned None after append_event")
  if len(loaded.events) != 1:
    raise SystemExit(f"expected 1 loaded event, got {len(loaded.events)}")
  if loaded.state.get("destination") != "Goa":
    raise SystemExit(
        f"expected destination='Goa', got {loaded.state.get('destination')!r}"
    )
  if loaded.state.get("days") != 2:
    raise SystemExit(f"expected days=2, got {loaded.state.get('days')!r}")
  if not isinstance(loaded.events[0], Event):
    raise SystemExit(
        f"expected loaded event to be Event, got {type(loaded.events[0])!r}"
    )

  print("verified loaded event count: 1")
  print(f"verified loaded state: {loaded.state}")
  print(f"verified loaded event type: {type(loaded.events[0]).__name__}")

  await service.delete_session(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session.id,
  )
  print(f"deleted session id: {session.id}")
  print("append_event smoke completed successfully")


if __name__ == "__main__":
  asyncio.run(main())
