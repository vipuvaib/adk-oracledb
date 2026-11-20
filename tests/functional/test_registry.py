#!/bin/python
#
# $Header: test_registry.py 23-jul-2026.18:27:01 dascenci Exp $
#
# test_registry.py
#
# Copyright (c) 2026, Oracle and/or its affiliates.
#
#    NAME
#      test_registry.py - Oracle ADK service registry functional tests
#
#    DESCRIPTION
#      Validates oracle:// service construction through the Google ADK
#      registry and exercises the returned services against real Oracle data.
#
#    NOTES
#      Registry parser-only coverage is intentionally avoided; each factory is
#      followed by a real service operation where the environment supports it.
#
#    MODIFIED   (MM/DD/YY)
#    dascenci    08/04/26 - fix ADK functional test regressions
#    dascenci    07/23/26 - add ADK registry functional tests
#    dascenci    07/23/26 - Creation
#
"""Functional coverage for oracle:// ADK registry factories."""

from __future__ import annotations

import os
from urllib.parse import urlencode

from google.adk.cli.service_registry import get_service_registry
from google.adk.memory.memory_entry import MemoryEntry
from google.genai import types
import pytest

from adk_oracledb.registry import register_oracle_services
from adk_oracledb.registry import _artifact_config_from_uri
from adk_oracledb.registry import _parse_oracle_uri
from adk_oracledb.registry import _session_config_from_uri


pytestmark = pytest.mark.oracle


def _oracle_uri(**params: str) -> str:
  return "oracle://?" + urlencode(params)


@pytest.mark.asyncio
async def test_registry_session_and_artifact_factories_use_real_oracle(
    oracle_functional_environment,
) -> None:
  """Session and artifact registry factories return working Oracle services."""
  environment = oracle_functional_environment
  register_oracle_services()
  registry = get_service_registry()
  session_service = registry.create_session_service(
      _oracle_uri(table_prefix=environment.prefix)
  )
  artifact_service = registry.create_artifact_service(
      _oracle_uri(artifact_table_prefix=environment.prefix)
  )

  session = await session_service.create_session(
      app_name="registry", user_id="alice", session_id="session-1"
  )
  assert session.id == "session-1"
  version = await artifact_service.save_artifact(
      app_name="registry",
      user_id="alice",
      session_id=session.id,
      filename="registry.txt",
      artifact=types.Part.from_text(text="registry functional"),
  )
  assert version == 0


@pytest.mark.asyncio
async def test_registry_memory_factory_uses_real_oracle_memory_tables(
    memory_functional_service,
) -> None:
  """The memory registry factory constructs a client backed by Oracle."""
  _, prefix = memory_functional_service
  embedder_model = os.environ["EMBEDDING_MODEL"]
  register_oracle_services()
  registry = get_service_registry()
  service = registry.create_memory_service(
      _oracle_uri(
          memory_table_prefix=prefix,
          embedder_model=embedder_model,
      )
  )

  try:
    await service.add_memory(
        app_name="registry-memory",
        user_id="alice",
        memories=[
            MemoryEntry(
                content=types.Content(
                    role="user",
                    parts=[types.Part.from_text(text="registry memory functional")],
                )
            )
        ],
    )
    assert service._config.table_name_prefix == prefix
  finally:
    pool = getattr(service, "_pool", None)
    if pool is not None:
      pool.close()


def test_registry_parses_explicit_credentials_and_service_name(
    monkeypatch,
) -> None:
  """Explicit oracle:// authority takes precedence over environment DSN."""
  monkeypatch.setenv("ORACLE_AI_DB_DSN", "environment-dsn")
  parsed = _parse_oracle_uri(
      "oracle://user%40name:secret@db.example.test:1522/XEPDB1"
  )
  assert parsed["user"] == "user@name"
  assert parsed["password"] == "secret"
  assert parsed["dsn"] == "db.example.test:1522/XEPDB1"


def test_registry_rejects_invalid_options_and_service_pool_parameters() -> None:
  """Malformed booleans/integers and unsupported pool options fail early."""
  base = "oracle://user:secret@db.example.test/XEPDB1"
  with pytest.raises(ValueError, match="boolean"):
    _session_config_from_uri(base + "?auto_create_tables=maybe")
  with pytest.raises(ValueError, match="only supported"):
    _artifact_config_from_uri(base + "?pool_min=0")
  with pytest.raises(ValueError, match="only supported"):
    _session_config_from_uri(base + "?pool_max=2")

def test_register_oracle_services_twice_is_idempotent() -> None:
  """Calling register_oracle_services twice does not raise or double-register."""
  register_oracle_services()
  register_oracle_services()  # should not raise
  registry = get_service_registry()
  # Sanity: factory still resolves normally after double registration.
  assert registry.create_session_service(_oracle_uri(table_prefix="ADK_REG_CHECK"))
