from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlencode
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

from google.adk.cli.service_registry import get_service_registry
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

from adk_oracledb.registry import register_oracle_services
from adk_oracledb.sessions.service import OracleSessionService
from adk_oracledb.sessions.service import OracleSessionServiceConfig


load_repo_env(__file__)

APP_NAME = "smoke_app"
USER_ID = "smoke_user"


def _table_prefix() -> str:
  return os.environ.get("ORACLE_SESSION_TABLE_PREFIX", "ADK_SMOKE")


def _config_from_env() -> OracleSessionServiceConfig:
  return OracleSessionServiceConfig(
      user=require_env("ORACLE_AI_DB_USER"),
      password=require_env("ORACLE_AI_DB_PASSWORD"),
      dsn=require_env("ORACLE_AI_DB_DSN"),
      table_prefix=_table_prefix(),
      auto_create_tables=True,
  )


def _registry_uri() -> str:
  return f"oracle://?{urlencode({'table_prefix': _table_prefix()})}"


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


def _registry_construction_smoke() -> None:
  register_oracle_services()
  registry = get_service_registry()
  service = registry.create_session_service(_registry_uri())
  if not isinstance(service, OracleSessionService):
    raise SystemExit(
        "registry did not construct an OracleSessionService for oracle://"
    )
  print("session registry construction smoke passed")


async def _delete_if_exists(
    service: OracleSessionService, session_id: str | None
) -> None:
  if session_id is None:
    return
  await service.delete_session(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
  )


async def _lifecycle_smoke(service: OracleSessionService) -> None:
  session_id: str | None = None
  try:
    created = await service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        state={"phase": "smoke", "step": 1},
    )
    session_id = created.id
    print(f"created session id: {created.id}")

    loaded = await service.get_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=created.id,
    )
    if loaded is None:
      raise SystemExit("get_session returned None immediately after create_session")
    if loaded.state.get("phase") != "smoke":
      raise SystemExit(f"loaded state mismatch: {loaded.state}")
    print(f"loaded session id: {loaded.id}")
    print(f"loaded state: {loaded.state}")
    print(f"loaded event count: {len(loaded.events)}")

    listed = await service.list_sessions(app_name=APP_NAME, user_id=USER_ID)
    print(f"listed session count: {len(listed.sessions)}")
    if created.id not in {session.id for session in listed.sessions}:
      raise SystemExit("list_sessions did not include the created session")

    await service.delete_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=created.id,
    )
    session_id = None
    print(f"deleted session id: {created.id}")

    deleted = await service.get_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=created.id,
    )
    if deleted is not None:
      raise SystemExit("get_session returned a session after delete_session")
    print("delete confirmed: get_session returned None")
    print("session lifecycle smoke passed")
  finally:
    await _delete_if_exists(service, session_id)


async def _append_event_smoke(service: OracleSessionService) -> None:
  session_id: str | None = None
  try:
    session = await service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        state={"phase": "append_smoke"},
    )
    session_id = session.id
    print(f"created append_event session id: {session.id}")

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
    if loaded.events[0].id != event.id:
      raise SystemExit(
          f"expected loaded event id {event.id!r}, got {loaded.events[0].id!r}"
      )
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
    print("session append_event smoke passed")
  finally:
    await _delete_if_exists(service, session_id)


async def main() -> None:
  _registry_construction_smoke()
  service = OracleSessionService(_config_from_env())
  await _lifecycle_smoke(service)
  await _append_event_smoke(service)
  print("session smoke completed successfully")


if __name__ == "__main__":
  asyncio.run(main())
