from __future__ import annotations

import os
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import unquote
from urllib.parse import urlsplit

from adk_oracledb.artifacts import OracleArtifactService
from adk_oracledb.artifacts import OracleArtifactServiceConfig
from adk_oracledb.memory import OracleMemoryService
from adk_oracledb.memory import OracleMemoryServiceConfig
from adk_oracledb.sessions import OracleSessionService
from adk_oracledb.sessions import OracleSessionServiceConfig
from google.adk.cli.service_registry import get_service_registry


_ORACLE_SCHEME = "oracle"


def _query_param(
    query: dict[str, list[str]],
    name: str,
    default: str | None = None,
) -> str | None:
  values = query.get(name)
  if not values:
    return default
  value = values[-1].strip()
  return value if value else default


def _first_env(*names: str, default: str | None = None) -> str | None:
  for name in names:
    value = os.environ.get(name)
    if value:
      return value
  return default


def _query_param_or_env(
    query: dict[str, list[str]],
    name: str,
    *env_names: str,
    default: str | None = None,
) -> str | None:
  return _query_param(query, name) or _first_env(*env_names, default=default)


def _parse_bool(
    query: dict[str, list[str]],
    name: str,
    default: bool,
) -> bool:
  value = _query_param(query, name)
  if value is None:
    return default

  normalized = value.lower()
  if normalized in {"true", "1", "yes", "y", "on"}:
    return True
  if normalized in {"false", "0", "no", "n", "off"}:
    return False
  raise ValueError(f"{name} must be a boolean value")


def _parse_int(
    query: dict[str, list[str]],
    name: str,
    default: int | None = None,
) -> int | None:
  value = _query_param(query, name)
  if value is None:
    return default
  try:
    parsed = int(value)
  except ValueError as e:
    raise ValueError(f"{name} must be an integer") from e
  if parsed < 1:
    raise ValueError(f"{name} must be a positive integer")
  return parsed


def _parse_csv(
    query: dict[str, list[str]],
    name: str,
) -> list[str] | None:
  value = _query_param(query, name)
  if value is None:
    return None
  return [item.strip() for item in value.split(",") if item.strip()]


def _build_dsn(*, host: str, port: int, service_name: str) -> str:
  return f"{host}:{port}/{service_name}"


def _parse_oracle_uri(uri: str) -> dict[str, Any]:
  parsed = urlsplit(uri)
  if parsed.scheme != _ORACLE_SCHEME:
    raise ValueError("oracle service URI must use oracle:// scheme")

  query = parse_qs(parsed.query, keep_blank_values=True)

  username = (
      unquote(parsed.username)
      if parsed.username
      else _first_env("ORACLE_AI_DB_USER")
  )
  if not username:
    raise ValueError("oracle service URI requires username or ORACLE_AI_DB_USER")

  password = (
      unquote(parsed.password)
      if parsed.password
      else _first_env("ORACLE_AI_DB_PASSWORD")
  )
  if not password:
    raise ValueError(
        "oracle service URI requires password or ORACLE_AI_DB_PASSWORD"
    )

  host = parsed.hostname
  service_name = parsed.path.strip("/")
  if not service_name:
    service_name = _query_param(query, "service_name") or ""

  dsn = _first_env("ORACLE_AI_DB_DSN")
  port: int | None = None
  if host and service_name:
    try:
      port = parsed.port or 1521
    except ValueError as e:
      raise ValueError("oracle service URI port must be an integer") from e
    service_name = unquote(service_name)
    dsn = _build_dsn(host=host, port=port, service_name=service_name)
  elif not host and not service_name and dsn:
    service_name = ""
  else:
    raise ValueError(
        "oracle service URI requires host/service_name or "
        "ORACLE_AI_DB_DSN"
    )

  return {
      "user": username,
      "password": password,
      "host": host,
      "port": port,
      "service_name": service_name,
      "dsn": dsn,
      "query": query,
  }


def _pool_kwargs(parsed: dict[str, Any]) -> dict[str, int]:
  query = parsed["query"]
  kwargs: dict[str, int] = {}
  pool_min = _parse_int(query, "pool_min")
  if pool_min is not None:
    kwargs["pool_min"] = pool_min
  pool_max = _parse_int(query, "pool_max")
  if pool_max is not None:
    kwargs["pool_max"] = pool_max
  return kwargs


