#!/bin/python
#
# $Header: test_sessions.py 22-jul-2026.21:16:18 dascenci Exp $
#
# test_sessions.py
#
# Copyright (c) 2026, Oracle and/or its affiliates.
#
#    NAME
#      test_sessions.py - OracleSessionService functional database tests
#
#    DESCRIPTION
#      Validates session schema, constraints, commit/rollback behavior,
#      isolation, concurrency, event persistence, and delete cascades against
#      a real Oracle Database.
#
#    NOTES
#      Tests inspect Oracle data dictionary views only to validate the database
#      contract; functional behavior is exercised through the public service.
#
#    MODIFIED   (MM/DD/YY)
#    dascenci    07/22/26 - add ADK session functional tests
#    dascenci    07/22/26 - Creation
#
"""Real-Oracle functional coverage for OracleSessionService."""

from __future__ import annotations

import os
import time
import asyncio

from google.adk.errors.already_exists_error import AlreadyExistsError
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types
import oracledb
import pytest


pytestmark = pytest.mark.oracle


def _table_names(prefix: str) -> set[str]:
  connection = oracledb.connect(
      user=os.environ["ORACLE_AI_DB_USER"],
      password=os.environ["ORACLE_AI_DB_PASSWORD"],
      dsn=os.environ["ORACLE_AI_DB_DSN"],
  )
  try:
    with connection.cursor() as cursor:
      cursor.execute(
          "SELECT table_name FROM user_tables WHERE table_name LIKE :prefix",
          prefix=f"{prefix}_%",
      )
      return {row[0] for row in cursor}
  finally:
    connection.close()


def _index_names(prefix: str) -> set[str]:
  connection = oracledb.connect(
      user=os.environ["ORACLE_AI_DB_USER"],
      password=os.environ["ORACLE_AI_DB_PASSWORD"],
      dsn=os.environ["ORACLE_AI_DB_DSN"],
  )
  try:
    with connection.cursor() as cursor:
      cursor.execute(
          "SELECT index_name FROM user_indexes WHERE index_name LIKE :prefix",
          prefix=f"{prefix}_%",
      )
      return {row[0] for row in cursor}
  finally:
    connection.close()


def _query_scalar(sql: str, **binds: object) -> object:
  connection = oracledb.connect(
      user=os.environ["ORACLE_AI_DB_USER"],
      password=os.environ["ORACLE_AI_DB_PASSWORD"],
      dsn=os.environ["ORACLE_AI_DB_DSN"],
  )
  try:
    with connection.cursor() as cursor:
      cursor.execute(sql, binds)
      return cursor.fetchone()[0]
  finally:
    connection.close()


@pytest.mark.asyncio
async def test_session_schema_creates_expected_tables_and_index(
    oracle_functional_environment,
) -> None:
  """The service creates its tables and event-order index in the real DB."""
  environment = oracle_functional_environment
  await environment.session_service.create_session(
      app_name="schema-app", user_id="schema-user", state={"phase": "schema"}
  )

  assert {
      f"{environment.prefix}_SESSIONS",
      f"{environment.prefix}_APP_STATES",
      f"{environment.prefix}_USER_STATES",
      f"{environment.prefix}_EVENTS",
  } <= _table_names(environment.prefix)
  assert f"{environment.prefix}_EVENTS_ORDER_IX" in _index_names(
      environment.prefix
  )
  foreign_key_count = _query_scalar(
      """
      SELECT COUNT(*)
      FROM user_constraints
      WHERE table_name = :table_name
        AND constraint_type = 'R'
        AND delete_rule = 'CASCADE'
      """,
      table_name=f"{environment.prefix}_EVENTS",
  )
  assert foreign_key_count == 1


@pytest.mark.asyncio
async def test_sessions_are_isolated_by_app_and_user(
    oracle_functional_environment,
) -> None:
  """Sessions and persisted state must not leak across app/user boundaries."""
  service = oracle_functional_environment.session_service
  first = await service.create_session(
      app_name="travel", user_id="alice", state={"city": "Goa"}
  )
  second = await service.create_session(
      app_name="travel", user_id="alice", state={"city": "Pune"}
  )
  other_user = await service.create_session(
      app_name="travel", user_id="bob", state={"city": "London"}
  )
  other_app = await service.create_session(
      app_name="support", user_id="alice", state={"city": "Austin"}
  )

  alice_sessions = await service.list_sessions(app_name="travel", user_id="alice")
  assert {session.id for session in alice_sessions.sessions} == {first.id, second.id}
  assert (
      await service.get_session(
          app_name="travel", user_id="alice", session_id=other_user.id
      )
      is None
  )
  assert (
      await service.get_session(
          app_name="travel", user_id="alice", session_id=other_app.id
      )
      is None
  )


