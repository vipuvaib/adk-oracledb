#!/bin/python
#
# $Header: test_memory.py 23-jul-2026.18:25:42 dascenci Exp $
#
# test_memory.py
#
# Copyright (c) 2026, Oracle and/or its affiliates.
#
#    NAME
#      test_memory.py - Oracle memory service functional database tests
#
#    DESCRIPTION
#      Exercises OracleAgentMemory-backed ADK memory operations through the
#      public OracleMemoryService using a real Oracle Database.
#
#    NOTES
#      These tests require oracleagentmemory, an embedding model, and the
#      embedding endpoint credentials configured by the TPI environment.
#
#    MODIFIED   (MM/DD/YY)
#    dascenci    07/23/26 - add ADK memory functional tests
#    dascenci    07/23/26 - Creation
#
"""Real-Oracle functional coverage for OracleMemoryService."""

from __future__ import annotations

import asyncio
import uuid

from google.adk.events.event import Event
from google.adk.memory.memory_entry import MemoryEntry
from google.genai import types
import oracledb
import pytest


pytestmark = pytest.mark.oracle


def _memory_text(memory: MemoryEntry) -> str:
  if not memory.content or not memory.content.parts:
    return ""
  return "\n".join(
      part.text for part in memory.content.parts if getattr(part, "text", None)
  )


def _contains_marker(response: object, marker: str) -> bool:
  memories = getattr(response, "memories", [])
  for memory in memories:
    metadata = getattr(memory, "custom_metadata", {}) or {}
    if marker in _memory_text(memory) or marker in str(metadata):
      return True
  return False


@pytest.mark.asyncio
async def test_memory_add_search_and_user_scope(
    memory_functional_service,
) -> None:
  """Memory writes and vector search remain isolated by exact user scope."""
  service, _ = memory_functional_service
  alice_marker = f"alice-{uuid.uuid4().hex}"
  bob_marker = f"bob-{uuid.uuid4().hex}"
  await service.add_memory(
      app_name="travel",
      user_id="alice",
      memories=[
          MemoryEntry(
              id=alice_marker,
              content=types.Content(
                  role="user",
                  parts=[types.Part.from_text(text=f"Goa beach plans {alice_marker}")],
              ),
              custom_metadata={"source": "functional", "marker": alice_marker},
          )
      ],
  )
  await service.add_memory(
      app_name="travel",
      user_id="bob",
      memories=[
          MemoryEntry(
              id=bob_marker,
              content=types.Content(
                  role="user",
                  parts=[types.Part.from_text(text=f"London museum plans {bob_marker}")],
              ),
          )
      ],
  )

  alice_results = await service.search_memory(
      app_name="travel", user_id="alice", query="Where are the beach plans?"
  )
  bob_results = await service.search_memory(
      app_name="travel", user_id="bob", query="Where are the museum plans?"
  )
  assert _contains_marker(alice_results, alice_marker)
  assert _contains_marker(bob_results, bob_marker)
  assert not any(
      bob_marker in _memory_text(memory)
      for memory in alice_results.memories
  )


@pytest.mark.asyncio
async def test_memory_ingests_session_events_with_metadata(
    memory_functional_service,
) -> None:
  """Session events become searchable memory records with ADK metadata."""
  service, _ = memory_functional_service
  event_marker = f"event-{uuid.uuid4().hex}"
  event = Event(
      id=event_marker,
      invocation_id=f"invocation-{event_marker}",
      author="user",
      timestamp=1_700_000_000.0,
      content=types.Content(
          role="user",
          parts=[types.Part.from_text(text=f"Remember this trip {event_marker}")],
      ),
  )
  await service.add_events_to_memory(
      app_name="events",
      user_id="alice",
      events=[event],
      session_id="session-1",
      custom_metadata={"test_case": "event-ingest"},
  )

  response = await service.search_memory(
      app_name="events", user_id="alice", query="What trip should I remember?"
  )
  matching = [
      memory
      for memory in response.memories
      if event_marker in _memory_text(memory)
  ]
  assert matching
  assert matching[0].custom_metadata["adk_event_id"] == event_marker


@pytest.mark.asyncio
async def test_memory_empty_and_partial_inputs_do_not_create_records(
    memory_functional_service,
) -> None:
  """Empty and partial ADK inputs are no-ops, while invalid scopes fail early."""
  service, _ = memory_functional_service
  await service.add_memory(app_name="empty", user_id="alice", memories=[])
  await service.add_events_to_memory(app_name="empty", user_id="alice", events=[])

  partial_event = Event(
      id="partial-event",
      invocation_id="partial-invocation",
      author="user",
      partial=True,
      content=types.Content(
          role="user", parts=[types.Part.from_text(text="partial")]
      ),
  )
  await service.add_events_to_memory(
      app_name="empty", user_id="alice", events=[partial_event]
  )
  with pytest.raises(ValueError):
    await service.search_memory(app_name="", user_id="alice", query="query")
  with pytest.raises(ValueError):
    await service.search_memory(app_name="empty", user_id="alice", query=" ")


@pytest.mark.asyncio
async def test_memory_client_initialization_is_shared_across_concurrent_calls(
    memory_functional_service,
) -> None:
  """Concurrent first use initializes one Oracle Agent Memory client."""
  service, _ = memory_functional_service
  await asyncio.gather(
      *(
          service.add_memory(
              app_name="concurrent",
              user_id=f"user-{index}",
              memories=[
                  MemoryEntry(
                      content=types.Content(
                          role="user",
                          parts=[types.Part.from_text(text=f"memory {index}")],
                      )
                  )
              ],
          )
          for index in range(2)
      )
  )
  # Confirm both concurrent writes actually landed rather than inspecting
  # the private client handle.
  for index in range(2):
    results = await service.search_memory(
        app_name="concurrent", user_id=f"user-{index}", query=f"memory {index}"
    )
    assert any(f"memory {index}" in _memory_text(m) for m in results.memories)

@pytest.mark.asyncio
async def test_search_memory_with_no_records_returns_empty(
    memory_functional_service,
) -> None:
  """Searching an app/user with no stored memories returns an empty result."""
  service, _ = memory_functional_service
  response = await service.search_memory(
      app_name="never-used-app", user_id="never-used-user", query="anything"
  )
  assert response.memories == []