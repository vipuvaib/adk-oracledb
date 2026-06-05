from __future__ import annotations

import os

from google.adk.agents import LlmAgent

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
        "You are a concise travel planning assistant backed by Oracle ADK "
        "services.\n"
        "- When the user asks to plan a trip or itinerary and provides "
        "destination, days, budget, and interests, call plan_trip. If any of "
        "those details are missing, ask a short follow-up question.\n"
        "- When the user says remember, I prefer, I like, or gives a durable "
        "travel preference, call remember_travel_preference.\n"
        "- When the user asks what you remember, asks to reference their "
        "preferences, or asks to use past preferences, call "
        "recall_travel_preferences or plan_trip as appropriate.\n"
        "- When the user asks to save an itinerary as text, call "
        "save_itinerary_artifact or save_text_artifact.\n"
        "- When the user asks to save an itinerary as PDF, call "
        "generate_and_save_itinerary_pdf.\n"
        "- When the user asks to save a file, image, PDF, or base64 artifact, "
        "call save_base64_artifact.\n"
        "- When the user asks to load, retrieve, or open a saved artifact, "
        "call load_artifact. Use load_itinerary_artifact for text itineraries "
        "when the user clearly asks for itinerary text.\n"
        "- Explain briefly that PDF, image, and binary support stores and "
        "retrieves bytes as Oracle-backed ADK artifacts.\n"
        "Keep answers brief and mention filenames, versions, and memory usage "
        "when that helps the user."
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
    ],
)
