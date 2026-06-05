from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Any
import uuid

from google.adk.memory.memory_entry import MemoryEntry
from google.adk.tools.tool_context import ToolContext
from google.genai import types

_MAX_INLINE_BINARY_RESPONSE_BYTES = 200_000
_EXPORTS_DIR = Path(__file__).resolve().parent / "exports"


def _require_text(value: str, name: str) -> str:
  text = value.strip()
  if not text:
    raise ValueError(f"{name} must not be empty")
  return text


def _require_positive_int(value: int, name: str) -> int:
  if value <= 0:
    raise ValueError(f"{name} must be greater than 0")
  return value


def _normalize_text_filename(filename: str) -> str:
  filename = _require_text(filename, "filename")
  if not filename.lower().endswith(".txt"):
    filename = f"{filename}.txt"
  return filename


def _ensure_pdf_filename(filename: str) -> str:
  filename = _require_text(filename, "filename")
  if not filename.lower().endswith(".pdf"):
    filename = f"{filename}.pdf"
  return filename


def _companion_text_filename_for_pdf(filename: str) -> str:
  filename = _ensure_pdf_filename(filename)
  return f"{filename[:-4]}.txt"


def _safe_export_path(output_filename: str) -> Path:
  output_filename = _require_text(output_filename, "output_filename")
  requested = Path(output_filename)
  if requested.is_absolute() or ".." in requested.parts:
    raise ValueError("output_filename must be a safe relative filename")
  safe_name = requested.name
  if not safe_name or safe_name in {".", ".."}:
    raise ValueError("output_filename must include a filename")
  _EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
  return _EXPORTS_DIR / safe_name


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


def _memory_snippets(memories: list[MemoryEntry], *, limit: int = 3) -> list[str]:
  snippets = []
  for memory in memories:
    text = _memory_entry_text(memory).strip()
    if text:
      snippets.append(text)
    if len(snippets) >= limit:
      break
  return snippets


def _decode_base64(base64_data: str) -> bytes:
  base64_data = _require_text(base64_data, "base64_data")
  try:
    return base64.b64decode(base64_data, validate=True)
  except (binascii.Error, ValueError) as exc:
    raise ValueError("base64_data must be valid base64") from exc


def _blob_data_to_bytes(data: bytes | str | None) -> bytes:
  if data is None:
    return b""
  if isinstance(data, bytes):
    return data
  try:
    return base64.b64decode(data, validate=True)
  except (binascii.Error, ValueError):
    return data.encode("utf-8")


def _pdf_escape(text: str) -> str:
  return (
      text.replace("\\", "\\\\")
      .replace("(", "\\(")
      .replace(")", "\\)")
      .replace("\r", " ")
  )


def _simple_pdf_bytes(title: str, body: str) -> bytes:
  title = _require_text(title, "title")
  body = _require_text(body, "body")
  lines = [title, ""] + body.splitlines()
  content_lines = ["BT", "/F1 18 Tf", "72 750 Td"]
  for index, line in enumerate(lines[:34]):
    if index == 1:
      content_lines.extend(["/F1 11 Tf", "0 -28 Td"])
      continue
    if index > 0:
      content_lines.append("0 -16 Td")
    content_lines.append(f"({_pdf_escape(line[:96])}) Tj")
  content_lines.append("ET")
  stream = "\n".join(content_lines).encode("latin-1", errors="replace")

  objects = [
      b"<< /Type /Catalog /Pages 2 0 R >>",
      b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
      (
          b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
          b"/Resources << /Font << /F1 4 0 R >> >> "
          b"/Contents 5 0 R >>"
      ),
      b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
      (
          f"<< /Length {len(stream)} >>\n".encode("ascii")
          + b"stream\n"
          + stream
          + b"\nendstream"
      ),
  ]

  pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
  offsets = [0]
  for index, obj in enumerate(objects, start=1):
    offsets.append(len(pdf))
    pdf.extend(f"{index} 0 obj\n".encode("ascii"))
    pdf.extend(obj)
    pdf.extend(b"\nendobj\n")
  xref_offset = len(pdf)
  pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
  pdf.extend(b"0000000000 65535 f \n")
  for offset in offsets[1:]:
    pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
  pdf.extend(
      (
          f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
          f"startxref\n{xref_offset}\n%%EOF\n"
      ).encode("ascii")
  )
  return bytes(pdf)


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


