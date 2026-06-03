from __future__ import annotations

import asyncio
from decimal import Decimal
from datetime import datetime
from datetime import timezone
import hashlib
import inspect
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

from adk_oracledb.connection import create_oracle_connection
from google.adk.artifacts.base_artifact_service import ArtifactVersion
from google.adk.artifacts.base_artifact_service import BaseArtifactService
from google.genai import types
from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator
from typing_extensions import override


_ARTIFACT_USER_SCOPE = "USER"
_ARTIFACT_SESSION_SCOPE = "SESSION"
_USER_SCOPE_ID = "__USER__"
_USER_NAMESPACE_PREFIX = "user:"
_ORACLE_ALREADY_EXISTS_CODE = 955
_ORACLE_UNIQUE_CONSTRAINT_CODE = 1
_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


async def _maybe_await(value: Any) -> Any:
  if inspect.isawaitable(value):
    return await value
  return value


async def _call(method: Any, *args: Any, **kwargs: Any) -> Any:
  return await _maybe_await(method(*args, **kwargs))


async def _close(resource: Any) -> None:
  close = getattr(resource, "close", None)
  if close is not None:
    await _maybe_await(close())


async def _rollback(connection: Any) -> None:
  rollback = getattr(connection, "rollback", None)
  if rollback is not None:
    try:
      await _maybe_await(rollback())
    except Exception:
      pass


def _schema_statements(table_prefix: str) -> list[str]:
  schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
  schema_sql = schema_sql.replace("ADK_", f"{table_prefix}_")
  sql_lines = []
  for line in schema_sql.splitlines():
    if not line.strip().startswith("--"):
      sql_lines.append(line)
  return [
      statement.strip()
      for statement in "\n".join(sql_lines).split(";")
      if statement.strip()
  ]


def _is_oracle_error_code(error: BaseException, code: int) -> bool:
  if f"ORA-{code:05d}" in str(error):
    return True

  for arg in getattr(error, "args", ()):
    if getattr(arg, "code", None) == code:
      return True
  return False


def _is_oracle_already_exists_error(error: BaseException) -> bool:
  return _is_oracle_error_code(error, _ORACLE_ALREADY_EXISTS_CODE)


def _is_oracle_unique_constraint_error(error: BaseException) -> bool:
  return _is_oracle_error_code(error, _ORACLE_UNIQUE_CONSTRAINT_CODE)


def _scope_type_and_id(session_id: str | None) -> tuple[str, str]:
  if session_id is None:
    return _ARTIFACT_USER_SCOPE, _USER_SCOPE_ID

  session_id = session_id.strip()
  if not session_id:
    return _ARTIFACT_USER_SCOPE, _USER_SCOPE_ID
  return _ARTIFACT_SESSION_SCOPE, session_id


def _is_user_scoped_filename(filename: str) -> bool:
  return filename.startswith(_USER_NAMESPACE_PREFIX)


def _artifact_scope_type_and_id(
    *,
    filename: str,
    session_id: str | None,
) -> tuple[str, str]:
  if _is_user_scoped_filename(filename):
    return _ARTIFACT_USER_SCOPE, _USER_SCOPE_ID
  return _scope_type_and_id(session_id)


def _validate_non_empty(value: str, name: str) -> str:
  value = value.strip()
  if not value:
    raise ValueError(f"{name} must not be empty")
  return value


def _filename_hash(filename: str) -> str:
  return hashlib.sha256(filename.encode("utf-8")).hexdigest()


def _artifact_canonical_uri(
    *,
    app_name: str,
    user_id: str,
    scope_type: str,
    scope_id: str,
    filename: str,
    version: int,
) -> str:
  encoded_app_name = quote(app_name, safe="")
  encoded_user_id = quote(user_id, safe="")
  encoded_scope_type = quote(scope_type.lower(), safe="")
  encoded_scope_id = quote(scope_id, safe="")
  encoded_filename = quote(filename, safe="")
  return (
      f"artifact://{encoded_app_name}/{encoded_user_id}/"
      f"{encoded_scope_type}/{encoded_scope_id}/{encoded_filename}"
      f"?version={version}"
  )


