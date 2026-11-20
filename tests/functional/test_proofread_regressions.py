"""Database regressions for the four code findings in the ADK Proofread report.

Set ORACLE_AI_DB_USER, ORACLE_AI_DB_PASSWORD, and ORACLE_AI_DB_DSN before
running this module with pytest.
Memory storage is real; embeddings are deterministic and local to these tests.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import os
import re
from unittest.mock import patch
import uuid

import numpy as np
import oracledb
import pytest

from adk_oracledb.artifacts import OracleArtifactService, OracleArtifactServiceConfig
from adk_oracledb.artifacts import service as artifact_module
from adk_oracledb.memory import OracleMemoryService, OracleMemoryServiceConfig
import conftest as functional_fixtures
import test_memory as memory_cases


pytestmark = pytest.mark.oracle


@dataclass(frozen=True)
class DatabaseSettings:
  user: str = field(repr=False)
  password: str = field(repr=False)
  dsn: str = field(repr=False)

  def kwargs(self):
    return {"user": self.user, "password": self.password, "dsn": self.dsn}

  def connect(self):
    connection = oracledb.connect(**self.kwargs(), tcp_connect_timeout=10)
    connection.call_timeout = 10000
    return connection


@pytest.fixture
def settings():
  names = ("ORACLE_AI_DB_USER", "ORACLE_AI_DB_PASSWORD", "ORACLE_AI_DB_DSN")
  if not all(os.environ.get(name) for name in names):
    pytest.skip("Set ORACLE_AI_DB_USER, ORACLE_AI_DB_PASSWORD, and ORACLE_AI_DB_DSN")
  return DatabaseSettings(*(os.environ[name] for name in names))


@pytest.fixture
def database(settings):
  with settings.connect() as connection:
    yield connection


def _prefix():
  # No SQL LIKE metacharacters; the helper under test uses prefix matching.
  return "ADKPR" + uuid.uuid4().hex[:10].upper()


def _tables(connection, prefix):
  with connection.cursor() as cursor:
    cursor.execute(
        "SELECT table_name FROM user_tables WHERE table_name LIKE :prefix",
        prefix=prefix + "%",
    )
    return [row[0] for row in cursor.fetchall()]


def _cleanup(connection, prefix):
  if not re.fullmatch(r"ADKPR[0-9A-F]{10}", prefix):
    raise AssertionError("Cleanup requires an exact generated test prefix")
  connection.rollback()
  names = _tables(connection, prefix)
  with connection.cursor() as cursor:
    for name in names:
      # OracleAgentMemory appends names directly, without an underscore.
      if not re.fullmatch(re.escape(prefix) + r"[A-Z0-9_]*", name):
        raise AssertionError("Unexpected object name in this test's namespace")
      cursor.execute(f"DROP TABLE {name} CASCADE CONSTRAINTS PURGE")


@pytest.fixture
def artifacts(settings, database):
  prefix = _prefix()
  assert not _tables(database, prefix)
  service = OracleArtifactService(
      OracleArtifactServiceConfig(**settings.kwargs(), table_prefix=prefix)
  )
  try:
    asyncio.run(service._ensure_schema())
    yield service, prefix
  finally:
    _cleanup(database, prefix)


def _insert(connection, prefix, filename="regression.txt", kind="TEXT", version=0):
  with connection.cursor() as cursor:
    cursor.setinputsizes(payload=oracledb.DB_TYPE_BLOB)
    cursor.execute(
        f"INSERT INTO {prefix}_ARTIFACTS "
        "(app_name, user_id, scope_type, scope_id, session_id, filename, "
        "filename_hash, version, payload_kind, mime_type, payload_blob, canonical_uri) "
        "VALUES (:app, :user_id, 'SESSION', :scope_id, :scope_id, :filename, "
        ":digest, :version, :kind, 'text/plain', :payload, :uri)",
        app="a" * 255,
        user_id="u" * 255,
        scope_id="s" * 255,
        filename=filename,
        digest=hashlib.sha256(filename.encode()).hexdigest(),
        version=version,
        kind=kind,
        payload=b"regression payload",
        uri="artifact://proofread/regression",
    )


def test_artifact_schema_on_8kb_al32utf8(artifacts, database, record_property):
  """Execute the actual initializer and inspect its real Oracle indexes."""
  _, prefix = artifacts
  with database.cursor() as cursor:
    cursor.execute(
        "SELECT value FROM nls_database_parameters "
        "WHERE parameter = 'NLS_CHARACTERSET'"
    )
    charset = cursor.fetchone()[0]
    cursor.execute(
        "SELECT t.block_size FROM user_indexes i "
        "JOIN user_tablespaces t ON t.tablespace_name = i.tablespace_name "
        "WHERE i.index_name = :name",
        name=f"{prefix}_ARTIFACTS_LATEST_IX",
    )
    block_size = cursor.fetchone()[0]
    cursor.execute(
        "SELECT index_name FROM user_indexes WHERE table_name = :name",
        name=f"{prefix}_ARTIFACTS",
    )
    indexes = {row[0] for row in cursor.fetchall()}
  record_property("oracle_charset", charset)
  record_property("oracle_index_block_size", block_size)
  assert f"{prefix}_ARTIFACTS_LATEST_IX" in indexes
  assert f"{prefix}_ARTIFACTS_KEYS_IX" not in indexes
  if (charset, block_size) != ("AL32UTF8", 8192):
    pytest.skip("Exact 8 KB AL32UTF8 case requires that database configuration")


@pytest.mark.parametrize("character", ["x", "\u754c"], ids=["ascii", "multibyte"])
def test_full_length_filename_can_be_stored(artifacts, database, character):
  """A 1024-character filename must remain storable with full-width scopes.

  This tests the schema directly. Canonical URI encoding is a separate concern.
  """
  _, prefix = artifacts
  filename = character * 1024
  _insert(database, prefix, filename=filename)
  with database.cursor() as cursor:
    cursor.execute(f"SELECT filename, LENGTH(filename) FROM {prefix}_ARTIFACTS")
    stored, length = cursor.fetchone()
  assert stored == filename
  assert length == 1024


def test_payload_kind_constraint_remains_enabled(artifacts, database):
  _, prefix = artifacts
  with database.cursor() as cursor:
    cursor.execute(
        "SELECT status FROM user_constraints WHERE constraint_name = :name",
        name=f"{prefix}_ARTIFACTS_KIND_CK",
    )
    assert cursor.fetchone()[0] == "ENABLED"
  with pytest.raises(oracledb.DatabaseError) as caught:
    _insert(database, prefix, kind="INVALID")
  assert caught.value.args[0].code == 2290
  assert f"{prefix}_ARTIFACTS_KIND_CK" in str(caught.value)


def test_second_initializer_tolerates_an_uncommitted_write(
    artifacts, database, settings,
):
  """A separate service can start while another session holds a DML lock."""
  _, prefix = artifacts
  statements = []

  class RecordingCursor:
    def __init__(self, cursor):
      self.cursor = cursor

    def execute(self, statement, *args, **kwargs):
      statements.append(statement)
      try:
        return self.cursor.execute(statement, *args, **kwargs)
      except oracledb.Error as error:
        error.add_note("Initializer statement: " + statement.split("(", 1)[0].strip())
        raise

    def __getattr__(self, name):
      return getattr(self.cursor, name)

  class RecordingConnection:
    def __init__(self, connection):
      self.connection = connection

    def cursor(self):
      return RecordingCursor(self.connection.cursor())

    def __getattr__(self, name):
      return getattr(self.connection, name)

  async def connect_with_bounded_ddl_wait(config):
    connection = settings.connect()
    with connection.cursor() as cursor:
      cursor.execute("ALTER SESSION SET ddl_lock_timeout = 1")
    return RecordingConnection(connection)

  _insert(database, prefix)
  try:
    new_service = OracleArtifactService(
        OracleArtifactServiceConfig(**settings.kwargs(), table_prefix=prefix)
    )
    with (
        patch.object(artifact_module, "create_oracle_connection", connect_with_bounded_ddl_wait),
        patch.object(OracleArtifactService, "_uses_async_connections", return_value=False),
    ):
      asyncio.run(new_service._ensure_schema())
    assert statements
    assert not any(
        re.match(r"\s*(ALTER|DROP)\s+TABLE\b", statement, re.I)
        for statement in statements
    )
    with settings.connect() as observer:
      with observer.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {prefix}_ARTIFACTS")
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT status FROM user_constraints WHERE constraint_name = :name",
            name=f"{prefix}_ARTIFACTS_KIND_CK",
        )
        assert cursor.fetchone()[0] == "ENABLED"
    database.commit()
    with settings.connect() as observer:
      with observer.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {prefix}_ARTIFACTS")
        assert cursor.fetchone()[0] == 1
  finally:
    database.rollback()


@pytest.mark.parametrize("table_count", [0, 1, 3])
def test_memory_cleanup_removes_all_matching_tables(database, table_count):
  """Exercise the actual fixture helper, including empty and multi-row results."""
  prefix, neighbor = _prefix(), _prefix()
  try:
    with database.cursor() as cursor:
      for index in range(table_count):
        cursor.execute(f"CREATE TABLE {prefix}_T{index} (id NUMBER)")
      cursor.execute(f"CREATE TABLE {neighbor}_KEEP (id NUMBER)")
    assert len(_tables(database, prefix)) == table_count
    functional_fixtures._drop_memory_tables(prefix)
    assert _tables(database, prefix) == []
    assert _tables(database, neighbor) == [f"{neighbor}_KEEP"]
  finally:
    _cleanup(database, prefix)
    _cleanup(database, neighbor)


@pytest.mark.asyncio
async def test_original_concurrent_memory_case_uses_one_real_client(
    settings, database, monkeypatch,
):
  """Run the repaired test against real Oracle storage with local embeddings."""
  from oracleagentmemory.core.embedders.embedder import Embedder

  class LocalEmbedder(Embedder):
    def embed(self, texts, *, is_query=False):
      vectors = np.zeros((len(texts), 64), dtype=np.float32)
      for row, text in enumerate(texts):
        for word in re.findall(r"\w+", text.lower()):
          bucket = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4]) % 64
          vectors[row, bucket] += 1
        norm = np.linalg.norm(vectors[row])
        if norm:
          vectors[row] /= norm
        else:
          vectors[row, 0] = 1
      return vectors

    async def embed_async(self, texts, *, is_query=False):
      return self.embed(texts, is_query=is_query)

  prefix = _prefix()
  assert not _tables(database, prefix)
  service = OracleMemoryService(
      OracleMemoryServiceConfig(
          **settings.kwargs(),
          table_name_prefix=prefix,
          embedder_model="local-regression-64",
          extract_memories=False,
      )
  )
  monkeypatch.setattr(
      service, "_build_embedder", lambda cls: LocalEmbedder("local-regression-64")
  )
  initializations = []
  create_client = service._create_client_sync

  def counted_create_client():
    initializations.append(True)
    return create_client()

  monkeypatch.setattr(service, "_create_client_sync", counted_create_client)
  try:
    await memory_cases.test_memory_client_initialization_is_shared_across_concurrent_calls(
        (service, prefix)
    )
    assert len(initializations) == 1
    assert _tables(database, prefix)
  finally:
    if service._pool is not None:
      service._pool.close(force=True)
    try:
      functional_fixtures._drop_memory_tables(prefix)
      assert _tables(database, prefix) == []
    finally:
      _cleanup(database, prefix)
