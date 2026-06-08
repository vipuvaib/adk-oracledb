from __future__ import annotations

from pathlib import Path
import sys

from google.adk.agents import LlmAgent


EXAMPLES_DIR = Path(__file__).resolve().parent.parent
if str(EXAMPLES_DIR) not in sys.path:
  sys.path.insert(0, str(EXAMPLES_DIR))

from oracle_env import agent_model_from_env
from oracle_env import load_repo_env


load_repo_env(__file__)

root_agent = LlmAgent(
    name="full_agent_oracle",
    model=agent_model_from_env(),
    description="A small travel preference assistant backed by Oracle services.",
    instruction=(
        "You are a concise travel preference assistant. Remember durable user "
        "travel preferences when the configured memory service is available, "
        "and keep answers practical and brief."
    ),
)
