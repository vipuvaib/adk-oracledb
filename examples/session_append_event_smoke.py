from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import time
from typing import NoReturn
import uuid


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))

from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

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
    _fail("get_session returned None after append_event")
  if len(loaded.events) != 1:
    _fail(f"expected 1 loaded event, got {len(loaded.events)}")
  if loaded.state.get("destination") != "Goa":
    _fail(f"expected destination='Goa', got {loaded.state.get('destination')!r}")
  if loaded.state.get("days") != 2:
    _fail(f"expected days=2, got {loaded.state.get('days')!r}")
  if not isinstance(loaded.events[0], Event):
    _fail(f"expected loaded event to be Event, got {type(loaded.events[0])!r}")

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
