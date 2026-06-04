from __future__ import annotations

from typing import Any
import uuid

from google.adk.memory.memory_entry import MemoryEntry
from google.adk.tools.tool_context import ToolContext
from google.genai import types


def _require_text(value: str, name: str) -> str:
  text = value.strip()
  if not text:
    raise ValueError(f"{name} must not be empty")
  return text


def _normalize_text_filename(filename: str) -> str:
  filename = _require_text(filename, "filename")
  if not filename.lower().endswith(".txt"):
    filename = f"{filename}.txt"
  return filename


def _memory_entry_text(memory: MemoryEntry) -> str:
  if not memory.content or not memory.content.parts:
    return ""
  return "\n".join(
      part.text for part in memory.content.parts if getattr(part, "text", None)
  )


def _metadata_for_tool(memory: MemoryEntry) -> dict[str, Any]:
  metadata = memory.custom_metadata or {}
  return {
      str(key): value
      for key, value in metadata.items()
      if isinstance(value, (str, int, float, bool)) or value is None
  }


async def remember_travel_preference(
    preference: str,
    tool_context: ToolContext,
) -> dict[str, str]:
  """Stores a durable travel preference in the configured memory service."""
  preference = _require_text(preference, "preference")
  memory_id = f"travel-preference-{uuid.uuid4().hex}"
  memory_text = f"User travel preference: {preference}"
  memory = MemoryEntry(
      id=memory_id,
      content=types.Content(
          role="user",
          parts=[types.Part.from_text(text=memory_text)],
      ),
      custom_metadata={
          "source": "oracle_tools_agent",
          "kind": "travel_preference",
      },
  )

  await tool_context.add_memory(
      memories=[memory],
      custom_metadata={
          "source": "oracle_tools_agent",
          "tool": "remember_travel_preference",
      },
  )

  return {
      "status": "stored",
      "memory_id": memory_id,
      "preference": preference,
  }


async def recall_travel_preferences(
    query: str,
    tool_context: ToolContext,
) -> dict[str, object]:
  """Searches durable travel preferences in the configured memory service."""
  query = _require_text(query, "query")
  response = await tool_context.search_memory(query)
  memories = [
      {
          "id": memory.id,
          "text": _memory_entry_text(memory),
          "metadata": _metadata_for_tool(memory),
      }
      for memory in response.memories
  ]
  return {
      "query": query,
      "count": len(memories),
      "memories": memories,
  }


async def save_itinerary_artifact(
    filename: str,
    itinerary: str,
    tool_context: ToolContext,
) -> dict[str, object]:
  """Saves a text itinerary as an Oracle-backed ADK artifact."""
  filename = _normalize_text_filename(filename)
  itinerary = _require_text(itinerary, "itinerary")
  version = await tool_context.save_artifact(
      filename,
      types.Part.from_text(text=itinerary),
      custom_metadata={
          "source": "oracle_tools_agent",
          "kind": "itinerary",
      },
  )
  return {
      "status": "saved",
      "filename": filename,
      "version": version,
  }


async def load_itinerary_artifact(
    filename: str,
    tool_context: ToolContext,
) -> dict[str, object]:
  """Loads a saved text itinerary artifact."""
  filename = _normalize_text_filename(filename)
  artifact = await tool_context.load_artifact(filename)
  if artifact is None:
    return {
        "status": "not_found",
        "filename": filename,
        "text": "",
    }
  text = artifact.text
  if text is None and artifact.inline_data and artifact.inline_data.data:
    data = artifact.inline_data.data
    if isinstance(data, str):
      text = data
    else:
      text = data.decode("utf-8", errors="replace")
  return {
      "status": "loaded",
      "filename": filename,
      "text": text or "",
  }