async def plan_trip(
    destination: str,
    days: int,
    budget: str,
    interests: str,
    tool_context: ToolContext,
) -> dict[str, object]:
  """Builds a planning brief using relevant stored travel preferences."""
  destination = _require_text(destination, "destination")
  days = _require_positive_int(days, "days")
  budget = _require_text(budget, "budget")
  interests = _require_text(interests, "interests")
  query = f"{destination} {budget} {interests} travel preferences"
  memory_response = await tool_context.search_memory(query)
  snippets = _memory_snippets(memory_response.memories)
  preference_block = (
      "\n".join(f"- {snippet}" for snippet in snippets)
      if snippets
      else "- No stored travel preferences found for this query."
  )
  structure = [
      "Arrival, recovery, and orientation",
      "Signature culture/history day",
      "Primary nature or adventure day",
      "Local food, markets, and neighborhoods",
      "Flexible buffer for weather, transit, or energy level",
      "Departure with one low-effort highlight",
  ]
  planning_brief = (
      f"Planning brief for a rich {days}-day {budget} trip to {destination}\n"
      f"Traveler interests: {interests}\n\n"
      "Memory context to consider, not blindly copy:\n"
      f"{preference_block}\n\n"
      "Suggested itinerary structure:\n"
      + "\n".join(f"- {item}" for item in structure)
      + "\n\n"
      "Write the final itinerary using current travel knowledge. Include "
      "morning, afternoon, and evening blocks for each day; practical transit "
      "and pacing notes; food ideas; budget-sensitive choices; and where the "
      "stored preferences influenced the plan. Do not treat memory as the only "
      "source of travel knowledge."
  )
  return {
      "destination": destination,
      "days": days,
      "budget": budget,
      "interests": interests,
      "used_memory_count": len(snippets),
      "recalled_preferences": snippets,
      "planning_brief": planning_brief,
      "itinerary": planning_brief,
  }


async def save_text_artifact(
    filename: str,
    text: str,
    tool_context: ToolContext,
) -> dict[str, object]:
  """Saves arbitrary text as an Oracle-backed ADK artifact."""
  filename = _normalize_text_filename(filename)
  text = _require_text(text, "text")
  version = await tool_context.save_artifact(
      filename,
      types.Part.from_text(text=text),
      custom_metadata={
          "source": "oracle_tools_agent",
          "kind": "text",
      },
  )
  return {
      "status": "saved",
      "filename": filename,
      "version": version,
      "mime_type": "text/plain",
      "size": len(text.encode("utf-8")),
  }


async def save_itinerary_artifact(
    filename: str,
    itinerary: str,
    tool_context: ToolContext,
) -> dict[str, object]:
  """Saves a text itinerary as an Oracle-backed ADK artifact."""
  result = await save_text_artifact(
      filename=filename,
      text=itinerary,
      tool_context=tool_context,
  )
  result["kind"] = "itinerary"
  return result


async def save_base64_artifact(
    filename: str,
    base64_data: str,
    mime_type: str,
    tool_context: ToolContext,
) -> dict[str, object]:
  """Saves binary bytes from base64 as an Oracle-backed ADK artifact."""
  filename = _require_text(filename, "filename")
  mime_type = _require_text(mime_type, "mime_type")
  payload = _decode_base64(base64_data)
  version = await tool_context.save_artifact(
      filename,
      types.Part(
          inline_data=types.Blob(
              data=payload,
              mime_type=mime_type,
          )
      ),
      custom_metadata={
          "source": "oracle_tools_agent",
          "kind": "binary",
          "mime_type": mime_type,
      },
  )
  return {
      "status": "saved",
      "filename": filename,
      "version": version,
      "mime_type": mime_type,
      "size": len(payload),
  }