def _ensure_part(artifact: types.Part | dict[str, Any]) -> types.Part:
  if isinstance(artifact, types.Part):
    return artifact
  if isinstance(artifact, dict):
    return types.Part.model_validate(artifact)
  raise ValueError("artifact must be a google.genai.types.Part or dict")


def _part_json(part: types.Part, payload: bytes, mime_type: str | None) -> dict[str, Any]:
  try:
    return part.model_dump(mode="json", by_alias=True, exclude_none=True)
  except (TypeError, ValueError):
    return {
        "inlineData": {
            "mimeType": mime_type,
            "size": len(payload),
        }
    }


def _part_to_payload(
    part: types.Part,
) -> tuple[str, bytes, str | None, dict[str, Any]]:
  if part.text is not None:
    payload = part.text.encode("utf-8")
    return (
        "TEXT",
        payload,
        "text/plain",
        part.model_dump(mode="json", by_alias=True, exclude_none=True),
    )

  if part.inline_data is not None:
    payload = part.inline_data.data or b""
    if isinstance(payload, bytearray):
      payload = bytes(payload)
    mime_type = part.inline_data.mime_type
    return (
        "INLINE_DATA",
        payload,
        mime_type,
        _part_json(part, payload, mime_type),
    )

  raise ValueError(
      "OracleArtifactService currently supports text and inline_data "
      "artifacts only."
  )


def _payload_to_part(
    *,
    payload_kind: str,
    payload: bytes,
    mime_type: str | None,
) -> types.Part:
  if payload_kind == "TEXT":
    return types.Part.from_text(text=payload.decode("utf-8"))
  if payload_kind == "INLINE_DATA":
    return types.Part(inline_data=types.Blob(data=payload, mime_type=mime_type))
  raise ValueError(f"Unsupported artifact payload kind: {payload_kind}")


async def _read_lob(value: Any) -> Any:
  read = getattr(value, "read", None)
  if read is not None:
    return await _maybe_await(read())
  return value


def _to_bytes(value: Any) -> bytes:
  if isinstance(value, bytes):
    return value
  if isinstance(value, bytearray):
    return bytes(value)
  if isinstance(value, memoryview):
    return value.tobytes()
  if isinstance(value, str):
    return value.encode("utf-8")
  return bytes(value)


def _json_dump(value: dict[str, Any] | list[Any]) -> str:
  try:
    return json.dumps(value, allow_nan=False)
  except (TypeError, ValueError) as e:
    raise ValueError("artifact metadata must be JSON serializable") from e


def _normalize_json_value(value: Any) -> Any:
  if isinstance(value, dict):
    return {key: _normalize_json_value(item) for key, item in value.items()}
  if isinstance(value, list):
    return [_normalize_json_value(item) for item in value]
  if isinstance(value, Decimal):
    if value == value.to_integral_value():
      return int(value)
    return float(value)
  return value


async def _json_load(value: Any) -> dict[str, Any]:
  value = await _read_lob(value)
  if value is None:
    return {}
  if isinstance(value, (bytes, bytearray)):
    value = value.decode("utf-8")
  if isinstance(value, str):
    value = json.loads(value) if value else {}
  value = _normalize_json_value(value)
  if not isinstance(value, dict):
    raise ValueError("Expected JSON object for artifact metadata.")
  return value


def _timestamp_to_float(value: Any) -> float:
  if isinstance(value, datetime):
    if value.tzinfo is None:
      value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()
  return float(value)


async def _artifact_version_from_row(row: Any) -> ArtifactVersion:
  return ArtifactVersion(
      version=int(row[0]),
      canonical_uri=row[1],
      custom_metadata=await _json_load(row[2]),
      create_time=_timestamp_to_float(row[3]),
      mime_type=row[4],
  )


