from __future__ import annotations

import os

from google.adk.agents import LlmAgent

from .tools import load_itinerary_artifact
from .tools import recall_travel_preferences
from .tools import remember_travel_preference
from .tools import save_itinerary_artifact


root_agent = LlmAgent(
    name="oracle_tools_agent",
    model=os.environ.get("ORACLE_FULL_AGENT_MODEL", "gemini-2.5-flash"),
    description=(
        "A travel assistant that explicitly uses Oracle-backed ADK memory and artifact tools."
    ),
    instruction=(
        "You are a concise travel preference assistant.\n"
        "- When the user says remember, I prefer, I like, or gives a durable "
        "travel preference, call remember_travel_preference.\n"
        "- When the user asks what you remember, asks to reference their "
        "preferences, or asks to use past preferences, call "
        "recall_travel_preferences.\n"
        "- When the user asks to save an itinerary, call "
        "save_itinerary_artifact.\n"
        "- When the user asks to retrieve or load a saved itinerary, call "
        "load_itinerary_artifact.\n"
        "Keep answers brief and mention the filename or memory result when "
        "that helps the user."
    ),
    tools=[
        remember_travel_preference,
        recall_travel_preferences,
        save_itinerary_artifact,
        load_itinerary_artifact,
    ],
)
