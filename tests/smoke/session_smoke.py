from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlencode
import uuid


REPO_ROOT = Path(__file__).resolve().parents[2]
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


def _state_delta_event(state_delta: dict[str, object]) -> Event:
  return Event(
      id=f"smoke-state-event-{uuid.uuid4().hex}",
      invocation_id=f"smoke-state-invocation-{uuid.uuid4().hex}",
      author="user",
      timestamp=time.time(),
      content=types.Content(
          role="user",
          parts=[types.Part.from_text(text="Update scoped state.")],
      ),
      actions=EventActions(state_delta=state_delta),
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


def _config_validation_smoke() -> None:
  generated_user = f"test-user-{uuid.uuid4().hex}"
  generated_value = f"test-db-value-{uuid.uuid4().hex}"
  default_config = OracleSessionServiceConfig(
      user=generated_user,
      password=generated_value,
      dsn="localhost:1521/FREEPDB1",
  )
  assert default_config.pool_min == 1
  assert default_config.pool_max == 4

  valid_config = OracleSessionServiceConfig(
      user=generated_user,
      password=generated_value,
      dsn="localhost:1521/FREEPDB1",
      pool_min=2,
      pool_max=5,
  )
  assert valid_config.pool_min == 2
  assert valid_config.pool_max == 5

  try:
    OracleSessionServiceConfig(
        user=generated_user,
        password=generated_value,
        dsn="localhost:1521/FREEPDB1",
        pool_min=5,
        pool_max=1,
    )
  except ValueError as exc:
    if "pool_max" not in str(exc):
      raise
  else:
    raise SystemExit("OracleSessionServiceConfig accepted pool_max < pool_min")
  print("session config validation smoke passed")


async def _delete_session_if_exists(
    service: OracleSessionService,
    *,
    app_name: str,
    user_id: str,
    session_id: str | None,
) -> None:
  if session_id is None:
    return
  await service.delete_session(
      app_name=app_name,
      user_id=user_id,
      session_id=session_id,
  )


async def _delete_if_exists(
    service: OracleSessionService, session_id: str | None
) -> None:
  await _delete_session_if_exists(
      service,
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


def _assert_absent(state: dict[str, object], key: str, context: str) -> None:
  if key in state:
    raise SystemExit(f"{context} unexpectedly contained {key!r}: {state}")


def _assert_state_value(
    state: dict[str, object],
    key: str,
    expected: object,
    context: str,
) -> None:
  if state.get(key) != expected:
    raise SystemExit(
        f"{context} expected {key!r}={expected!r}, got {state.get(key)!r}"
    )


async def _state_scope_smoke(service: OracleSessionService) -> None:
  smoke_id = uuid.uuid4().hex
  app_name = f"{APP_NAME}_state_{smoke_id}"
  other_app_name = f"{APP_NAME}_other_state_{smoke_id}"
  user_id = f"{USER_ID}_state_{smoke_id}"
  other_user_id = f"{USER_ID}_other_state_{smoke_id}"
  cleanup: list[tuple[str, str, str]] = []

  async def create(
      *,
      app: str,
      user: str,
      state: dict[str, object] | None = None,
  ):
    session = await service.create_session(
        app_name=app,
        user_id=user,
        state=state,
    )
    cleanup.append((app, user, session.id))
    return session

  try:
    session_a = await create(
        app=app_name,
        user=user_id,
        state={
            "trip": "Goa",
            "user:preference": "aisle",
            "app:policy": "standard",
            "temp:scratch": "not-persisted",
        },
    )
    _assert_state_value(session_a.state, "trip", "Goa", "session A create")
    _assert_state_value(
        session_a.state, "user:preference", "aisle", "session A create"
    )
    _assert_state_value(
        session_a.state, "app:policy", "standard", "session A create"
    )
    _assert_absent(session_a.state, "temp:scratch", "session A create")

    loaded_a = await service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_a.id,
    )
    if loaded_a is None:
      raise SystemExit("state scope smoke could not load session A")
    _assert_state_value(loaded_a.state, "trip", "Goa", "session A load")
    _assert_state_value(
        loaded_a.state, "user:preference", "aisle", "session A load"
    )
    _assert_state_value(
        loaded_a.state, "app:policy", "standard", "session A load"
    )
    _assert_absent(loaded_a.state, "temp:scratch", "session A load")

    session_b = await create(app=app_name, user=user_id)
    _assert_state_value(
        session_b.state, "user:preference", "aisle", "session B create"
    )
    _assert_state_value(
        session_b.state, "app:policy", "standard", "session B create"
    )
    _assert_absent(session_b.state, "trip", "session B create")
    _assert_absent(session_b.state, "temp:scratch", "session B create")

    session_c = await create(app=app_name, user=other_user_id)
    _assert_state_value(
        session_c.state, "app:policy", "standard", "session C create"
    )
    _assert_absent(session_c.state, "user:preference", "session C create")

    session_d = await create(app=other_app_name, user=user_id)
    _assert_absent(session_d.state, "app:policy", "session D create")
    _assert_absent(session_d.state, "user:preference", "session D create")

    event = _state_delta_event(
        {
            "trip_note": "museum",
            "user:preference": "window",
            "app:policy": "updated",
            "temp:scratch": "transient",
        }
    )
    await service.append_event(session=session_b, event=event)
    _assert_state_value(
        session_b.state, "temp:scratch", "transient", "session B in-memory"
    )

    loaded_b = await service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_b.id,
    )
    if loaded_b is None:
      raise SystemExit("state scope smoke could not load session B")
    _assert_state_value(loaded_b.state, "trip_note", "museum", "session B load")
    _assert_state_value(
        loaded_b.state, "user:preference", "window", "session B load"
    )
    _assert_state_value(
        loaded_b.state, "app:policy", "updated", "session B load"
    )
    _assert_absent(loaded_b.state, "temp:scratch", "session B load")
    if not loaded_b.events:
      raise SystemExit("session B loaded without appended event")
    loaded_delta = loaded_b.events[-1].actions.state_delta or {}
    _assert_absent(loaded_delta, "temp:scratch", "session B event delta")
    _assert_state_value(
        loaded_delta, "user:preference", "window", "session B event delta"
    )
    _assert_state_value(
        loaded_delta, "app:policy", "updated", "session B event delta"
    )
    _assert_state_value(
        loaded_delta, "trip_note", "museum", "session B event delta"
    )

    session_e = await create(app=app_name, user=user_id)
    _assert_state_value(
        session_e.state, "user:preference", "window", "session E create"
    )
    _assert_state_value(
        session_e.state, "app:policy", "updated", "session E create"
    )
    _assert_absent(session_e.state, "trip_note", "session E create")

    session_f = await create(app=app_name, user=other_user_id)
    _assert_state_value(
        session_f.state, "app:policy", "updated", "session F create"
    )
    _assert_absent(session_f.state, "user:preference", "session F create")

    user_state = await service.get_user_state(app_name, user_id)
    _assert_state_value(
        user_state, "preference", "window", "direct user state"
    )
    _assert_absent(user_state, "user:preference", "direct user state")
    app_state = await service.get_app_state(app_name)
    _assert_state_value(app_state, "policy", "updated", "direct app state")
    _assert_absent(app_state, "app:policy", "direct app state")

    await service.delete_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_b.id,
    )
    cleanup = [
        item for item in cleanup if item != (app_name, user_id, session_b.id)
    ]
    session_g = await create(app=app_name, user=user_id)
    _assert_state_value(
        session_g.state, "user:preference", "window", "session G create"
    )
    _assert_state_value(
        session_g.state, "app:policy", "updated", "session G create"
    )
    print("session scoped-state smoke passed")
  finally:
    for app_name_value, user_id_value, session_id in reversed(cleanup):
      await _delete_session_if_exists(
          service,
          app_name=app_name_value,
          user_id=user_id_value,
          session_id=session_id,
      )


async def main() -> None:
  _config_validation_smoke()
  _registry_construction_smoke()
  service = OracleSessionService(_config_from_env())
  await _lifecycle_smoke(service)
  await _append_event_smoke(service)
  await _state_scope_smoke(service)
  print("session smoke completed successfully")


if __name__ == "__main__":
  asyncio.run(main())
