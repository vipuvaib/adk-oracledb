from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any

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


def _scope_type_and_id(session_id: str | None) -> tuple[str, str]:
  if session_id is None:
    return _ARTIFACT_USER_SCOPE, _USER_SCOPE_ID

  session_id = session_id.strip()
  if not session_id:
    return _ARTIFACT_USER_SCOPE, _USER_SCOPE_ID
  return _ARTIFACT_SESSION_SCOPE, session_id


def _validate_non_empty(value: str, name: str) -> str:
  value = value.strip()
  if not value:
    raise ValueError(f"{name} must not be empty")
  return value


def _filename_hash(filename: str) -> str:
  return hashlib.sha256(filename.encode("utf-8")).hexdigest()


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
    raise NotImplementedError(
        "OracleArtifactService.save_artifact is pending artifact storage "
        "wiring."
    )

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
    raise NotImplementedError(
        "OracleArtifactService.load_artifact is pending artifact storage "
        "wiring."
    )

  @override
  async def list_artifact_keys(
      self, *, app_name: str, user_id: str, session_id: str | None = None
  ) -> list[str]:
    raise NotImplementedError(
        "OracleArtifactService.list_artifact_keys is pending artifact storage "
        "wiring."
    )

  @override
  async def delete_artifact(
      self,
      *,
      app_name: str,
      user_id: str,
      filename: str,
      session_id: str | None = None,
  ) -> None:
    raise NotImplementedError(
        "OracleArtifactService.delete_artifact is pending artifact storage "
        "wiring."
    )

  @override
  async def list_versions(
      self,
      *,
      app_name: str,
      user_id: str,
      filename: str,
      session_id: str | None = None,
  ) -> list[int]:
    raise NotImplementedError(
        "OracleArtifactService.list_versions is pending artifact storage "
        "wiring."
    )

  @override
  async def list_artifact_versions(
      self,
      *,
      app_name: str,
      user_id: str,
      filename: str,
      session_id: str | None = None,
  ) -> list[ArtifactVersion]:
    raise NotImplementedError(
        "OracleArtifactService.list_artifact_versions is pending artifact "
        "storage wiring."
    )

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
    raise NotImplementedError(
        "OracleArtifactService.get_artifact_version is pending artifact "
        "storage wiring."
    )
