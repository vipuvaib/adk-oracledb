#!/bin/python
#
# $Header: test_artifacts.py 22-jul-2026.21:16:20 dascenci Exp $
#
# test_artifacts.py
#
# Copyright (c) 2026, Oracle and/or its affiliates.
#
#    NAME
#      test_artifacts.py - OracleArtifactService functional database tests
#
#    DESCRIPTION
#      Validates artifact schema and indexes, transaction visibility, version
#      allocation under concurrency, and user/session scope isolation.
#
#    NOTES
#      Database checks use a generated schema prefix and are performed against
#      the same Oracle account used by the public artifact service.
#
#    MODIFIED   (MM/DD/YY)
#    dascenci    07/22/26 - add ADK artifact functional tests
#    dascenci    07/22/26 - Creation
#
"""Real-Oracle functional coverage for OracleArtifactService."""

from __future__ import annotations

import os
import asyncio

from google.genai import types
import oracledb
import pytest


pytestmark = pytest.mark.oracle


def _table_names(prefix: str) -> set[str]:
  connection = oracledb.connect(
      user=os.environ["ORACLE_AI_DB_USER"],
      password=os.environ["ORACLE_AI_DB_PASSWORD"],
      dsn=os.environ["ORACLE_AI_DB_DSN"],
  )
  try:
    with connection.cursor() as cursor:
      cursor.execute(
          "SELECT table_name FROM user_tables WHERE table_name LIKE :prefix",
          prefix=f"{prefix}_%",
      )
      return {row[0] for row in cursor}
  finally:
    connection.close()


def _index_names(prefix: str) -> set[str]:
  connection = oracledb.connect(
      user=os.environ["ORACLE_AI_DB_USER"],
      password=os.environ["ORACLE_AI_DB_PASSWORD"],
      dsn=os.environ["ORACLE_AI_DB_DSN"],
  )
  try:
    with connection.cursor() as cursor:
      cursor.execute(
          "SELECT index_name FROM user_indexes WHERE index_name LIKE :prefix",
          prefix=f"{prefix}_%",
      )
      return {row[0] for row in cursor}
  finally:
    connection.close()


def _query_scalar(sql: str, **binds: object) -> object:
  connection = oracledb.connect(
      user=os.environ["ORACLE_AI_DB_USER"],
      password=os.environ["ORACLE_AI_DB_PASSWORD"],
      dsn=os.environ["ORACLE_AI_DB_DSN"],
  )
  try:
    with connection.cursor() as cursor:
      cursor.execute(sql, binds)
      return cursor.fetchone()[0]
  finally:
    connection.close()


@pytest.mark.asyncio
async def test_artifact_schema_creates_expected_table_and_indexes(
    oracle_functional_environment,
) -> None:
  """The artifact service creates the expected real-DB schema objects."""
  environment = oracle_functional_environment
  await environment.artifact_service.save_artifact(
      app_name="schema-app",
      user_id="schema-user",
      session_id="schema-session",
      filename="schema.txt",
      artifact=types.Part.from_text(text="schema"),
  )

  assert f"{environment.prefix}_ARTIFACTS" in _table_names(environment.prefix)
  indexes = _index_names(environment.prefix)
  assert f"{environment.prefix}_ARTIFACTS_LATEST_IX" in indexes
  assert f"{environment.prefix}_ARTIFACTS_KEYS_IX" not in indexes


@pytest.mark.asyncio
async def test_artifact_versions_and_scopes_are_isolated(
    oracle_functional_environment,
) -> None:
  """Session and user artifacts retain versions without crossing scopes."""
  service = oracle_functional_environment.artifact_service
  session_filename = "report.txt"
  user_filename = "user:profile.txt"

  assert await service.save_artifact(
      app_name="travel",
      user_id="alice",
      session_id="session-a",
      filename=session_filename,
      artifact=types.Part.from_text(text="first"),
  ) == 0
  assert await service.save_artifact(
      app_name="travel",
      user_id="alice",
      session_id="session-a",
      filename=session_filename,
      artifact=types.Part.from_text(text="second"),
  ) == 1
  assert await service.save_artifact(
      app_name="travel",
      user_id="alice",
      session_id=None,
      filename=user_filename,
      artifact=types.Part.from_text(text="alice profile"),
  ) == 0

  latest = await service.load_artifact(
      app_name="travel",
      user_id="alice",
      session_id="session-a",
      filename=session_filename,
  )
  original = await service.load_artifact(
      app_name="travel",
      user_id="alice",
      session_id="session-a",
      filename=session_filename,
      version=0,
  )
  assert latest is not None and latest.text == "second"
  assert original is not None and original.text == "first"
  assert await service.list_versions(
      app_name="travel",
      user_id="alice",
      session_id="session-a",
      filename=session_filename,
  ) == [0, 1]
  assert await service.load_artifact(
      app_name="travel",
      user_id="bob",
      session_id="session-a",
      filename=session_filename,
  ) is None
  user_artifact = await service.load_artifact(
      app_name="travel",
      user_id="alice",
      session_id="session-a",
      filename=user_filename,
  )
  assert user_artifact is not None and user_artifact.text == "alice profile"


@pytest.mark.asyncio
async def test_saved_artifact_is_committed_and_visible_to_a_new_connection(
    oracle_functional_environment,
) -> None:
  """A successful save is committed before the public API returns."""
  environment = oracle_functional_environment
  await environment.artifact_service.save_artifact(
      app_name="commit",
      user_id="alice",
      session_id="session-a",
      filename="visible.txt",
      artifact=types.Part.from_text(text="committed"),
  )

  assert _query_scalar(
      f"SELECT COUNT(*) FROM {environment.prefix}_ARTIFACTS "
      "WHERE app_name = :app_name AND user_id = :user_id AND filename = :filename",
      app_name="commit",
      user_id="alice",
      filename="visible.txt",
  ) == 1


