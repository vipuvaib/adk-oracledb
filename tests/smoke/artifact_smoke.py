from __future__ import annotations

import asyncio
import base64
import json
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
from adk_oracledb.artifacts import service as artifact_service_module
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


def _assert_inline_data(
    part: types.Part | None,
    *,
    expected_data: bytes,
    expected_mime_type: str,
    label: str,
) -> None:
  if part is None:
    _fail(f"{label} returned None")
  if part.inline_data is None:
    _fail(f"{label} did not return inline_data: {part!r}")
  if part.inline_data.data != expected_data:
    _fail(f"{label} inline bytes changed during round trip")
  if part.inline_data.mime_type != expected_mime_type:
    _fail(
        f"{label} mime_type mismatch: expected {expected_mime_type!r}, "
        f"got {part.inline_data.mime_type!r}"
    )


def _assert_file_data(
    part: types.Part | None,
    *,
    expected_uri: str,
    expected_mime_type: str,
    label: str,
) -> None:
  if part is None:
    _fail(f"{label} returned None")
  if part.file_data is None:
    _fail(f"{label} did not return file_data: {part!r}")
  if part.file_data.file_uri != expected_uri:
    _fail(
        f"{label} file_uri mismatch: expected {expected_uri!r}, "
        f"got {part.file_data.file_uri!r}"
    )
  if part.file_data.mime_type != expected_mime_type:
    _fail(
        f"{label} mime_type mismatch: expected {expected_mime_type!r}, "
        f"got {part.file_data.mime_type!r}"
    )


def _artifact_scope_helper_smoke() -> None:
  assert artifact_service_module._artifact_scope_type_and_id(
      filename="user:profile.txt",
      session_id=None,
  ) == ("USER", "__USER__")
  assert artifact_service_module._artifact_scope_type_and_id(
      filename="report.txt",
      session_id="session-1",
  ) == ("SESSION", "session-1")
  for missing_session_id in (None, " "):
    try:
      artifact_service_module._artifact_scope_type_and_id(
          filename="report.txt",
          session_id=missing_session_id,
      )
    except ValueError as exc:
      if "session_id is required for session-scoped artifacts" not in str(exc):
        raise
    else:
      _fail("plain artifact filename did not require a session_id")


def _artifact_inline_data_helper_smoke() -> None:
  original_bytes = b"\xfb\xff%PDF-1.4 oracle inline bytes\x00"
  mime_type = "application/pdf"
  part = types.Part.from_bytes(data=original_bytes, mime_type=mime_type)

  payload_kind, payload, payload_mime_type, part_json = (
      artifact_service_module._part_to_payload(part)
  )
  assert payload_kind == "INLINE_DATA"
  assert payload == original_bytes
  assert payload_mime_type == mime_type
  inline_json = part_json["inlineData"]
  assert "data" not in inline_json
  assert inline_json["mimeType"] == mime_type
  assert inline_json["size"] == len(original_bytes)
  assert inline_json["storage"] == "payload_blob"

  serialized_part = part.model_dump(
      mode="json", exclude_none=True, by_alias=True
  )
  encoded_payload = serialized_part["inlineData"]["data"]
  ensured_part = artifact_service_module._ensure_part(serialized_part)
  ensured_payload_kind, ensured_payload, _, ensured_part_json = (
      artifact_service_module._part_to_payload(ensured_part)
  )
  assert ensured_payload_kind == "INLINE_DATA"
  assert ensured_payload == original_bytes
  assert "data" not in ensured_part_json["inlineData"]
  assert encoded_payload not in json.dumps(ensured_part_json)

  decoded_payload = artifact_service_module._inline_data_to_bytes(
      encoded_payload
  )
  assert decoded_payload == original_bytes

  padded_base64 = base64.b64encode(original_bytes).decode("ascii")
  unpadded_base64 = padded_base64.rstrip("=")
  padded_urlsafe_base64 = base64.urlsafe_b64encode(original_bytes).decode(
      "ascii"
  )
  unpadded_urlsafe_base64 = padded_urlsafe_base64.rstrip("=")
  for encoded in (
      padded_base64,
      unpadded_base64,
      padded_urlsafe_base64,
      unpadded_urlsafe_base64,
      f"  {unpadded_urlsafe_base64}  ",
  ):
    assert artifact_service_module._inline_data_to_bytes(encoded) == original_bytes

  for invalid_value in (
      "not valid base64",
      "abcde",
      "****",
  ):
    try:
      artifact_service_module._inline_data_to_bytes(invalid_value)
    except ValueError as exc:
      if "base64" not in str(exc):
        raise
    else:
      _fail(
          f"invalid base64 inline_data.data did not raise ValueError: "
          f"{invalid_value!r}"
      )


def _artifact_file_data_helper_smoke() -> None:
  file_uri = "file://example/report.pdf"
  mime_type = "application/pdf"
  part = types.Part(
      file_data=types.FileData(file_uri=file_uri, mime_type=mime_type)
  )
  payload_kind, payload, payload_mime_type, part_json = (
      artifact_service_module._part_to_payload(part)
  )
  assert payload_kind == "FILE_DATA"
  assert payload == file_uri.encode("utf-8")
  assert payload_mime_type == mime_type
  assert part_json["payloadKind"] == "FILE_DATA"
  assert part_json["fileData"]["fileUri"] == file_uri
  assert part_json["fileData"]["mimeType"] == mime_type
  assert part_json["fileData"]["storage"] == "payload_blob"
  assert part_json["fileData"]["representation"] == "file_uri"

  round_tripped = artifact_service_module._payload_to_part(
      payload_kind=payload_kind,
      payload=payload,
      mime_type=payload_mime_type,
  )
  _assert_file_data(
      round_tripped,
      expected_uri=file_uri,
      expected_mime_type=mime_type,
      label="file_data helper round trip",
  )


