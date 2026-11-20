"""Real-Oracle reproductions for the 2026-11-13 Proofread findings."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from google.adk.events.event import Event
from google.genai import types
import oracledb
import pytest

from adk_oracledb.sessions import OracleSessionService, OracleSessionServiceConfig
from adk_oracledb.sessions import service as sessions_module

pytestmark = pytest.mark.oracle


def _connect():
  connection = oracledb.connect(user=os.environ["ORACLE_AI_DB_USER"],
      password=os.environ["ORACLE_AI_DB_PASSWORD"], dsn=os.environ["ORACLE_AI_DB_DSN"],
      tcp_connect_timeout=10)
  connection.call_timeout = 10000
  return connection


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["text", "binary"])
async def test_review_empty_artifact_round_trip(oracle_functional_environment, kind):
  environment = oracle_functional_environment
  service = environment.artifact_service
  part = (types.Part.from_text(text="") if kind == "text" else
          types.Part.from_bytes(data=b"", mime_type="application/octet-stream"))
  filename = "empty." + kind
  for version in (0, 1):
    assert await service.save_artifact(app_name="review", user_id="alice",
        session_id="session", filename=filename, artifact=part) == version
    loaded = await service.load_artifact(app_name="review", user_id="alice",
        session_id="session", filename=filename, version=version)
    assert loaded is not None
    if kind == "text":
      assert loaded.text == ""
    else:
      assert loaded.inline_data is not None and loaded.inline_data.data == b""
  assert await service.list_versions(app_name="review", user_id="alice",
      session_id="session", filename=filename) == [0, 1]
  with _connect() as connection:
    with connection.cursor() as cursor:
      cursor.execute(
          f"SELECT content_size, DBMS_LOB.GETLENGTH(payload_blob), "
          f"CASE WHEN payload_blob IS NULL THEN 1 ELSE 0 END "
          f"FROM {environment.prefix}_ARTIFACTS ORDER BY version")
      assert cursor.fetchall() == [(0, 0, 0), (0, 0, 0)]


@pytest.mark.asyncio
async def test_review_session_initializer_while_event_write_is_uncommitted(
    oracle_functional_environment, record_property,
):
  environment = oracle_functional_environment
  await environment.session_service.create_session(
      app_name="review", user_id="alice", session_id="session")
  prefix = environment.prefix
  statements = []

  class RecordingCursor:
    def __init__(self, cursor):
      self.cursor = cursor
    def execute(self, statement, *args, **kwargs):
      statements.append(statement)
      try:
        return self.cursor.execute(statement, *args, **kwargs)
      except oracledb.Error as exc:
        exc.add_note("Initializer SQL: " + statement.split("(", 1)[0].strip())
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

  async def bounded_connection(config):
    connection = _connect()
    with connection.cursor() as cursor:
      cursor.execute("ALTER SESSION SET ddl_lock_timeout = 1")
    return RecordingConnection(connection)

  event = Event(id="pending-event", invocation_id="review", author="user",
      content=types.Content(role="user", parts=[types.Part.from_text(text="pending")]))
  writer = _connect()
  try:
    with writer.cursor() as cursor:
      cursor.execute(
          f"INSERT INTO {prefix}_EVENTS "
          "(app_name,user_id,session_id,event_id,event_ts,event_json) "
          "VALUES ('review','alice','session',:id,:stamp,:payload)",
          id=event.id, stamp=datetime.now(timezone.utc), payload=event.model_dump_json())
    # Independently reproduce the index-specific contention reported by review.
    with _connect() as probe:
      with probe.cursor() as cursor:
        cursor.execute("ALTER SESSION SET ddl_lock_timeout = 1")
        with pytest.raises(oracledb.DatabaseError) as blocked:
          cursor.execute(f"CREATE INDEX {prefix}_EVENTS_ORDER_IX ON "
                         f"{prefix}_EVENTS (app_name,user_id,session_id,event_ts,event_id)")
        record_property("existing_index_ddl_error", blocked.value.args[0].code)
        assert blocked.value.args[0].code == 54
    service = OracleSessionService(OracleSessionServiceConfig(
        user=os.environ["ORACLE_AI_DB_USER"], password=os.environ["ORACLE_AI_DB_PASSWORD"],
        dsn=os.environ["ORACLE_AI_DB_DSN"], table_prefix=prefix))
    with (
        patch.object(sessions_module, "create_oracle_connection", bounded_connection),
        patch.object(service, "_uses_async_connections", return_value=False),
    ):
      await service._initialize_schema()
    assert not any(s.lstrip().upper().startswith("CREATE INDEX") for s in statements)
    with _connect() as observer:
      with observer.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {prefix}_EVENTS")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT COUNT(*) FROM user_indexes WHERE index_name=:name",
                       name=prefix + "_EVENTS_ORDER_IX")
        assert cursor.fetchone()[0] == 1
    writer.commit()
    with _connect() as observer:
      with observer.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {prefix}_EVENTS")
        assert cursor.fetchone()[0] == 1
  finally:
    writer.rollback()
    writer.close()


THICK_PROBE = "import asyncio, json, os, sys, threading\nfrom unittest.mock import patch\nimport oracledb\noracledb.init_oracle_client()\nfrom adk_oracledb.connection import OracleConnectionFactory\nfrom adk_oracledb.sessions import OracleSessionService, OracleSessionServiceConfig\nfrom adk_oracledb.artifacts import OracleArtifactService, OracleArtifactServiceConfig\nfrom google.adk.events.event import Event\nfrom google.genai import types\nassert not oracledb.is_thin_mode()\nassert hasattr(oracledb, \"connect_async\") and hasattr(oracledb, \"create_pool_async\")\noperation, prefix = sys.argv[1:]\nconfig = dict(user=os.environ[\"ORACLE_AI_DB_USER\"], password=os.environ[\"ORACLE_AI_DB_PASSWORD\"],\n              dsn=os.environ[\"ORACLE_AI_DB_DSN\"], table_prefix=prefix)\nloop_thread = threading.get_ident()\nconnection_threads = []\noriginal_connect = oracledb.connect\ndef tracked_connect(**kwargs):\n    connection_threads.append(threading.get_ident())\n    return original_connect(**kwargs)\nasync def main():\n    factory = OracleConnectionFactory(OracleSessionServiceConfig(**config))\n    if operation == \"connection\":\n        connection = await factory.create_connection()\n        try:\n            with connection.cursor() as cursor:\n                cursor.execute(\"SELECT 1 FROM dual\")\n                assert cursor.fetchone()[0] == 1\n        finally:\n            connection.close()\n        assert not factory.supports_async_connections\n    elif operation == \"pool\":\n        pool = await factory.create_pool()\n        try:\n            with pool.acquire() as connection:\n                with connection.cursor() as cursor:\n                    cursor.execute(\"SELECT 1 FROM dual\")\n                    assert cursor.fetchone()[0] == 1\n        finally:\n            pool.close()\n        assert not factory.supports_async\n    elif operation == \"session\":\n        service = OracleSessionService(OracleSessionServiceConfig(**config))\n        with patch.object(oracledb, \"connect\", tracked_connect):\n            session = await service.create_session(app_name=\"review\", user_id=\"alice\", state={\"count\": 1})\n            await service.append_event(session, Event(\n                id=\"event\", invocation_id=\"review\", author=\"user\",\n                content=types.Content(role=\"user\", parts=[types.Part.from_text(text=\"thick-mode event\")])))\n            loaded = await service.get_session(app_name=\"review\", user_id=\"alice\", session_id=session.id)\n        assert loaded is not None and loaded.state[\"count\"] == 1 and len(loaded.events) == 1\n        assert not service._uses_async_connections()\n        assert connection_threads and all(t != loop_thread for t in connection_threads)\n    else:\n        service = OracleArtifactService(OracleArtifactServiceConfig(**config))\n        with patch.object(oracledb, \"connect\", tracked_connect):\n            for filename, data in ((\"binary.bin\", b\"thick-mode data\"), (\"empty.bin\", b\"\")):\n                assert await service.save_artifact(app_name=\"review\", user_id=\"alice\",\n                    session_id=\"session\", filename=filename,\n                    artifact=types.Part.from_bytes(data=data, mime_type=\"application/octet-stream\")) == 0\n                loaded = await service.load_artifact(app_name=\"review\", user_id=\"alice\",\n                    session_id=\"session\", filename=filename)\n                assert loaded is not None and loaded.inline_data.data == data\n        assert not service._uses_async_connections()\n        assert connection_threads and all(t != loop_thread for t in connection_threads)\nasyncio.run(main())\nprint(json.dumps({\"thin\": oracledb.is_thin_mode(), \"client_version\": oracledb.clientversion(),\n                  \"operation\": operation, \"success\": True}))\n"


@pytest.mark.parametrize("operation", ["connection", "pool", "session", "artifact"])
def test_review_real_thick_mode(oracle_functional_environment, operation, record_property):
  environment = os.environ.copy()
  root = Path(__file__).resolve().parents[2]
  environment["PYTHONPATH"] = str(root / "src")
  completed = subprocess.run(
      [sys.executable, "-B", "-c", THICK_PROBE, operation, oracle_functional_environment.prefix],
      env=environment, capture_output=True, text=True, timeout=60,
  )
  assert completed.returncode == 0, completed.stdout + completed.stderr
  result = json.loads(completed.stdout.splitlines()[-1])
  assert result["thin"] is False and result["success"] is True
  record_property("oracle_client_version", result["client_version"])