def _session_config_from_uri(uri: str) -> OracleSessionServiceConfig:
  parsed = _parse_oracle_uri(uri)
  query = parsed["query"]
  table_prefix = _query_param_or_env(
      query,
      "table_prefix",
      "ORACLE_SESSION_TABLE_PREFIX",
      default="ADK",
  )
  return OracleSessionServiceConfig(
      user=parsed["user"],
      password=parsed["password"],
      dsn=parsed["dsn"],
      table_prefix=table_prefix or "ADK",
      auto_create_tables=_parse_bool(query, "auto_create_tables", True),
      **_pool_kwargs(parsed),
  )


def _artifact_config_from_uri(uri: str) -> OracleArtifactServiceConfig:
  parsed = _parse_oracle_uri(uri)
  query = parsed["query"]
  table_prefix = (
      _query_param(query, "artifact_table_prefix")
      or _query_param(query, "table_prefix")
      or _first_env("ORACLE_ARTIFACT_TABLE_PREFIX")
      or "ADK"
  )
  return OracleArtifactServiceConfig(
      user=parsed["user"],
      password=parsed["password"],
      dsn=parsed["dsn"],
      table_prefix=table_prefix,
      auto_create_tables=_parse_bool(query, "auto_create_tables", True),
      **_pool_kwargs(parsed),
  )


def _memory_config_from_uri(uri: str) -> OracleMemoryServiceConfig:
  parsed = _parse_oracle_uri(uri)
  query = parsed["query"]
  embedder_model = _query_param_or_env(
      query,
      "embedder_model",
      "EMBEDDING_MODEL",
  )
  if not embedder_model:
    raise ValueError(
        "oracle:// memory service requires embedder_model query parameter "
        "or EMBEDDING_MODEL"
    )

  table_name_prefix = (
      _query_param(query, "memory_table_prefix")
      or _query_param(query, "table_prefix")
      or _first_env("ORACLE_MEMORY_TABLE_PREFIX")
      or "ADK_MEMORY"
  )
  search_top_k = _parse_int(query, "search_top_k")

  kwargs: dict[str, Any] = {
      "user": parsed["user"],
      "password": parsed["password"],
      "dsn": parsed["dsn"],
      "table_name_prefix": table_name_prefix,
      "schema_policy": _query_param(
          query, "schema_policy", "create_if_necessary"
      )
      or "create_if_necessary",
      "embedder_model": embedder_model,
      "embedder_api_base": _query_param_or_env(
          query,
          "embedder_api_base",
          "EMBEDDING_ENDPOINT",
      ),
      "embedder_api_key": _query_param_or_env(
          query,
          "embedder_api_key",
          "EMBEDDING_API_KEY",
      ),
      "llm_model": _query_param_or_env(
          query,
          "llm_model",
          "GENAI_MODEL",
      ),
      "llm_api_base": _query_param_or_env(
          query,
          "llm_api_base",
          "GENAI_ENDPOINT",
      ),
      "llm_api_key": _query_param_or_env(
          query,
          "llm_api_key",
          "GENAI_API_KEY",
      ),
      "extract_memories": _parse_bool(query, "extract_memories", False),
      "record_types": _parse_csv(query, "record_types"),
      **_pool_kwargs(parsed),
  }
  if search_top_k is not None:
    kwargs["search_top_k"] = search_top_k

  return OracleMemoryServiceConfig(**kwargs)


def _oracle_session_factory(uri: str, **kwargs: Any) -> OracleSessionService:
  del kwargs
  return OracleSessionService(_session_config_from_uri(uri))


def _oracle_memory_factory(uri: str, **kwargs: Any) -> OracleMemoryService:
  del kwargs
  return OracleMemoryService(_memory_config_from_uri(uri))


def _oracle_artifact_factory(uri: str, **kwargs: Any) -> OracleArtifactService:
  del kwargs
  return OracleArtifactService(_artifact_config_from_uri(uri))


def register_oracle_services() -> None:
  """Register oracle:// URI factories with ADK's service registry."""
  registry = get_service_registry()
  registry.register_session_service(_ORACLE_SCHEME, _oracle_session_factory)
  registry.register_memory_service(_ORACLE_SCHEME, _oracle_memory_factory)
  registry.register_artifact_service(_ORACLE_SCHEME, _oracle_artifact_factory)
