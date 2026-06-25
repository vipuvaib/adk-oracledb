from __future__ import annotations

from pathlib import Path
import sys

from google.adk.agents import LlmAgent

_EXAMPLES_DIR = Path(__file__).resolve().parents[1]
if str(_EXAMPLES_DIR) not in sys.path:
  sys.path.insert(0, str(_EXAMPLES_DIR))

from oracle_env import agent_model_from_env
from oracle_env import load_repo_env

from .tools import export_artifact_to_file
from .tools import generate_and_save_itinerary_pdf
from .tools import list_saved_artifacts
from .tools import load_artifact
from .tools import load_itinerary_artifact
from .tools import plan_trip
from .tools import recall_travel_preferences
from .tools import remember_travel_preference
from .tools import save_itinerary_artifact
from .tools import save_text_artifact


load_repo_env(__file__)

root_agent = LlmAgent(
    name="oracle_travel_agent",
    model=agent_model_from_env(),
    description=(
        "A travel planning assistant that uses Oracle-backed ADK memory and artifacts."
    ),
    instruction=(
        "You are a practical travel planner backed by Oracle ADK services. "
        "Use the available tools intentionally instead of only answering from "
        "the current prompt.\n"
        "- When the user gives a travel preference, call remember_travel_preference.\n"
        "- Before planning, call recall_travel_preferences or plan_trip so stored "
        "preferences can influence the answer.\n"
        "- Use plan_trip to create a planning brief, then write the final itinerary "
        "with day-by-day morning, afternoon, and evening details.\n"
        "- When the user asks to save text, call save_text_artifact.\n"
        "- When the user asks to save an itinerary, call save_itinerary_artifact.\n"
        "- When the user asks to save an itinerary as PDF, call "
        "generate_and_save_itinerary_pdf. It also saves companion text so the "
        "itinerary can be retrieved later.\n"
        "- When saving an itinerary as a text artifact or generating a PDF "
        "artifact from an itinerary, preserve the full itinerary text. Do not "
        "summarize, shorten, rewrite, or compress a previously generated "
        "itinerary before passing it to the artifact tools.\n"
        "- If the user says \"save that itinerary\" or \"generate a PDF from "
        "that itinerary,\" use the complete itinerary from the conversation as "
        "the artifact content. If the full itinerary text is not available, "
        "regenerate the full itinerary and then save or generate the PDF from "
        "that full text.\n"
        "- When the user asks what files or artifacts exist, call list_saved_artifacts.\n"
        "- Use load_artifact or load_itinerary_artifact to inspect saved text "
        "and PDF companion text.\n"
        "- Use export_artifact_to_file when the user asks to download, open, or "
        "get a saved artifact as a local file.\n"
        "- Respect ADK artifact scoping: plain filenames are session scoped, "
        "and filenames beginning with user: are user scoped.\n"
        "Keep answers useful and concise. Mention filenames, versions, export "
        "paths, and memory usage when relevant."
    ),
    tools=[
        remember_travel_preference,
        recall_travel_preferences,
        plan_trip,
        list_saved_artifacts,
        save_text_artifact,
        save_itinerary_artifact,
        load_artifact,
        load_itinerary_artifact,
        generate_and_save_itinerary_pdf,
        export_artifact_to_file,
    ],
)
