from __future__ import annotations

from pathlib import Path
import sys

from google.adk.agents import LlmAgent

EXAMPLES_DIR = Path(__file__).resolve().parent.parent
if str(EXAMPLES_DIR) not in sys.path:
  sys.path.insert(0, str(EXAMPLES_DIR))

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
    name="oracle_tools_agent",
    model=agent_model_from_env(),
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
        "- When the user asks what files or artifacts exist, call "
        "list_saved_artifacts.\n"
        "- Use load_artifact or load_itinerary_artifact for saved text "
        "artifacts, generated PDF metadata, and generated PDF companion text.\n"
        "- Use export_artifact_to_file when the user asks to download, open, "
        "or get a saved generated PDF or text artifact as a local file.\n"
        "- In ADK artifacts, the prefix user: is a namespace prefix, not a "
        "normal filename character. Never replace user: with user_. Never "
        "sanitize or remove the colon in user:.\n"
        "- If the user asks to save, load, list, or export an artifact whose "
        "name starts with user:, pass that exact prefix to the tool. Example: "
        "user says: save this as user:ujjwal_trip; tool filename argument "
        "must be: user:ujjwal_trip; final saved filename may become: "
        "user:ujjwal_trip.txt.\n"
        "- If a user-scoped itinerary filename has no extension, the tool may "
        "append .txt while preserving the prefix: user:ujjwal_trip -> "
        "user:ujjwal_trip.txt. Always tell the user the actual artifact "
        "filename returned by the tool.\n"
        "- This example intentionally demonstrates text artifacts, generated "
        "PDF artifacts, listing, loading, and local export.\n"
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