class OracleArtifactServiceConfig(BaseModel):
  """Configuration for Oracle-backed ADK artifact storage."""

  user: str
  password: str
  dsn: str
  table_prefix: str = "ADK"
  auto_create_tables: bool = True
  pool_min: int = Field(default=1, ge=1)
  pool_max: int = Field(default=4, ge=1)

  @field_validator("table_prefix")
  @classmethod
  def _validate_table_prefix(cls, value: str) -> str:
    table_prefix = value.strip().upper()
    if not table_prefix:
      raise ValueError("table_prefix must not be empty")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", table_prefix):
      raise ValueError(
          "table_prefix must contain only letters, numbers, and underscore"
      )
    return table_prefix

  @model_validator(mode="after")
  def _validate_pool_bounds(self) -> OracleArtifactServiceConfig:
    if self.pool_max < self.pool_min:
      raise ValueError("pool_max must be greater than or equal to pool_min")
    return self


class OracleArtifactService(BaseArtifactService):
  """Skeleton ADK artifact service backed by Oracle Database."""

  def __init__(self, config: OracleArtifactServiceConfig):
    self._config = config
    self._schema_initialized = False
    self._schema_lock = asyncio.Lock()

  def _artifacts_table_name(self) -> str:
    return f"{self._config.table_prefix}_ARTIFACTS"

  async def _ensure_schema(self) -> None:
    if not self._config.auto_create_tables or self._schema_initialized:
      return

    async with self._schema_lock:
      if self._schema_initialized:
        return

      connection = await create_oracle_connection(self._config)
      cursor = None
      try:
        cursor = await _call(connection.cursor)
        for statement in _schema_statements(self._config.table_prefix):
          try:
            await _call(cursor.execute, statement)
          except Exception as e:
            if _is_oracle_already_exists_error(e):
              continue
            raise
        await _call(connection.commit)
        self._schema_initialized = True
      except BaseException:
        await _rollback(connection)
        raise
      finally:
        if cursor is not None:
          await _close(cursor)
        await _close(connection)

  @override
  async def save_artifact(
      self,
      *,
      app_name: str,
      user_id: str,
      filename: str,
      artifact: types.Part | dict[str, Any],
      session_id: str | None = None,
      custom_metadata: dict[str, Any] | None = None,
  ) -> int:
    app_name = _validate_non_empty(app_name, "app_name")
    user_id = _validate_non_empty(user_id, "user_id")
    filename = _validate_non_empty(filename, "filename")
    scope_type, scope_id = _artifact_scope_type_and_id(
        filename=filename,
        session_id=session_id,
    )
    session_id_value = scope_id if scope_type == _ARTIFACT_SESSION_SCOPE else None
    filename_hash = _filename_hash(filename)

    part = _ensure_part(artifact)
    payload_kind, payload, mime_type, part_json = _part_to_payload(part)
    payload_hash = hashlib.sha256(payload).hexdigest()
    content_size = len(payload)
    metadata_json = _json_dump(dict(custom_metadata or {}))
    part_json_value = _json_dump(part_json)
    artifacts_table = self._artifacts_table_name()

    await self._ensure_schema()
    connection = await create_oracle_connection(self._config)
    cursor = None
    try:
      cursor = await _call(connection.cursor)
      for attempt in range(3):
        await _call(
            cursor.execute,
            f"""
            SELECT NVL(MAX(version), -1) + 1
            FROM {artifacts_table}
            WHERE app_name = :app_name
              AND user_id = :user_id
              AND scope_type = :scope_type
              AND scope_id = :scope_id
              AND filename_hash = :filename_hash
            """,
            {
                "app_name": app_name,
                "user_id": user_id,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "filename_hash": filename_hash,
            },
        )
        row = await _call(cursor.fetchone)
        version = int(row[0])
        canonical_uri = _artifact_canonical_uri(
            app_name=app_name,
            user_id=user_id,
            scope_type=scope_type,
            scope_id=scope_id,
            filename=filename,
            version=version,
        )

        try:
          await _call(
              cursor.execute,
              f"""
              INSERT INTO {artifacts_table} (
                app_name,
                user_id,
                scope_type,
                scope_id,
                session_id,
                filename,
                filename_hash,
                version,
                payload_kind,
                mime_type,
                payload_blob,
                part_json,
                custom_metadata,
                canonical_uri,
                content_size,
                sha256
              )
              VALUES (
                :app_name,
                :user_id,
                :scope_type,
                :scope_id,
                :session_id,
                :filename,
                :filename_hash,
                :version,
                :payload_kind,
                :mime_type,
                :payload_blob,
                :part_json,
                :custom_metadata,
                :canonical_uri,
                :content_size,
                :sha256
              )
              """,
              {
                  "app_name": app_name,
                  "user_id": user_id,
                  "scope_type": scope_type,
                  "scope_id": scope_id,
                  "session_id": session_id_value,
                  "filename": filename,
                  "filename_hash": filename_hash,
                  "version": version,
                  "payload_kind": payload_kind,
                  "mime_type": mime_type,
                  "payload_blob": payload,
                  "part_json": part_json_value,
                  "custom_metadata": metadata_json,
                  "canonical_uri": canonical_uri,
                  "content_size": content_size,
                  "sha256": payload_hash,
              },
          )
        except Exception as e:
          if attempt < 2 and _is_oracle_unique_constraint_error(e):
            await _rollback(connection)
            continue
          raise

        await _call(connection.commit)
        return version

      raise RuntimeError("Could not allocate artifact version after retries.")
    except BaseException:
      await _rollback(connection)
      raise
    finally:
      if cursor is not None:
        await _close(cursor)
      await _close(connection)

  @override
  async def load_artifact(
      self,
      *,
      app_name: str,
      user_id: str,
      filename: str,
      session_id: str | None = None,
      version: int | None = None,
  ) -> types.Part | None:
    app_name = _validate_non_empty(app_name, "app_name")
    user_id = _validate_non_empty(user_id, "user_id")
    filename = _validate_non_empty(filename, "filename")
    if version is not None and version < 0:
      raise ValueError("version must be non-negative")

    scope_type, scope_id = _artifact_scope_type_and_id(
        filename=filename,
        session_id=session_id,
    )
    filename_hash = _filename_hash(filename)
    artifacts_table = self._artifacts_table_name()

    await self._ensure_schema()
    connection = await create_oracle_connection(self._config)
    cursor = None
    try:
      cursor = await _call(connection.cursor)
      params: dict[str, Any] = {
          "app_name": app_name,
          "user_id": user_id,
          "scope_type": scope_type,
          "scope_id": scope_id,
          "filename_hash": filename_hash,
      }
      if version is None:
        query = f"""
          SELECT payload_kind, payload_blob, mime_type
          FROM (
            SELECT payload_kind, payload_blob, mime_type, version
            FROM {artifacts_table}
            WHERE app_name = :app_name
              AND user_id = :user_id
              AND scope_type = :scope_type
              AND scope_id = :scope_id
              AND filename_hash = :filename_hash
            ORDER BY version DESC
          )
          WHERE ROWNUM <= 1
        """
      else:
        params["version"] = version
        query = f"""
          SELECT payload_kind, payload_blob, mime_type
          FROM {artifacts_table}
          WHERE app_name = :app_name
            AND user_id = :user_id
            AND scope_type = :scope_type
            AND scope_id = :scope_id
            AND filename_hash = :filename_hash
            AND version = :version
        """

      await _call(cursor.execute, query, params)
      row = await _call(cursor.fetchone)
      if row is None:
        return None

      payload_kind = row[0]
      payload = _to_bytes(await _read_lob(row[1]))
      mime_type = row[2]
      return _payload_to_part(
          payload_kind=payload_kind,
          payload=payload,
          mime_type=mime_type,
      )
    finally:
      if cursor is not None:
        await _close(cursor)
      await _close(connection)

  @override
  async def list_artifact_keys(
      self, *, app_name: str, user_id: str, session_id: str | None = None
  ) -> list[str]:
    app_name = _validate_non_empty(app_name, "app_name")
    user_id = _validate_non_empty(user_id, "user_id")
    scope_type, scope_id = _scope_type_and_id(session_id)
    artifacts_table = self._artifacts_table_name()

    await self._ensure_schema()
    connection = await create_oracle_connection(self._config)
    cursor = None
    try:
      cursor = await _call(connection.cursor)
      params = {
          "app_name": app_name,
          "user_id": user_id,
          "user_scope_type": _ARTIFACT_USER_SCOPE,
          "user_scope_id": _USER_SCOPE_ID,
      }
      if scope_type == _ARTIFACT_SESSION_SCOPE:
        params["session_scope_type"] = scope_type
        params["session_scope_id"] = scope_id
        query = f"""
          SELECT DISTINCT filename
          FROM {artifacts_table}
          WHERE app_name = :app_name
            AND user_id = :user_id
            AND (
              (
                scope_type = :session_scope_type
                AND scope_id = :session_scope_id
              )
              OR (
                scope_type = :user_scope_type
                AND scope_id = :user_scope_id
              )
            )
          ORDER BY filename ASC
        """
      else:
        query = f"""
          SELECT DISTINCT filename
          FROM {artifacts_table}
          WHERE app_name = :app_name
            AND user_id = :user_id
            AND scope_type = :user_scope_type
            AND scope_id = :user_scope_id
          ORDER BY filename ASC
        """

      await _call(cursor.execute, query, params)
      rows = await _call(cursor.fetchall)
      return [row[0] for row in rows]
    finally:
      if cursor is not None:
        await _close(cursor)
      await _close(connection)

  @override
  async def delete_artifact(
      self,
      *,
      app_name: str,
      user_id: str,
      filename: str,
      session_id: str | None = None,
  ) -> None:
    app_name = _validate_non_empty(app_name, "app_name")
    user_id = _validate_non_empty(user_id, "user_id")
    filename = _validate_non_empty(filename, "filename")
    scope_type, scope_id = _artifact_scope_type_and_id(
        filename=filename,
        session_id=session_id,
    )
    filename_hash = _filename_hash(filename)
    artifacts_table = self._artifacts_table_name()

    await self._ensure_schema()
    connection = await create_oracle_connection(self._config)
    cursor = None
    try:
      cursor = await _call(connection.cursor)
      await _call(
          cursor.execute,
          f"""
          DELETE FROM {artifacts_table}
          WHERE app_name = :app_name
            AND user_id = :user_id
            AND scope_type = :scope_type
            AND scope_id = :scope_id
            AND filename_hash = :filename_hash
            AND filename = :filename
          """,
          {
              "app_name": app_name,
              "user_id": user_id,
              "scope_type": scope_type,
              "scope_id": scope_id,
              "filename_hash": filename_hash,
              "filename": filename,
          },
      )
      await _call(connection.commit)
    except BaseException:
      await _rollback(connection)
      raise
    finally:
      if cursor is not None:
        await _close(cursor)
      await _close(connection)

  @override
  async def list_versions(
      self,
      *,
      app_name: str,
      user_id: str,
      filename: str,
      session_id: str | None = None,
  ) -> list[int]:
    app_name = _validate_non_empty(app_name, "app_name")
    user_id = _validate_non_empty(user_id, "user_id")
    filename = _validate_non_empty(filename, "filename")
    scope_type, scope_id = _artifact_scope_type_and_id(
        filename=filename,
        session_id=session_id,
    )
    filename_hash = _filename_hash(filename)
    artifacts_table = self._artifacts_table_name()

    await self._ensure_schema()
    connection = await create_oracle_connection(self._config)
    cursor = None
    try:
      cursor = await _call(connection.cursor)
      await _call(
          cursor.execute,
          f"""
          SELECT version
          FROM {artifacts_table}
          WHERE app_name = :app_name
            AND user_id = :user_id
            AND scope_type = :scope_type
            AND scope_id = :scope_id
            AND filename_hash = :filename_hash
            AND filename = :filename
          ORDER BY version ASC
          """,
          {
              "app_name": app_name,
              "user_id": user_id,
              "scope_type": scope_type,
              "scope_id": scope_id,
              "filename_hash": filename_hash,
              "filename": filename,
          },
      )
      rows = await _call(cursor.fetchall)
      return [int(row[0]) for row in rows]
    finally:
      if cursor is not None:
        await _close(cursor)
      await _close(connection)

  @override
  async def list_artifact_versions(
      self,
      *,
      app_name: str,
      user_id: str,
      filename: str,
      session_id: str | None = None,
  ) -> list[ArtifactVersion]:
    app_name = _validate_non_empty(app_name, "app_name")
    user_id = _validate_non_empty(user_id, "user_id")
    filename = _validate_non_empty(filename, "filename")
    scope_type, scope_id = _artifact_scope_type_and_id(
        filename=filename,
        session_id=session_id,
    )
    filename_hash = _filename_hash(filename)
    artifacts_table = self._artifacts_table_name()

    await self._ensure_schema()
    connection = await create_oracle_connection(self._config)
    cursor = None
    try:
      cursor = await _call(connection.cursor)
      await _call(
          cursor.execute,
          f"""
          SELECT version, canonical_uri, custom_metadata, create_time, mime_type
          FROM {artifacts_table}
          WHERE app_name = :app_name
            AND user_id = :user_id
            AND scope_type = :scope_type
            AND scope_id = :scope_id
            AND filename_hash = :filename_hash
            AND filename = :filename
          ORDER BY version ASC
          """,
          {
              "app_name": app_name,
              "user_id": user_id,
              "scope_type": scope_type,
              "scope_id": scope_id,
              "filename_hash": filename_hash,
              "filename": filename,
          },
      )
      rows = await _call(cursor.fetchall)
      return [await _artifact_version_from_row(row) for row in rows]
    finally:
      if cursor is not None:
        await _close(cursor)
      await _close(connection)

  @override
  async def get_artifact_version(
      self,
      *,
      app_name: str,
      user_id: str,
      filename: str,
      session_id: str | None = None,
      version: int | None = None,
  ) -> ArtifactVersion | None:
    app_name = _validate_non_empty(app_name, "app_name")
    user_id = _validate_non_empty(user_id, "user_id")
    filename = _validate_non_empty(filename, "filename")
    if version is not None and version < 0:
      raise ValueError("version must be non-negative")

    scope_type, scope_id = _artifact_scope_type_and_id(
        filename=filename,
        session_id=session_id,
    )
    filename_hash = _filename_hash(filename)
    artifacts_table = self._artifacts_table_name()

    await self._ensure_schema()
    connection = await create_oracle_connection(self._config)
    cursor = None
    try:
      cursor = await _call(connection.cursor)
      params: dict[str, Any] = {
          "app_name": app_name,
          "user_id": user_id,
          "scope_type": scope_type,
          "scope_id": scope_id,
          "filename_hash": filename_hash,
          "filename": filename,
      }
      if version is None:
        query = f"""
          SELECT version, canonical_uri, custom_metadata, create_time, mime_type
          FROM (
            SELECT version, canonical_uri, custom_metadata, create_time, mime_type
            FROM {artifacts_table}
            WHERE app_name = :app_name
              AND user_id = :user_id
              AND scope_type = :scope_type
              AND scope_id = :scope_id
              AND filename_hash = :filename_hash
              AND filename = :filename
            ORDER BY version DESC
          )
          WHERE ROWNUM <= 1
        """
      else:
        params["version"] = version
        query = f"""
          SELECT version, canonical_uri, custom_metadata, create_time, mime_type
          FROM {artifacts_table}
          WHERE app_name = :app_name
            AND user_id = :user_id
            AND scope_type = :scope_type
            AND scope_id = :scope_id
            AND filename_hash = :filename_hash
            AND filename = :filename
            AND version = :version
        """

      await _call(cursor.execute, query, params)
      row = await _call(cursor.fetchone)
      if row is None:
        return None
      return await _artifact_version_from_row(row)
    finally:
      if cursor is not None:
        await _close(cursor)
      await _close(connection)
