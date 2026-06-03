from __future__ import annotations

import os

from google.adk.agents import LlmAgent


root_agent = LlmAgent(
    name="full_agent_oracle",
    model=os.environ.get("ORACLE_FULL_AGENT_MODEL", "gemini-2.5-flash"),
    description="A small travel preference assistant backed by Oracle services.",
    instruction=(
        "You are a concise travel preference assistant. Remember durable user "
        "travel preferences when the configured memory service is available, "
        "and keep answers practical and brief."
    ),
)
