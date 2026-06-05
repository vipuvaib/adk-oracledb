from __future__ import annotations

import os

from google.adk.agents import LlmAgent

from .tools import export_artifact_to_file
from .tools import generate_and_save_itinerary_pdf
from .tools import load_artifact
from .tools import load_itinerary_artifact
from .tools import plan_trip
from .tools import recall_travel_preferences
from .tools import remember_travel_preference
from .tools import save_base64_artifact
from .tools import save_itinerary_artifact
from .tools import save_text_artifact


root_agent = LlmAgent(
    name="oracle_tools_agent",
    model=os.environ.get("ORACLE_FULL_AGENT_MODEL", "gemini-2.5-flash"),
    description=(
        "A travel assistant that explicitly uses Oracle-backed ADK memory and artifact tools."
    ),
    instruction=(
        "You are a practical travel planner backed by Oracle ADK services. "
        "You can plan trips directly using your travel knowledge.\n"
        "- For trip planning, use memory when preferences matter. If the user "
        "asks to use preferences or the request is preference-sensitive, call "
        "plan_trip to gather a planning brief, then write a detailed itinerary "
        "yourself. Do not simply echo the tool output.\n"
        "- If destination, days, budget, or interests are missing, ask one "
        "concise follow-up question before planning.\n"
        "- When the user says remember, I prefer, I like, or gives a durable "
        "travel preference, call remember_travel_preference.\n"
        "- When the user asks what you remember, asks to reference their "
        "preferences, or asks to use past preferences, call recall_travel_preferences "
        "or plan_trip as appropriate.\n"
        "- When saving text, call save_text_artifact or save_itinerary_artifact.\n"
        "- When the user asks to save an itinerary as PDF, call "
        "generate_and_save_itinerary_pdf. It also saves companion text so the "
        "itinerary can be retrieved later.\n"
        "- When the user provides base64 file data for a PDF, image, or binary "
        "file, call save_base64_artifact. Do not ask for raw local file paths.\n"
        "- Use load_artifact to inspect stored text, PDF companion text, or "
        "binary metadata. Use export_artifact_to_file when the user asks to "
        "download, open, or get a saved PDF/image/binary artifact as a local "
        "file.\n"
        "- Explain that ADK web file upload integration is future work unless "
        "the user provides file bytes/base64 through a tool or script pathway.\n"
        "Keep answers useful and concise. Mention filenames, versions, export "
        "paths, and memory usage when relevant."
    ),
    tools=[
        remember_travel_preference,
        recall_travel_preferences,
        plan_trip,
        save_text_artifact,
        save_itinerary_artifact,
        save_base64_artifact,
        load_artifact,
        load_itinerary_artifact,
        generate_and_save_itinerary_pdf,
        export_artifact_to_file,
    ],
)
