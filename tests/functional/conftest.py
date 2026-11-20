#!/bin/python
#
# $Header: conftest.py 22-jul-2026.21:16:16 dascenci Exp $
#
# conftest.py
#
# Copyright (c) 2026, Oracle and/or its affiliates.
#
#    NAME
#      conftest.py - Shared fixtures for ADK Oracle functional tests
#
#    DESCRIPTION
#      Creates isolated, real-Oracle service configurations and removes the
#      generated schema objects after each functional test.
#
#    NOTES
#      Each test uses an unpredictable table prefix to avoid collisions across
#      Farm reruns and parallel workers.
#
#    MODIFIED   (MM/DD/YY)
#    dascenci    07/22/26 - add ADK functional pytest fixtures
#    dascenci    07/22/26 - Creation
#
"""Fixtures for real-Oracle functional tests.

Each test gets a unique schema prefix so Farm retries can run without sharing
tables.  The fixture drops only tables bearing that generated prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import uuid

import pytest
import os
import oracledb

from adk_oracledb.artifacts import OracleArtifactService
from adk_oracledb.artifacts import OracleArtifactServiceConfig
from adk_oracledb.memory import OracleMemoryService
from adk_oracledb.memory import OracleMemoryServiceConfig
from adk_oracledb.sessions import OracleSessionService
from adk_oracledb.sessions import OracleSessionServiceConfig


@dataclass(frozen=True)
class OracleFunctionalEnvironment:
  """Services and isolated Oracle object prefix for one functional test."""

  prefix: str
  session_service: OracleSessionService
  artifact_service: OracleArtifactService


def _database_config(prefix: str) -> dict[str, object]:
  return {
      "user": os.environ["ORACLE_AI_DB_USER"],
      "password": os.environ["ORACLE_AI_DB_PASSWORD"],
      "dsn": os.environ["ORACLE_AI_DB_DSN"],
      "table_prefix": prefix,
      "auto_create_tables": True,
  }


def _drop_test_tables(prefix: str) -> None:
  """Remove the tables created by one test, in dependency-safe order."""
  import oracledb

  connection = oracledb.connect(
      user=os.environ["ORACLE_AI_DB_USER"],
      password=os.environ["ORACLE_AI_DB_PASSWORD"],
      dsn=os.environ["ORACLE_AI_DB_DSN"],
  )
  try:
    with connection.cursor() as cursor:
      for suffix in ("EVENTS", "SESSIONS", "APP_STATES", "USER_STATES", "ARTIFACTS"):
        try:
          cursor.execute(f"DROP TABLE {prefix}_{suffix} CASCADE CONSTRAINTS PURGE")
        except oracledb.DatabaseError as error:
          if getattr(error.args[0], "code", None) != 942:
            raise
    connection.commit()
  finally:
    connection.close()


@pytest.fixture
def oracle_functional_environment() -> OracleFunctionalEnvironment:
  """Create independent services backed by a disposable real-DB schema."""
  prefix = f"ADKFT{uuid.uuid4().hex[:10].upper()}"
  config = _database_config(prefix)
  environment = OracleFunctionalEnvironment(
      prefix=prefix,
      session_service=OracleSessionService(OracleSessionServiceConfig(**config)),
      artifact_service=OracleArtifactService(OracleArtifactServiceConfig(**config)),
  )
  try:
    yield environment
  finally:
    _drop_test_tables(prefix)


def _memory_config(prefix: str) -> OracleMemoryServiceConfig:
  return OracleMemoryServiceConfig(
      user=os.environ["ORACLE_AI_DB_USER"],
      password=os.environ["ORACLE_AI_DB_PASSWORD"],
      dsn=os.environ["ORACLE_AI_DB_DSN"],
      table_name_prefix=prefix,
      schema_policy="create_if_necessary",
      embedder_model=os.environ["EMBEDDING_MODEL"],
      embedder_api_base=os.environ.get("EMBEDDING_ENDPOINT"),
      embedder_api_key=os.environ.get("EMBEDDING_API_KEY"),
      embedder_encoding_format=os.environ.get("EMBEDDING_ENCODING_FORMAT"),
      embedder_input_type=os.environ.get("EMBEDDING_INPUT_TYPE"),
      embedder_query_input_type=os.environ.get("EMBEDDING_QUERY_INPUT_TYPE"),
      embedder_document_input_type=os.environ.get("EMBEDDING_DOCUMENT_INPUT_TYPE"),
      extract_memories=False,
      search_top_k=10,
  )


def _drop_memory_tables(prefix: str) -> None:
  import oracledb

  connection = oracledb.connect(
      user=os.environ["ORACLE_AI_DB_USER"],
      password=os.environ["ORACLE_AI_DB_PASSWORD"],
      dsn=os.environ["ORACLE_AI_DB_DSN"],
  )
  try:
    with connection.cursor() as cursor:
      cursor.execute(
          "SELECT table_name FROM user_tables WHERE table_name LIKE :prefix",
          prefix=f"{prefix}%",
      )
      for (table_name,) in cursor.fetchall():
        cursor.execute(f"DROP TABLE {table_name} CASCADE CONSTRAINTS PURGE")
    connection.commit()
  finally:
    connection.close()


@pytest.fixture
def memory_functional_service() -> tuple[OracleMemoryService, str]:
  required = (
      "ORACLE_AI_DB_USER",
      "ORACLE_AI_DB_PASSWORD",
      "ORACLE_AI_DB_DSN",
      "EMBEDDING_MODEL",
  )
  missing = [name for name in required if not os.environ.get(name)]
  if missing:
    pytest.skip(
        "real Oracle memory provider is not configured: " + ", ".join(missing)
    )

  prefix = f"ADKFTMEM{uuid.uuid4().hex[:8].upper()}"
  service = OracleMemoryService(_memory_config(prefix))
  try:
    yield service, prefix
  finally:
    pool = getattr(service, "_pool", None)
    if pool is not None:
      pool.close()
    _drop_memory_tables(prefix)

def _connect() -> oracledb.Connection:
  return oracledb.connect(
      user=os.environ["ORACLE_AI_DB_USER"],
      password=os.environ["ORACLE_AI_DB_PASSWORD"],
      dsn=os.environ["ORACLE_AI_DB_DSN"],
  )


def table_names(prefix: str) -> set[str]:
  connection = _connect()
  try:
    with connection.cursor() as cursor:
      cursor.execute(
          "SELECT table_name FROM user_tables WHERE table_name LIKE :prefix",
          prefix=f"{prefix}_%",
      )
      return {row[0] for row in cursor}
  finally:
    connection.close()


def index_names(prefix: str) -> set[str]:
  connection = _connect()
  try:
    with connection.cursor() as cursor:
      cursor.execute(
          "SELECT index_name FROM user_indexes WHERE index_name LIKE :prefix",
          prefix=f"{prefix}_%",
      )
      return {row[0] for row in cursor}
  finally:
    connection.close()


def query_scalar(sql: str, **binds: object) -> object:
  connection = _connect()
  try:
    with connection.cursor() as cursor:
      cursor.execute(sql, binds)
      return cursor.fetchone()[0]
  finally:
    connection.close()