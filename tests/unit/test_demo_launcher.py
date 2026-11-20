"""Private configuration and credential-free URI construction for the demo."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples"))
from run_oci_demo import build_command, load_demo_environment, service_arguments


class DemoLauncherTest(unittest.TestCase):
  def _config(self):
    return {
        "ORACLE_AI_DB_USER": "test", "ORACLE_AI_DB_PASSWORD": "quote'$ value",
        "ORACLE_AI_DB_DSN": "localhost:1550/test",
        "GENAI_MODEL": "oci/openai.gpt-oss-120b", "EMBEDDING_MODEL": "oci/cohere.embed-v4.0",
        "OCI_REGION": "us-chicago-1", "OCI_USER": "user", "OCI_TENANCY": "tenant",
        "OCI_FINGERPRINT": "fingerprint", "OCI_COMPARTMENT_ID": "compartment",
        "OCI_KEY_FILE": "/private/test-key",
    }

  def test_private_snapshot_round_trips_shell_quoted_values(self):
    config = self._config()
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / "test.env"
      path.write_text("\n".join(k + "=" + shlex.quote(v) for k, v in config.items()))
      path.chmod(0o600)
      self.assertEqual(load_demo_environment(path), config)

  def test_permissive_file_is_rejected(self):
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / "test.env"
      path.write_text("ORACLE_AI_DB_PASSWORD=secret")
      path.chmod(0o644)
      with self.assertRaisesRegex(ValueError, "mode 600"):
        load_demo_environment(path)

  def test_native_oci_requires_signing_configuration(self):
    config = self._config()
    del config["OCI_REGION"]
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / "test.env"
      path.write_text("\n".join(k + "=" + shlex.quote(v) for k, v in config.items()))
      path.chmod(0o600)
      with self.assertRaisesRegex(ValueError, "OCI_REGION"):
        load_demo_environment(path)

  def test_all_three_uris_use_isolated_prefix_without_credentials(self):
    arguments = service_arguments(self._config(), "adk_demo_test")
    self.assertEqual(arguments, [
        "--session_service_uri", "oracle://?table_prefix=ADK_DEMO_TEST",
        "--memory_service_uri", "oracle://?memory_table_prefix=ADK_DEMO_TEST_MEM",
        "--artifact_service_uri", "oracle://?artifact_table_prefix=ADK_DEMO_TEST_ART",
    ])
    self.assertNotIn(self._config()["ORACLE_AI_DB_PASSWORD"], " ".join(arguments))

  def test_web_and_cli_share_the_same_service_configuration(self):
    namespace = argparse.Namespace(command="web", host="127.0.0.1", port=8000,
        table_prefix=None, agent="oracle_travel_agent", query=None)
    web = build_command(namespace, self._config())
    namespace.command = "run"
    namespace.query = "hello"
    cli = build_command(namespace, self._config())
    for flag in ("--session_service_uri", "--memory_service_uri", "--artifact_service_uri"):
      self.assertIn(flag, web)
      self.assertIn(flag, cli)
    self.assertEqual(cli[-1], "hello")

  def test_invalid_prefix_is_rejected(self):
    with self.assertRaisesRegex(ValueError, "Oracle identifier"):
      service_arguments(self._config(), "bad-prefix")


class DemoRecallToolTest(unittest.IsolatedAsyncioTestCase):
  def _tools(self):
    import importlib.util
    path = Path(__file__).resolve().parents[2] / "examples/oracle_travel_agent/tools.py"
    spec = importlib.util.spec_from_file_location("demo_recall_tools", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

  async def test_blank_recall_query_searches_general_preferences(self):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    context = SimpleNamespace(search_memory=AsyncMock(return_value=SimpleNamespace(memories=[])))
    tools = self._tools()
    for query in ("", "  "):
      result = await tools.recall_travel_preferences(query, context)
      self.assertEqual(result["query"], "travel preferences")
      context.search_memory.assert_awaited_with("travel preferences")

  async def test_explicit_recall_query_is_preserved(self):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    context = SimpleNamespace(search_memory=AsyncMock(return_value=SimpleNamespace(memories=[])))
    result = await self._tools().recall_travel_preferences("  garden walks  ", context)
    self.assertEqual(result["query"], "garden walks")
    context.search_memory.assert_awaited_once_with("garden walks")


if __name__ == "__main__":
  unittest.main()