async def load_artifact(
    filename: str,
    tool_context: ToolContext,
) -> dict[str, object]:
  """Loads any saved text or inline_data artifact."""
  filename = _require_text(filename, "filename")
  artifact = await tool_context.load_artifact(filename)
  if artifact is None:
    return {
        "status": "not_found",
        "filename": filename,
    }
  if artifact.text is not None:
    return {
        "status": "loaded",
        "filename": filename,
        "kind": "text",
        "text": artifact.text,
        "size": len(artifact.text.encode("utf-8")),
    }
  if artifact.inline_data is not None:
    payload = _blob_data_to_bytes(artifact.inline_data.data)
    result: dict[str, object] = {
        "status": "loaded",
        "filename": filename,
        "kind": "inline_data",
        "mime_type": artifact.inline_data.mime_type,
        "size": len(payload),
        "content_inlined": len(payload) <= _MAX_INLINE_BINARY_RESPONSE_BYTES,
    }
    if len(payload) <= _MAX_INLINE_BINARY_RESPONSE_BYTES:
      result["base64_data"] = base64.b64encode(payload).decode("ascii")
    else:
      result["message"] = "Artifact is too large to inline in the response."
    if artifact.inline_data.mime_type == "application/pdf" and filename.lower().endswith(".pdf"):
      companion_filename = _companion_text_filename_for_pdf(filename)
      companion = await tool_context.load_artifact(companion_filename)
      if companion is not None and companion.text is not None:
        result["companion_text_filename"] = companion_filename
        result["companion_text"] = companion.text
    return result
  return {
      "status": "loaded",
      "filename": filename,
      "kind": "unsupported",
  }


async def load_itinerary_artifact(
    filename: str,
    tool_context: ToolContext,
) -> dict[str, object]:
  """Loads a saved text itinerary artifact."""
  filename = _normalize_text_filename(filename)
  result = await load_artifact(filename=filename, tool_context=tool_context)
  if result.get("status") == "not_found":
    return {
        "status": "not_found",
        "filename": filename,
        "text": "",
    }
  if result.get("kind") == "text":
    return {
        "status": "loaded",
        "filename": filename,
        "text": str(result.get("text", "")),
    }
  text = ""
  base64_data = result.get("base64_data")
  if isinstance(base64_data, str):
    text = _decode_base64(base64_data).decode("utf-8", errors="replace")
  return {
      "status": "loaded",
      "filename": filename,
      "text": text,
  }


async def generate_and_save_itinerary_pdf(
    filename: str,
    title: str,
    itinerary: str,
    tool_context: ToolContext,
) -> dict[str, object]:
  """Generates a simple PDF from itinerary text and saves it as an artifact."""
  filename = _ensure_pdf_filename(filename)
  companion_filename = _companion_text_filename_for_pdf(filename)
  itinerary = _require_text(itinerary, "itinerary")
  pdf_bytes = _simple_pdf_bytes(title=title, body=itinerary)
  pdf_version = await tool_context.save_artifact(
      filename,
      types.Part(
          inline_data=types.Blob(
              data=pdf_bytes,
              mime_type="application/pdf",
          )
      ),
      custom_metadata={
          "source": "oracle_tools_agent",
          "kind": "itinerary_pdf",
      },
  )
  companion_version = await tool_context.save_artifact(
      companion_filename,
      types.Part.from_text(text=itinerary),
      custom_metadata={
          "source": "oracle_tools_agent",
          "kind": "itinerary_pdf_companion_text",
          "pdf_filename": filename,
      },
  )
  return {
      "status": "saved",
      "filename": filename,
      "version": pdf_version,
      "pdf_filename": filename,
      "pdf_version": pdf_version,
      "companion_text_filename": companion_filename,
      "companion_text_version": companion_version,
      "mime_type": "application/pdf",
      "size": len(pdf_bytes),
  }


async def export_artifact_to_file(
    filename: str,
    output_filename: str,
    tool_context: ToolContext,
) -> dict[str, object]:
  """Exports a saved artifact to the local example exports directory."""
  filename = _require_text(filename, "filename")
  output_path = _safe_export_path(output_filename)
  artifact = await tool_context.load_artifact(filename)
  if artifact is None:
    return {
        "status": "not_found",
        "source_filename": filename,
        "output_path": str(output_path),
    }

  if artifact.text is not None:
    payload = artifact.text.encode("utf-8")
    output_path.write_bytes(payload)
    return {
        "status": "exported",
        "source_filename": filename,
        "output_path": str(output_path),
        "kind": "text",
        "mime_type": "text/plain",
        "size": len(payload),
    }

  if artifact.inline_data is not None:
    payload = _blob_data_to_bytes(artifact.inline_data.data)
    output_path.write_bytes(payload)
    return {
        "status": "exported",
        "source_filename": filename,
        "output_path": str(output_path),
        "kind": "inline_data",
        "mime_type": artifact.inline_data.mime_type,
        "size": len(payload),
    }

  return {
      "status": "unsupported",
      "source_filename": filename,
      "output_path": str(output_path),
      "kind": "unsupported",
      "size": 0,
  }
