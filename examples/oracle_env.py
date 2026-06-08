from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _env_path(start_file: str | Path) -> Path | None:
  start = Path(start_file).resolve()
  current = start if start.is_dir() else start.parent
  for directory in (current, *current.parents):
    candidate = directory / ".env"
    if candidate.is_file():
      return candidate
  return None


def _unquote_env_value(value: str) -> str:
  value = value.strip()
  if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
    return value[1:-1]
  return value


def load_repo_env(start_file: str | Path) -> None:
  """Loads the nearest repo .env into os.environ without printing values."""
  path = _env_path(start_file)
  if path is None:
    return

  for raw_line in path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
      continue
    if line.startswith("export "):
      line = line[len("export ") :].lstrip()
    if "=" not in line:
      continue
    key, value = line.split("=", 1)
    key = key.strip()
    if not key:
      continue
    os.environ.setdefault(key, _unquote_env_value(value))


def first_env(*names: str, default: str | None = None) -> str | None:
  for name in names:
    value = os.environ.get(name)
    if value:
      return value
  return default


def require_env(*names: str) -> str:
  value = first_env(*names)
  if value is not None:
    return value
  joined = " or ".join(names)
  raise SystemExit(f"Missing required environment variable: {joined}")


def configure_genai_provider_env() -> None:
  """Maps shared GENAI_* settings to common LiteLLM/OpenAI env names."""
  provider = first_env("GENAI_PROVIDER")
  endpoint = first_env("GENAI_ENDPOINT")
  api_key = first_env("GENAI_API_KEY")

  if api_key:
    os.environ.setdefault("OPENAI_API_KEY", api_key)
    os.environ.setdefault("LITELLM_API_KEY", api_key)
    if provider and provider.lower() == "oci":
      os.environ.setdefault("OCI_API_KEY", api_key)

  if endpoint:
    os.environ.setdefault("OPENAI_API_BASE", endpoint)
    os.environ.setdefault("OPENAI_BASE_URL", endpoint)
    os.environ.setdefault("LITELLM_API_BASE", endpoint)
    if provider and provider.lower() == "oci":
      os.environ.setdefault("OCI_API_BASE", endpoint)


def agent_model_from_env() -> Any:
  """Returns an ADK model object/string from GENAI_MODEL."""
  configure_genai_provider_env()
  model = require_env("GENAI_MODEL")

  endpoint = first_env("GENAI_ENDPOINT")
  api_key = first_env("GENAI_API_KEY")
  provider_style = "/" in model
  if not provider_style:
    return model

  from google.adk.models.lite_llm import LiteLlm

  kwargs: dict[str, str] = {}
  if endpoint:
    kwargs["api_base"] = endpoint
  if api_key:
    kwargs["api_key"] = api_key
  return LiteLlm(model=model, **kwargs)


def oracle_dsn_from_env() -> str:
  return require_env("ORACLE_AI_DB_DSN")


def oracle_user_from_env() -> str:
  return require_env("ORACLE_AI_DB_USER")


def oracle_password_from_env() -> str:
  return require_env("ORACLE_AI_DB_PASSWORD")