@pytest.mark.asyncio
async def test_appended_event_round_trips_through_oracle(
    oracle_functional_environment,
) -> None:
  """Appending an ADK event persists both the event and its state delta."""
  service = oracle_functional_environment.session_service
  session = await service.create_session(
      app_name="events", user_id="alice", state={"phase": "created"}
  )
  event = Event(
      id="functional-event-1",
      invocation_id="functional-invocation-1",
      author="user",
      timestamp=time.time(),
      content=types.Content(role="user", parts=[types.Part.from_text(text="Go")]),
      actions=EventActions(state_delta={"phase": "updated", "counter": 1}),
  )

  await service.append_event(session=session, event=event)
  loaded = await service.get_session(
      app_name="events", user_id="alice", session_id=session.id
  )

  assert loaded is not None
  assert loaded.state["phase"] == "updated"
  assert loaded.state["counter"] == 1
  assert [loaded_event.id for loaded_event in loaded.events] == [event.id]


@pytest.mark.asyncio
async def test_duplicate_session_rolls_back_without_persisting_new_state(
    oracle_functional_environment,
) -> None:
  """A failed create must not commit app/user/session state changes."""
  service = oracle_functional_environment.session_service
  await service.create_session(
      app_name="rollback",
      user_id="alice",
      session_id="fixed-session",
      state={"phase": "committed"},
  )

  with pytest.raises(AlreadyExistsError):
    await service.create_session(
        app_name="rollback",
        user_id="alice",
        session_id="fixed-session",
        state={"phase": "must-not-persist", "user:mode": "new"},
    )

  loaded = await service.get_session(
      app_name="rollback", user_id="alice", session_id="fixed-session"
  )
  assert loaded is not None
  assert loaded.state == {"phase": "committed"}
  assert await service.get_user_state("rollback", "alice") == {}


@pytest.mark.asyncio
async def test_failed_event_append_rolls_back_state_and_event_insert(
    oracle_functional_environment,
) -> None:
  """A duplicate event ID rolls back both the event insert and state update."""
  service = oracle_functional_environment.session_service
  session = await service.create_session(
      app_name="atomic", user_id="alice", state={"phase": "created"}
  )
  first_event = Event(
      id="same-event-id",
      invocation_id="first-invocation",
      author="user",
      timestamp=time.time(),
      content=types.Content(role="user", parts=[types.Part.from_text(text="one")]),
      actions=EventActions(state_delta={"phase": "committed"}),
  )
  await service.append_event(session=session, event=first_event)

  duplicate_event = Event(
      id="same-event-id",
      invocation_id="duplicate-invocation",
      author="user",
      timestamp=time.time(),
      content=types.Content(role="user", parts=[types.Part.from_text(text="two")]),
      actions=EventActions(state_delta={"phase": "must-not-persist"}),
  )
  with pytest.raises(oracledb.DatabaseError):
    await service.append_event(session=session, event=duplicate_event)

  loaded = await service.get_session(
      app_name="atomic", user_id="alice", session_id=session.id
  )
  assert loaded is not None
  assert loaded.state["phase"] == "committed"
  assert [event.id for event in loaded.events] == ["same-event-id"]


@pytest.mark.asyncio
async def test_concurrent_creates_commit_distinct_sessions(
    oracle_functional_environment,
) -> None:
  """Parallel session creates persist every session without cross-talk."""
  service = oracle_functional_environment.session_service
  sessions = await asyncio.gather(
      *(
          service.create_session(
              app_name="concurrent",
              user_id="alice",
              state={"ordinal": ordinal},
          )
          for ordinal in range(4)
      )
  )

  assert len({session.id for session in sessions}) == 4
  listed = await service.list_sessions(app_name="concurrent", user_id="alice")
  assert {session.id for session in listed.sessions} == {
      session.id for session in sessions
  }


@pytest.mark.asyncio
async def test_delete_session_cascades_to_persisted_events(
    oracle_functional_environment,
) -> None:
  """Deleting a session relies on and verifies the Oracle cascade contract."""
  environment = oracle_functional_environment
  service = environment.session_service
  session = await service.create_session(app_name="cascade", user_id="alice")
  await service.append_event(
      session=session,
      event=Event(
          id="cascade-event",
          invocation_id="cascade-invocation",
          author="user",
          timestamp=time.time(),
          content=types.Content(role="user", parts=[types.Part.from_text(text="go")]),
          actions=EventActions(),
      ),
  )
  assert _query_scalar(
      f"SELECT COUNT(*) FROM {environment.prefix}_EVENTS "
      "WHERE app_name = :app_name AND user_id = :user_id AND session_id = :session_id",
      app_name="cascade",
      user_id="alice",
      session_id=session.id,
  ) == 1

  await service.delete_session(
      app_name="cascade", user_id="alice", session_id=session.id
  )
  assert _query_scalar(
      f"SELECT COUNT(*) FROM {environment.prefix}_EVENTS "
      "WHERE app_name = :app_name AND user_id = :user_id AND session_id = :session_id",
      app_name="cascade",
      user_id="alice",
      session_id=session.id,
  ) == 0


