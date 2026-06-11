from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
from typing import NoReturn
from urllib.parse import urlencode
import uuid

from google.genai import types


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))
EXAMPLES_DIR = REPO_ROOT / "examples"
if str(EXAMPLES_DIR) not in sys.path:
  sys.path.insert(0, str(EXAMPLES_DIR))

from oracle_env import load_repo_env
from oracle_env import require_env

from adk_oracledb.artifacts import OracleArtifactService
from adk_oracledb.artifacts import OracleArtifactServiceConfig
from adk_oracledb.registry import register_oracle_services
from google.adk.cli.service_registry import get_service_registry


load_repo_env(__file__)

APP_NAME = "artifact_smoke_app"
USER_ID = "artifact_smoke_user"


def _fail(message: str) -> NoReturn:
  raise SystemExit(message)


def _table_prefix() -> str:
  return os.environ.get("ORACLE_ARTIFACT_TABLE_PREFIX", "ADK_ART_SMOKE")


def _config_from_env() -> OracleArtifactServiceConfig:
  return OracleArtifactServiceConfig(
      user=require_env("ORACLE_AI_DB_USER"),
      password=require_env("ORACLE_AI_DB_PASSWORD"),
      dsn=require_env("ORACLE_AI_DB_DSN"),
      table_prefix=_table_prefix(),
      auto_create_tables=True,
  )


def _registry_uri() -> str:
  return f"oracle://?{urlencode({'artifact_table_prefix': _table_prefix()})}"


def _registry_construction_smoke() -> None:
  register_oracle_services()
  registry = get_service_registry()
  service = registry.create_artifact_service(_registry_uri())
  if not isinstance(service, OracleArtifactService):
    _fail("registry did not construct an OracleArtifactService for oracle://")
  print("artifact registry construction smoke passed")


def _assert_text(part: types.Part | None, expected: str, label: str) -> None:
  if part is None:
    _fail(f"{label} returned None")
  if part.text != expected:
    _fail(f"{label} text mismatch: expected {expected!r}, got {part.text!r}")


def _assert_binary(
    part: types.Part | None,
    *,
    expected_payload: bytes,
    expected_mime_type: str,
) -> None:
  if part is None:
    _fail("binary load returned None")
  if part.inline_data is None:
    _fail("binary load did not return inline_data")
  if part.inline_data.data != expected_payload:
    _fail("binary payload mismatch")
  if part.inline_data.mime_type != expected_mime_type:
    _fail(
        "binary mime type mismatch: "
        f"expected {expected_mime_type!r}, got {part.inline_data.mime_type!r}"
    )


