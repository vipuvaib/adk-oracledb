#!/bin/python
#
# $Header: test_oracle_contract.py 23-jul-2026.18:15:21 dascenci Exp $
#
# test_oracle_contract.py
#
# Copyright (c) 2026, Oracle and/or its affiliates.
#
#    NAME
#      test_oracle_contract.py - Oracle schema and datatype contract tests
#
#    DESCRIPTION
#      Exercises Oracle-specific schema lifecycle, JSON, Unicode, BLOB, and
#      configuration behavior through the public ADK service interfaces.
#
#    NOTES
#      These tests use the real TPI database and an isolated generated prefix.
#      Privilege-matrix and RAC failover tests require additional DB setup.
#
#    MODIFIED   (MM/DD/YY)
#    dascenci    08/04/26 - fix ADK functional test regressions
#    dascenci    07/23/26 - add ADK Oracle datatype and schema lifecycle tests
#    dascenci    07/23/26 - Creation
#
"""Oracle-specific functional tests for the ADK database integration."""

from __future__ import annotations

import os

from google.genai import types
import oracledb
import pytest

from adk_oracledb.artifacts import OracleArtifactService
from adk_oracledb.artifacts import OracleArtifactServiceConfig
from adk_oracledb.sessions import OracleSessionService
from adk_oracledb.sessions import OracleSessionServiceConfig

from conftest import _connect
from conftest import index_names as _index_names
from conftest import query_scalar as _query_scalar
from conftest import table_names as _table_names

pytestmark = pytest.mark.oracle


def _config(prefix: str) -> dict[str, object]:
  return {
      "user": os.environ["ORACLE_AI_DB_USER"],
      "password": os.environ["ORACLE_AI_DB_PASSWORD"],
      "dsn": os.environ["ORACLE_AI_DB_DSN"],
      "table_prefix": prefix,
      "auto_create_tables": True,
  }


def _column_types(table_name: str) -> dict[str, str]:
  connection = _connect()
  try:
    with connection.cursor() as cursor:
      cursor.execute(
          """
          SELECT column_name, data_type
          FROM user_tab_columns
          WHERE table_name = :table_name
          """,
          table_name=table_name,
      )
      return {name: data_type for name, data_type in cursor}
  finally:
    connection.close()


def _artifact_content_size(prefix: str, filename: str) -> int:
  connection = _connect()
  try:
    with connection.cursor() as cursor:
      cursor.execute(
          f"SELECT content_size FROM {prefix}_ARTIFACTS "
          "WHERE app_name = :app_name AND user_id = :user_id "
          "AND filename = :filename",
          app_name="lob",
          user_id="alice",
          filename=filename,
      )
      return int(cursor.fetchone()[0])
  finally:
    connection.close()


@pytest.mark.parametrize(
    "invalid_prefix",
    ["", "1ADK", "ADK-TEST", "ADK TEST", "ADK$TEST"],
)
def test_table_prefix_validation_rejects_invalid_oracle_identifiers(
    invalid_prefix: str,
) -> None:
  """Table names are validated before dynamic DDL or SQL is built."""
  with pytest.raises(ValueError):
    OracleSessionServiceConfig(
        user="user",
        password="password",
        dsn="cdb1_pdb1",
        table_prefix=invalid_prefix,
    )
  with pytest.raises(ValueError):
    OracleArtifactServiceConfig(
        user="user",
        password="password",
        dsn="cdb1_pdb1",
        table_prefix=invalid_prefix,
    )


@pytest.mark.asyncio
async def test_schema_initialization_is_idempotent(
    oracle_functional_environment,
) -> None:
  """A second service instance can reuse an existing schema safely."""
  environment = oracle_functional_environment
  config = _config(environment.prefix)
  first_session_service = OracleSessionService(
      OracleSessionServiceConfig(**config)
  )
  second_session_service = OracleSessionService(
      OracleSessionServiceConfig(**config)
  )
  first_artifact_service = OracleArtifactService(
      OracleArtifactServiceConfig(**config)
  )
  second_artifact_service = OracleArtifactService(
      OracleArtifactServiceConfig(**config)
  )

  await first_session_service.create_session(
      app_name="idempotent", user_id="alice", session_id="one"
  )
  await second_session_service.create_session(
      app_name="idempotent", user_id="alice", session_id="two"
  )
  await first_artifact_service.save_artifact(
      app_name="idempotent",
      user_id="alice",
      session_id="one",
      filename="one.txt",
      artifact=types.Part.from_text(text="one"),
  )
  await second_artifact_service.save_artifact(
      app_name="idempotent",
      user_id="alice",
      session_id="two",
      filename="two.txt",
      artifact=types.Part.from_text(text="two"),
  )


