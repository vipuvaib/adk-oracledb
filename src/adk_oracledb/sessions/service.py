from __future__ import annotations

import re
from typing import Any

from google.adk.events.event import Event
from google.adk.sessions.base_session_service import BaseSessionService
from google.adk.sessions.base_session_service import GetSessionConfig
from google.adk.sessions.base_session_service import ListSessionsResponse
from google.adk.sessions.session import Session
from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from typing_extensions import override


class OracleSessionServiceConfig(BaseModel):
  """Configuration for Oracle-backed ADK session storage."""

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
    if not re.fullmatch(r"[A-Z0-9_]+", table_prefix):
      raise ValueError(
          "table_prefix must contain only letters, numbers, and underscore"
      )
    return table_prefix


class OracleSessionService(BaseSessionService):
  """Minimal Oracle Database session service skeleton."""

  def __init__(self, config: OracleSessionServiceConfig):
    self._config = config

  @override
  async def create_session(
      self,
      *,
      app_name: str,
      user_id: str,
      state: dict[str, Any] | None = None,
      session_id: str | None = None,
  ) -> Session:
    raise NotImplementedError

  @override
  async def get_session(
      self,
      *,
      app_name: str,
      user_id: str,
      session_id: str,
      config: GetSessionConfig | None = None,
  ) -> Session | None:
    raise NotImplementedError

  @override
  async def list_sessions(
      self, *, app_name: str, user_id: str | None = None
  ) -> ListSessionsResponse:
    raise NotImplementedError

  @override
  async def delete_session(
      self, *, app_name: str, user_id: str, session_id: str
  ) -> None:
    raise NotImplementedError

  @override
  async def append_event(self, session: Session, event: Event) -> Event:
    raise NotImplementedError

  @override
  async def flush(self) -> None:
    pass
