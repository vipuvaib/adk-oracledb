from __future__ import annotations

import base64
import binascii
import html
import io
from pathlib import Path
from typing import Any
import uuid

from google.adk.memory.memory_entry import MemoryEntry
from google.adk.tools.tool_context import ToolContext
from google.genai import types

_EXPORTS_DIR = Path(__file__).resolve().parent / "exports"
MAX_PDF_SOURCE_CHARS = 80_000


def _require_text(value: str, name: str) -> str:
  text = value.strip()
  if not text:
    raise ValueError(f"{name} must not be empty")
  return text


def _require_text_preserve(value: str, name: str) -> str:
  if not value.strip():
    raise ValueError(f"{name} must not be empty")
  return value


def _require_positive_int(value: int, name: str) -> int:
  if value <= 0:
    raise ValueError(f"{name} must be greater than 0")
  return value


def _is_user_scoped(filename: str) -> bool:
  return filename.startswith("user:")


def _artifact_scope_from_filename(filename: str) -> str:
  return "user" if _is_user_scoped(filename) else "session"


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


def _blob_data_to_bytes(data: bytes | str | None) -> bytes:
  if data is None:
    return b""
  if isinstance(data, bytes):
    return data
  try:
    return base64.b64decode(data, validate=True)
  except (binascii.Error, ValueError):
    return data.encode("utf-8")


def _pdf_error_result(
    *,
    filename: str,
    companion_filename: str,
    message: str,
) -> dict[str, object]:
  return {
      "status": "error",
      "filename": filename,
      "requested_filename": filename,
      "resolved_filename": filename,
      "scope": _artifact_scope_from_filename(filename),
      "pdf_filename": filename,
      "companion_text_filename": companion_filename,
      "mime_type": "application/pdf",
      "size": 0,
      "message": message,
  }


def _pdf_paragraph_text(text: str) -> str:
  return html.escape(text.replace("\t", "    "), quote=False)