async def main() -> None:
  _registry_construction_smoke()
  service = OracleArtifactService(_config_from_env())
  smoke_id = uuid.uuid4().hex
  session_id = f"artifact-smoke-session-{smoke_id}"

  text_filename = f"folder/artifact {smoke_id} #1.txt"
  text_v0 = f"artifact smoke text version zero {smoke_id}"
  text_v1 = f"artifact smoke text version one {smoke_id}"

  version0 = await service.save_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=text_filename,
      artifact=types.Part.from_text(text=text_v0),
      custom_metadata={
          "source": "artifact-smoke",
          "smoke_id": smoke_id,
          "version": 0,
      },
  )
  print(f"saved text artifact version: {version0}")
  assert version0 == 0

  version1 = await service.save_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=text_filename,
      artifact=types.Part.from_text(text=text_v1),
      custom_metadata={
          "source": "artifact-smoke",
          "smoke_id": smoke_id,
          "version": 1,
      },
  )
  print(f"saved text artifact version: {version1}")
  assert version1 == 1

  _assert_text(
      await service.load_artifact(
          app_name=APP_NAME,
          user_id=USER_ID,
          session_id=session_id,
          filename=text_filename,
      ),
      text_v1,
      "load latest text artifact",
  )
  _assert_text(
      await service.load_artifact(
          app_name=APP_NAME,
          user_id=USER_ID,
          session_id=session_id,
          filename=text_filename,
          version=0,
      ),
      text_v0,
      "load text artifact version 0",
  )

  versions = await service.list_versions(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=text_filename,
  )
  print(f"text artifact versions: {versions}")
  assert versions == [0, 1]

  latest_metadata = await service.get_artifact_version(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=text_filename,
  )
  if latest_metadata is None:
    _fail("get_artifact_version returned None for text artifact")
  print(f"latest text artifact metadata: {latest_metadata}")
  assert latest_metadata.version == 1
  assert latest_metadata.mime_type == "text/plain"
  assert latest_metadata.custom_metadata["smoke_id"] == smoke_id
  assert latest_metadata.canonical_uri.endswith("?version=1")

  all_metadata = await service.list_artifact_versions(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=text_filename,
  )
  print(f"text artifact version metadata count: {len(all_metadata)}")
  assert [item.version for item in all_metadata] == [0, 1]

  binary_filename = f"folder/artifact {smoke_id} #1.bin"
  binary_payload = f"artifact-binary-smoke-{smoke_id}".encode("utf-8")
  binary_mime_type = "application/octet-stream"
  binary_version = await service.save_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=binary_filename,
      artifact=types.Part(
          inline_data=types.Blob(
              data=binary_payload,
              mime_type=binary_mime_type,
          )
      ),
      custom_metadata={
          "source": "artifact-binary-smoke",
          "smoke_id": smoke_id,
      },
  )
  print(f"saved binary artifact version: {binary_version}")
  assert binary_version == 0

  _assert_binary(
      await service.load_artifact(
          app_name=APP_NAME,
          user_id=USER_ID,
          session_id=session_id,
          filename=binary_filename,
      ),
      expected_payload=binary_payload,
      expected_mime_type=binary_mime_type,
  )

  user_filename = f"user:user-artifact-{smoke_id}.txt"
  user_text = f"user scoped artifact {smoke_id}"
  user_version = await service.save_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=user_filename,
      artifact=types.Part.from_text(text=user_text),
      custom_metadata={
          "source": "artifact-user-smoke",
          "scope": "user",
          "smoke_id": smoke_id,
      },
  )
  print(f"saved user-scoped artifact version: {user_version}")
  assert user_version == 0

  _assert_text(
      await service.load_artifact(
          app_name=APP_NAME,
          user_id=USER_ID,
          session_id=session_id,
          filename=user_filename,
      ),
      user_text,
      "load user artifact with session_id",
  )
  _assert_text(
      await service.load_artifact(
          app_name=APP_NAME,
          user_id=USER_ID,
          session_id=None,
          filename=user_filename,
      ),
      user_text,
      "load user artifact without session_id",
  )

  session_keys = await service.list_artifact_keys(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
  )
  print(f"session artifact keys: {session_keys}")
  assert text_filename in session_keys
  assert binary_filename in session_keys
  assert user_filename in session_keys

  user_keys = await service.list_artifact_keys(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=None,
  )
  print(f"user artifact keys: {user_keys}")
  assert user_filename in user_keys
  assert text_filename not in user_keys

  user_metadata = await service.get_artifact_version(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=user_filename,
  )
  if user_metadata is None:
    _fail("get_artifact_version returned None for user artifact")
  print(f"user artifact metadata: {user_metadata}")
  assert user_metadata.version == 0
  assert user_metadata.custom_metadata["scope"] == "user"
  assert "/user/" in user_metadata.canonical_uri

  await service.delete_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=user_filename,
  )
  deleted_user = await service.load_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=user_filename,
  )
  assert deleted_user is None
  print("deleted user-scoped artifact")

  await service.delete_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=text_filename,
  )
  assert (
      await service.load_artifact(
          app_name=APP_NAME,
          user_id=USER_ID,
          session_id=session_id,
          filename=text_filename,
      )
      is None
  )
  assert (
      await service.list_versions(
          app_name=APP_NAME,
          user_id=USER_ID,
          session_id=session_id,
          filename=text_filename,
      )
      == []
  )
  print("deleted text artifact")

  await service.delete_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=binary_filename,
  )
  print("deleted binary artifact")

  print("artifact smoke completed successfully")


if __name__ == "__main__":
  asyncio.run(main())