@pytest.mark.asyncio
async def test_session_json_unicode_and_nested_state_round_trip(
    oracle_functional_environment,
) -> None:
  """Oracle JSON preserves Unicode and nested state values."""
  service = oracle_functional_environment.session_service
  session = await service.create_session(
      app_name="datatype",
      user_id="東京ユーザー",
      state={
          "greeting": "Olá, 東京 🚀",
          "nested": {"enabled": True, "count": 3, "items": ["α", "β"]},
      },
  )
  loaded = await service.get_session(
      app_name="datatype", user_id="東京ユーザー", session_id=session.id
  )

  assert loaded is not None
  assert loaded.state == {
      "greeting": "Olá, 東京 🚀",
      "nested": {"enabled": True, "count": 3, "items": ["α", "β"]},
  }


@pytest.mark.asyncio
async def test_schema_uses_native_json_and_blob_columns(
    oracle_functional_environment,
) -> None:
  """The generated schema uses Oracle JSON and BLOB types as designed."""
  environment = oracle_functional_environment
  await environment.session_service.create_session(
      app_name="types", user_id="alice", state={"created": True}
  )
  await environment.artifact_service.save_artifact(
      app_name="types",
      user_id="alice",
      session_id="session",
      filename="types.txt",
      artifact=types.Part.from_text(text="types"),
  )

  session_columns = _column_types(f"{environment.prefix}_SESSIONS")
  artifact_columns = _column_types(f"{environment.prefix}_ARTIFACTS")
  assert session_columns["STATE_JSON"] == "JSON"
  assert artifact_columns["PART_JSON"] == "JSON"
  assert artifact_columns["CUSTOM_METADATA"] == "JSON"
  assert artifact_columns["PAYLOAD_BLOB"] == "BLOB"


@pytest.mark.asyncio
async def test_large_binary_artifact_round_trips_through_oracle_blob(
    oracle_functional_environment,
) -> None:
  """A one-megabyte payload survives Oracle BLOB storage and retrieval."""
  service = oracle_functional_environment.artifact_service
  payload = (b"oracle-adk-blob-" * 65536)[:1_000_000]
  filename = "large-payload.bin"
  await service.save_artifact(
      app_name="lob",
      user_id="alice",
      session_id="session",
      filename=filename,
      artifact=types.Part.from_bytes(
          data=payload, mime_type="application/octet-stream"
      ),
  )

  loaded = await service.load_artifact(
      app_name="lob",
      user_id="alice",
      session_id="session",
      filename=filename,
  )
  metadata = await service.get_artifact_version(
      app_name="lob",
      user_id="alice",
      session_id="session",
      filename=filename,
  )
  assert loaded is not None and loaded.inline_data is not None
  assert loaded.inline_data.data == payload
  assert metadata is not None
  assert _artifact_content_size(oracle_functional_environment.prefix, filename) == len(
      payload
  )

@pytest.mark.asyncio
async def test_auto_create_tables_false_fails_clearly_on_missing_schema() -> None:
  """Disabling auto-create must reach Oracle and report its missing-table error."""
  import uuid

  config = _config("ADKNOAUTO" + uuid.uuid4().hex[:10].upper())
  config["auto_create_tables"] = False
  service = OracleSessionService(OracleSessionServiceConfig(**config))
  with pytest.raises(oracledb.DatabaseError) as caught:
    await service.create_session(app_name="x", user_id="y")
  assert caught.value.args[0].code == 942


@pytest.mark.asyncio
async def test_multi_megabyte_binary_artifact_round_trips(
    oracle_functional_environment,
) -> None:
  """A payload crossing Oracle's inline-LOB threshold survives round trip."""
  service = oracle_functional_environment.artifact_service
  payload = (b"oracle-adk-blob-" * 65536 * 5)[:5_000_000]
  filename = "very-large-payload.bin"
  await service.save_artifact(
      app_name="lob",
      user_id="alice",
      session_id="session",
      filename=filename,
      artifact=types.Part.from_bytes(
          data=payload, mime_type="application/octet-stream"
      ),
  )

  loaded = await service.load_artifact(
      app_name="lob",
      user_id="alice",
      session_id="session",
      filename=filename,
  )
  assert loaded is not None and loaded.inline_data is not None
  assert loaded.inline_data.data == payload