@pytest.mark.asyncio
async def test_concurrent_saves_allocate_distinct_artifact_versions(
    oracle_functional_environment,
) -> None:
  """Concurrent saves retry Oracle uniqueness conflicts and preserve versions."""
  service = oracle_functional_environment.artifact_service
  versions = await asyncio.gather(
      *(
          service.save_artifact(
              app_name="concurrent",
              user_id="alice",
              session_id="session-a",
              filename="report.txt",
              artifact=types.Part.from_text(text=f"version {ordinal}"),
          )
          for ordinal in range(2)
      )
  )

  assert sorted(versions) == [0, 1]
  assert await service.list_versions(
      app_name="concurrent",
      user_id="alice",
      session_id="session-a",
      filename="report.txt",
  ) == [0, 1]


@pytest.mark.asyncio
async def test_artifact_keys_delete_and_binary_payload_round_trip(
    oracle_functional_environment,
) -> None:
  """User/session key listing, binary payloads, metadata, and deletion work."""
  service = oracle_functional_environment.artifact_service
  binary = types.Part(
      inline_data=types.Blob(data=b"\x00oracle\xff", mime_type="application/octet-stream")
  )

  await service.save_artifact(
      app_name="keys",
      user_id="alice",
      session_id="session-a",
      filename="binary.bin",
      artifact=binary,
      custom_metadata={"source": "functional", "ordinal": 1},
  )
  await service.save_artifact(
      app_name="keys",
      user_id="alice",
      session_id=None,
      filename="user:preferences.json",
      artifact=types.Part.from_text(text="{}"),
  )

  assert await service.list_artifact_keys(
      app_name="keys", user_id="alice", session_id="session-a"
  ) == ["binary.bin", "user:preferences.json"]
  loaded = await service.load_artifact(
      app_name="keys",
      user_id="alice",
      session_id="session-a",
      filename="binary.bin",
  )
  assert loaded is not None
  assert loaded.inline_data is not None
  assert loaded.inline_data.data == b"\x00oracle\xff"
  assert loaded.inline_data.mime_type == "application/octet-stream"

  await service.delete_artifact(
      app_name="keys",
      user_id="alice",
      session_id="session-a",
      filename="binary.bin",
  )
  assert await service.load_artifact(
      app_name="keys",
      user_id="alice",
      session_id="session-a",
      filename="binary.bin",
  ) is None
  assert await service.list_versions(
      app_name="keys",
      user_id="alice",
      session_id="session-a",
      filename="binary.bin",
  ) == []


@pytest.mark.asyncio
async def test_artifact_validation_rejects_invalid_scope_and_version(
    oracle_functional_environment,
) -> None:
  """Public validation prevents ambiguous scopes and invalid versions."""
  service = oracle_functional_environment.artifact_service
  with pytest.raises(ValueError, match="session_id is required"):
    await service.save_artifact(
        app_name="validation",
        user_id="alice",
        filename="session-only.txt",
        artifact=types.Part.from_text(text="invalid"),
    )
  with pytest.raises(ValueError, match="version must be non-negative"):
    await service.load_artifact(
        app_name="validation",
        user_id="alice",
        session_id="session-a",
        filename="session-only.txt",
        version=-1,
    )

@pytest.mark.asyncio
async def test_load_artifact_missing_version_returns_none(
    oracle_functional_environment,
) -> None:
  """Loading a version that was never written returns None, not an error."""
  service = oracle_functional_environment.artifact_service
  await service.save_artifact(
      app_name="missing-version",
      user_id="alice",
      session_id="session-a",
      filename="only-v0.txt",
      artifact=types.Part.from_text(text="v0"),
  )

  assert await service.load_artifact(
      app_name="missing-version",
      user_id="alice",
      session_id="session-a",
      filename="only-v0.txt",
      version=5,
  ) is None

@pytest.mark.asyncio
async def test_user_scoped_artifact_is_isolated_by_user(
    oracle_functional_environment,
) -> None:
  """A user:-prefixed artifact for one user is invisible to another user."""
  service = oracle_functional_environment.artifact_service
  await service.save_artifact(
      app_name="user-scope",
      user_id="alice",
      session_id=None,
      filename="user:profile.txt",
      artifact=types.Part.from_text(text="alice profile"),
  )

  assert await service.load_artifact(
      app_name="user-scope",
      user_id="bob",
      session_id=None,
      filename="user:profile.txt",
  ) is None

@pytest.mark.asyncio
async def test_versioning_after_delete(
    oracle_functional_environment,
) -> None:
  """Saving after delete either restarts or continues versioning consistently."""
  service = oracle_functional_environment.artifact_service
  filename = "recreated.txt"
  await service.save_artifact(
      app_name="revive",
      user_id="alice",
      session_id="session-a",
      filename=filename,
      artifact=types.Part.from_text(text="first"),
  )
  await service.delete_artifact(
      app_name="revive",
      user_id="alice",
      session_id="session-a",
      filename=filename,
  )
  new_version = await service.save_artifact(
      app_name="revive",
      user_id="alice",
      session_id="session-a",
      filename=filename,
      artifact=types.Part.from_text(text="after delete"),
  )

  # Document actual contract here once confirmed; placeholder assumes restart at 0.
  assert new_version == 0