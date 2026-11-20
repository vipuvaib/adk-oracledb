"""Live configured-model checks through ADK and Oracle-backed services.

Set the Oracle database and model-provider environment variables before
running these tests with pytest. They make live model-provider calls.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import time
import uuid

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.models.llm_request import LlmRequest
from google.adk.runners import Runner
from google.adk.tools.tool_context import ToolContext
from google.adk.memory.memory_entry import MemoryEntry
from google.genai import types
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples"))
from oracle_env import agent_model_from_env

pytestmark = pytest.mark.oracle


@pytest.fixture
def configured_llm():
  if not os.environ.get("GENAI_MODEL"):
    pytest.skip("GENAI_MODEL must select a live test model")
  return agent_model_from_env()


def _text(content) -> str:
  return "".join(
      part.text for part in (content.parts or [])
      if part.text and not getattr(part, "thought", False)
  ) if content else ""


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True], ids=["complete", "stream"])
async def test_configured_llm_answers_through_adk(configured_llm, record_property, stream):
  request = LlmRequest(
      contents=[types.Content(role="user", parts=[types.Part.from_text(
          text="What is 19 plus 23? Reply with only the decimal integer."
      )])],
      config=types.GenerateContentConfig(temperature=0, max_output_tokens=512),
  )
  responses = []
  started = time.perf_counter()
  first_text = None
  async with asyncio.timeout(120):
    async for response in configured_llm.generate_content_async(request, stream=stream):
      responses.append(response)
      if first_text is None and _text(response.content):
        first_text = time.perf_counter() - started
  record_property("elapsed_seconds", round(time.perf_counter() - started, 3))
  record_property("first_text_seconds", first_text)
  record_property("model", os.environ["GENAI_MODEL"])
  finals = [r for r in responses if not r.partial]
  assert finals, "ADK did not yield a complete response"
  assert "".join(_text(r.content) for r in finals).strip() == "42"
  assert not any(r.error_code for r in responses)


@pytest.mark.asyncio
async def test_configured_embeddings_rank_a_paraphrase(memory_functional_service, record_property):
  service, _ = memory_functional_service
  records = [
      "Maya has a severe peanut allergy. Meals must exclude groundnuts.",
      "Maya's train from Kyoto departs at nine in the morning.",
      "Maya prefers quiet hotels with a view of the mountains.",
  ]
  started = time.perf_counter()
  async with asyncio.timeout(180):
    await service.add_memory(
        app_name="semantic_live", user_id="maya",
        memories=[MemoryEntry(content=types.Content(role="user", parts=[
            types.Part.from_text(text=text)
        ])) for text in records],
    )
    added = time.perf_counter()
    result = await service.search_memory(
        app_name="semantic_live", user_id="maya",
        query="Which ingredient must be avoided to prevent a dangerous reaction?",
    )
  record_property("add_seconds", round(added - started, 3))
  record_property("search_seconds", round(time.perf_counter() - added, 3))
  record_property("model", os.environ["EMBEDDING_MODEL"])
  assert result.memories
  assert "peanut" in _text(result.memories[0].content).lower()


@pytest.mark.asyncio
async def test_llm_uses_memory_tool_and_saves_oracle_artifact(
    configured_llm, oracle_functional_environment, memory_functional_service, record_property,
):
  environment = oracle_functional_environment
  memory, _ = memory_functional_service
  app_name = "oci_live_tools"
  user_id = "maya"
  booking_code = "KYOTO-" + uuid.uuid4().hex[:12].upper()
  await memory.add_memory(
      app_name=app_name, user_id=user_id,
      memories=[MemoryEntry(content=types.Content(role="user", parts=[
          types.Part.from_text(text="Maya's Kyoto hotel booking reference is " + booking_code)
      ]))],
  )

  async def retrieve_reservation(query: str, tool_context: ToolContext) -> dict[str, str]:
    """Retrieve the user's saved reservation and save a booking.txt artifact."""
    result = await tool_context.search_memory(query)
    text = "\n".join(_text(entry.content) for entry in result.memories)
    if not text:
      return {"status": "not_found"}
    version = await tool_context.save_artifact("booking.txt", types.Part.from_text(text=text))
    return {"reservation": text, "artifact_version": str(version)}

  agent = LlmAgent(
      name=app_name, model=configured_llm,
      instruction=(
          "Always call retrieve_reservation to answer reservation questions. "
          "Use its result to return the exact booking reference. "
          "Never invent a reference. Return just the reference after the tool succeeds."
      ),
      generate_content_config=types.GenerateContentConfig(temperature=0, max_output_tokens=1024),
      tools=[retrieve_reservation],
  )
  session = await environment.session_service.create_session(app_name=app_name, user_id=user_id)
  runner = Runner(
      app_name=app_name, agent=agent, session_service=environment.session_service,
      memory_service=memory, artifact_service=environment.artifact_service,
  )
  started = time.perf_counter()
  try:
    async with asyncio.timeout(180):
      events = [event async for event in runner.run_async(
          user_id=user_id, session_id=session.id,
          new_message=types.Content(role="user", parts=[types.Part.from_text(
              text="Find my Kyoto hotel booking reference in my saved reservations."
          )]),
          run_config=RunConfig(max_llm_calls=4),
      )]
  finally:
    await runner.close()
  record_property("elapsed_seconds", round(time.perf_counter() - started, 3))
  calls = [part.function_call for event in events for part in (event.content.parts if event.content else []) if part.function_call]
  assert any(call.name == "retrieve_reservation" for call in calls)
  finals = [event for event in events if event.is_final_response()]
  assert finals and booking_code in _text(finals[-1].content)
  artifact = await environment.artifact_service.load_artifact(
      app_name=app_name, user_id=user_id, session_id=session.id, filename="booking.txt",
  )
  assert artifact is not None and booking_code in artifact.text
  persisted = await environment.session_service.get_session(
      app_name=app_name, user_id=user_id, session_id=session.id,
  )
  assert persisted is not None
  assert any(
      part.function_response and part.function_response.name == "retrieve_reservation"
      for event in persisted.events for part in (event.content.parts if event.content else [])
  )