@pytest.mark.asyncio
async def test_app_user_session_and_temporary_state_boundaries(
    oracle_functional_environment,
) -> None:
  """ADK state prefixes land in the correct Oracle state tables."""
  service = oracle_functional_environment.session_service
  session = await service.create_session(
      app_name="state-boundaries",
      user_id="alice",
      state={
          "app:theme": "dark",
          "user:locale": "en-US",
          "session_counter": 1,
          "temp:ignored": "not persisted",
      },
  )

  assert session.state == {
      "app:theme": "dark",
      "user:locale": "en-US",
      "session_counter": 1,
  }
  assert await service.get_app_state("state-boundaries") == {"theme": "dark"}
  assert await service.get_user_state("state-boundaries", "alice") == {
      "locale": "en-US"
  }

  event = Event(
      id="state-boundary-event",
      invocation_id="state-boundary-invocation",
      author="user",
      timestamp=time.time(),
      content=types.Content(role="user", parts=[types.Part.from_text(text="update")]),
      actions=EventActions(
          state_delta={
              "app:theme": "light",
              "user:locale": "fr-FR",
              "session_counter": 2,
              "temp:transient": "drop me",
          }
      ),
  )
  await service.append_event(session=session, event=event)
  assert await service.get_app_state("state-boundaries") == {"theme": "light"}
  assert await service.get_user_state("state-boundaries", "alice") == {
      "locale": "fr-FR"
  }
  loaded = await service.get_session(
      app_name="state-boundaries", user_id="alice", session_id=session.id
  )
  assert loaded is not None
  assert loaded.state["session_counter"] == 2
  assert "temp:transient" not in loaded.state


@pytest.mark.asyncio
async def test_missing_session_and_empty_listing_are_safe(
    oracle_functional_environment,
) -> None:
  """Reads of absent data return ADK empty responses without database errors."""
  service = oracle_functional_environment.session_service
  assert await service.get_session(
      app_name="missing", user_id="alice", session_id="does-not-exist"
  ) is None
  listed = await service.list_sessions(app_name="missing", user_id="alice")
  assert listed.sessions == []

@pytest.mark.asyncio
async def test_append_event_to_missing_session_raises(
    oracle_functional_environment,
) -> None:
  """Appending to a session that was never created fails clearly."""
  service = oracle_functional_environment.session_service
  from google.adk.sessions.session import Session

  phantom_session = Session(
      id="does-not-exist",
      app_name="missing-session",
      user_id="alice",
      state={},
      events=[],
  )
  event = Event(
      id="orphan-event",
      invocation_id="orphan-invocation",
      author="user",
      timestamp=time.time(),
      content=types.Content(role="user", parts=[types.Part.from_text(text="go")]),
      actions=EventActions(),
  )

  with pytest.raises(Exception):  # noqa: B017 -- tighten to actual ADK error once confirmed
    await service.append_event(session=phantom_session, event=event)


@pytest.mark.asyncio
async def test_delete_already_deleted_session_is_safe(
    oracle_functional_environment,
) -> None:
  """Deleting a session twice does not raise on the second call."""
  service = oracle_functional_environment.session_service
  session = await service.create_session(app_name="double-delete", user_id="alice")

  await service.delete_session(
      app_name="double-delete", user_id="alice", session_id=session.id
  )
  # Second delete should be a no-op, not an error.
  await service.delete_session(
      app_name="double-delete", user_id="alice", session_id=session.id
  )

@pytest.mark.asyncio
async def test_concurrent_appends_to_same_session_do_not_lose_events(
    oracle_functional_environment,
) -> None:
  """Parallel event appends to one session all persist without loss."""
  service = oracle_functional_environment.session_service
  session = await service.create_session(app_name="same-session-race", user_id="alice")

  async def _append(ordinal: int) -> None:
    await service.append_event(
        session=session,
        event=Event(
            id=f"race-event-{ordinal}",
            invocation_id=f"race-invocation-{ordinal}",
            author="user",
            timestamp=time.time(),
            content=types.Content(
                role="user", parts=[types.Part.from_text(text=f"event {ordinal}")]
            ),
            actions=EventActions(state_delta={f"key_{ordinal}": ordinal}),
        ),
    )

  await asyncio.gather(*(_append(ordinal) for ordinal in range(5)))

  loaded = await service.get_session(
      app_name="same-session-race", user_id="alice", session_id=session.id
  )
  assert loaded is not None
  assert {event.id for event in loaded.events} == {
      f"race-event-{ordinal}" for ordinal in range(5)
  }
  for ordinal in range(5):
    assert loaded.state[f"key_{ordinal}"] == ordinal