async def main() -> None:
  _artifact_scope_helper_smoke()
  _artifact_inline_data_helper_smoke()
  _artifact_file_data_helper_smoke()
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

  missing_session_filename = f"plain-missing-session-{smoke_id}.txt"
  for missing_session_id in (None, " "):
    try:
      await service.save_artifact(
          app_name=APP_NAME,
          user_id=USER_ID,
          session_id=missing_session_id,
          filename=missing_session_filename,
          artifact=types.Part.from_text(text="should not save"),
      )
    except ValueError as exc:
      if "session_id is required for session-scoped artifacts" not in str(exc):
        raise
    else:
      _fail("plain artifact save without session_id did not fail")
  print("plain artifact missing-session validation passed")

  user_filename = f"user:user-artifact-{smoke_id}.txt"
  user_text = f"user scoped artifact {smoke_id}"
  user_version = await service.save_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=None,
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

  inline_dict_filename = f"inline-dict-artifact-{smoke_id}.pdf"
  inline_dict_bytes = (
      b"%PDF-1.4 oracle inline dict artifact " + smoke_id.encode("utf-8")
  )
  inline_dict_mime_type = "application/pdf"
  inline_dict_part = types.Part.from_bytes(
      data=inline_dict_bytes,
      mime_type=inline_dict_mime_type,
  ).model_dump(mode="json", exclude_none=True, by_alias=True)
  inline_dict_version = await service.save_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=inline_dict_filename,
      artifact=inline_dict_part,
      custom_metadata={
          "source": "artifact-inline-dict-smoke",
          "smoke_id": smoke_id,
      },
  )
  print(f"saved inline dict artifact version: {inline_dict_version}")
  assert inline_dict_version == 0

  _assert_inline_data(
      await service.load_artifact(
          app_name=APP_NAME,
          user_id=USER_ID,
          session_id=session_id,
          filename=inline_dict_filename,
      ),
      expected_data=inline_dict_bytes,
      expected_mime_type=inline_dict_mime_type,
      label="load inline dict artifact",
  )
  inline_dict_metadata = await service.get_artifact_version(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=inline_dict_filename,
  )
  if inline_dict_metadata is None:
    _fail("get_artifact_version returned None for inline dict artifact")
  assert inline_dict_metadata.version == 0
  assert inline_dict_metadata.mime_type == inline_dict_mime_type
  assert inline_dict_metadata.custom_metadata["smoke_id"] == smoke_id
  print("inline dict artifact smoke passed")

  await service.delete_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=inline_dict_filename,
  )
  assert (
      await service.load_artifact(
          app_name=APP_NAME,
          user_id=USER_ID,
          session_id=session_id,
          filename=inline_dict_filename,
      )
      is None
  )
  print("deleted inline dict artifact")

  file_data_filename = f"file-data-artifact-{smoke_id}.pdf"
  file_data_uri = f"file://example/{smoke_id}/report.pdf"
  file_data_mime_type = "application/pdf"
  file_data_version = await service.save_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=file_data_filename,
      artifact=types.Part(
          file_data=types.FileData(
              file_uri=file_data_uri,
              mime_type=file_data_mime_type,
          )
      ),
      custom_metadata={
          "source": "artifact-file-data-smoke",
          "smoke_id": smoke_id,
      },
  )
  print(f"saved file_data artifact version: {file_data_version}")
  assert file_data_version == 0

  _assert_file_data(
      await service.load_artifact(
          app_name=APP_NAME,
          user_id=USER_ID,
          session_id=session_id,
          filename=file_data_filename,
      ),
      expected_uri=file_data_uri,
      expected_mime_type=file_data_mime_type,
      label="load file_data artifact",
  )
  file_data_metadata = await service.get_artifact_version(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=file_data_filename,
  )
  if file_data_metadata is None:
    _fail("get_artifact_version returned None for file_data artifact")
  assert file_data_metadata.version == 0
  assert file_data_metadata.mime_type == file_data_mime_type
  assert file_data_metadata.custom_metadata["smoke_id"] == smoke_id
  file_data_versions = await service.list_artifact_versions(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=file_data_filename,
  )
  assert len(file_data_versions) == 1
  assert file_data_versions[0].mime_type == file_data_mime_type
  print("file_data artifact smoke passed")

  await service.delete_artifact(
      app_name=APP_NAME,
      user_id=USER_ID,
      session_id=session_id,
      filename=file_data_filename,
  )
  assert (
      await service.load_artifact(
          app_name=APP_NAME,
          user_id=USER_ID,
          session_id=session_id,
          filename=file_data_filename,
      )
      is None
  )
  print("deleted file_data artifact")

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

  print("artifact smoke completed successfully")


if __name__ == "__main__":
  asyncio.run(main())