def _reportlab_pdf_bytes(title: str, body: str) -> bytes:
  title = _require_text(title, "title")
  body = _require_text(body, "body")
  source_chars = len(title) + len(body)
  if source_chars > MAX_PDF_SOURCE_CHARS:
    raise ValueError(
        "PDF source text is too large for this demo helper "
        f"({source_chars} characters; limit {MAX_PDF_SOURCE_CHARS}). "
        "Save the itinerary as text or shorten it before generating a PDF."
    )

  try:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph
    from reportlab.platypus import SimpleDocTemplate
    from reportlab.platypus import Spacer
  except ImportError as e:
    raise RuntimeError(
        "PDF generation requires ReportLab. Install it with "
        'pip install "adk-oracledb[examples]" or pip install reportlab.'
    ) from e

  buffer = io.BytesIO()
  doc = SimpleDocTemplate(
      buffer,
      pagesize=LETTER,
      rightMargin=54,
      leftMargin=54,
      topMargin=54,
      bottomMargin=54,
  )
  styles = getSampleStyleSheet()
  title_style = ParagraphStyle(
      "ItineraryTitle",
      parent=styles["Title"],
      spaceAfter=14,
  )
  body_style = ParagraphStyle(
      "ItineraryBody",
      parent=styles["BodyText"],
      leading=14,
      spaceAfter=6,
  )
  story = [Paragraph(_pdf_paragraph_text(title), title_style), Spacer(1, 8)]
  for line in body.splitlines():
    if line.strip():
      story.append(Paragraph(_pdf_paragraph_text(line), body_style))
    else:
      story.append(Spacer(1, 8))

  doc.build(story)
  return buffer.getvalue()


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
          "source": "oracle_travel_agent",
          "kind": "travel_preference",
      },
  )

  await tool_context.add_memory(
      memories=[memory],
      custom_metadata={
          "source": "oracle_travel_agent",
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
  text = _require_text_preserve(text, "text")
  version = await tool_context.save_artifact(
      filename,
      types.Part.from_text(text=text),
      custom_metadata={
          "source": "oracle_travel_agent",
          "kind": "text",
      },
  )
  return {
      "status": "saved",
      "filename": filename,
      "requested_filename": filename,
      "resolved_filename": filename,
      "scope": _artifact_scope_from_filename(filename),
      "version": version,
      "type": "text",
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


async def list_saved_artifacts(tool_context: ToolContext) -> dict[str, object]:
  """Lists artifact names available to this session/user context."""
  artifact_names = await tool_context.list_artifacts()
  return {
      "status": "listed",
      "count": len(artifact_names),
      "artifact_names": artifact_names,
  }


async def load_artifact(
    filename: str,
    tool_context: ToolContext,
) -> dict[str, object]:
  """Loads a saved text artifact or PDF artifact metadata by exact name."""
  filename = _require_text(filename, "filename")
  artifact = await tool_context.load_artifact(filename)
  if artifact is None:
    return {
        "status": "not_found",
        "filename": filename,
        "requested_filename": filename,
        "resolved_filename": filename,
        "scope": _artifact_scope_from_filename(filename),
    }

  scope = _artifact_scope_from_filename(filename)
  if artifact.text is not None:
    return {
        "status": "loaded",
        "filename": filename,
        "requested_filename": filename,
        "resolved_filename": filename,
        "scope": scope,
        "kind": "text",
        "mime_type": "text/plain",
        "text": artifact.text,
        "size": len(artifact.text.encode("utf-8")),
    }

  if artifact.inline_data is not None:
    payload = _blob_data_to_bytes(artifact.inline_data.data)
    result: dict[str, object] = {
        "status": "loaded",
        "filename": filename,
        "requested_filename": filename,
        "resolved_filename": filename,
        "scope": scope,
        "kind": "inline_data",
        "mime_type": artifact.inline_data.mime_type,
        "size": len(payload),
        "message": "Artifact contains inline data; use export_artifact_to_file to write it locally.",
    }
    if (
        artifact.inline_data.mime_type == "application/pdf"
        and filename.lower().endswith(".pdf")
    ):
      companion_filename = _companion_text_filename_for_pdf(filename)
      companion = await tool_context.load_artifact(companion_filename)
      if companion is not None and companion.text is not None:
        result["companion_text_filename"] = companion_filename
        result["companion_text"] = companion.text
    return result

  return {
      "status": "loaded",
      "filename": filename,
      "requested_filename": filename,
      "resolved_filename": filename,
      "scope": scope,
      "kind": "unsupported",
      "mime_type": None,
      "size": 0,
  }


async def load_itinerary_artifact(
    filename: str,
    tool_context: ToolContext,
) -> dict[str, object]:
  """Loads a saved text itinerary artifact by exact name."""
  filename = _normalize_text_filename(filename)
  result = await load_artifact(filename=filename, tool_context=tool_context)
  if result.get("status") == "not_found":
    return {
        "status": "not_found",
        "filename": filename,
        "requested_filename": filename,
        "resolved_filename": filename,
        "scope": _artifact_scope_from_filename(filename),
        "text": "",
    }
  if result.get("kind") == "text":
    return {
        "status": "loaded",
        "filename": filename,
        "requested_filename": filename,
        "resolved_filename": filename,
        "scope": _artifact_scope_from_filename(filename),
        "text": str(result.get("text", "")),
    }
  return {
      "status": "loaded",
      "filename": filename,
      "requested_filename": filename,
      "resolved_filename": filename,
      "scope": _artifact_scope_from_filename(filename),
      "kind": result.get("kind", "unsupported"),
      "text": "",
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
  itinerary = _require_text_preserve(itinerary, "itinerary")
  try:
    pdf_bytes = _reportlab_pdf_bytes(title=title, body=itinerary)
  except (RuntimeError, ValueError) as e:
    return _pdf_error_result(
        filename=filename,
        companion_filename=companion_filename,
        message=str(e),
    )
  pdf_version = await tool_context.save_artifact(
      filename,
      types.Part(
          inline_data=types.Blob(
              data=pdf_bytes,
              mime_type="application/pdf",
          )
      ),
      custom_metadata={
          "source": "oracle_travel_agent",
          "kind": "itinerary_pdf",
      },
  )
  companion_version = await tool_context.save_artifact(
      companion_filename,
      types.Part.from_text(text=itinerary),
      custom_metadata={
          "source": "oracle_travel_agent",
          "kind": "itinerary_pdf_companion_text",
          "pdf_filename": filename,
      },
  )
  return {
      "status": "saved",
      "filename": filename,
      "requested_filename": filename,
      "resolved_filename": filename,
      "scope": _artifact_scope_from_filename(filename),
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
  """Exports a saved artifact to the local example exports directory by exact name."""
  filename = _require_text(filename, "filename")
  output_path = _safe_export_path(output_filename)
  artifact = await tool_context.load_artifact(filename)
  if artifact is None:
    return {
        "status": "not_found",
        "source_filename": filename,
        "requested_filename": filename,
        "resolved_filename": filename,
        "scope": _artifact_scope_from_filename(filename),
        "output_path": str(output_path),
        "kind": "not_found",
        "mime_type": None,
        "size": 0,
    }

  scope = _artifact_scope_from_filename(filename)
  if artifact.text is not None:
    payload = artifact.text.encode("utf-8")
    output_path.write_bytes(payload)
    return {
        "status": "exported",
        "source_filename": filename,
        "requested_filename": filename,
        "resolved_filename": filename,
        "scope": scope,
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
        "requested_filename": filename,
        "resolved_filename": filename,
        "scope": scope,
        "output_path": str(output_path),
        "kind": "inline_data",
        "mime_type": artifact.inline_data.mime_type,
        "size": len(payload),
    }

  return {
      "status": "unsupported",
      "source_filename": filename,
      "requested_filename": filename,
      "resolved_filename": filename,
      "scope": scope,
      "output_path": str(output_path),
      "kind": "unsupported",
      "mime_type": None,
      "size": 0,
  }
