from __future__ import annotations

from pathlib import Path
from secrets import token_urlsafe
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))

from adk_oracledb.registry import _parse_oracle_uri


class OracleUriParsingTest(unittest.TestCase):

  def test_ipv6_host_is_bracketed_in_generated_dsn(self) -> None:
    password = token_urlsafe(24)
    parsed = _parse_oracle_uri(
        f"oracle://ADK_USER:{password}@[2001:db8::1]:1521/FREEPDB1"
    )

    self.assertEqual(parsed["dsn"], "[2001:db8::1]:1521/FREEPDB1")
    self.assertEqual(parsed["password"], password)

  def test_ipv4_host_is_unchanged_in_generated_dsn(self) -> None:
    password = token_urlsafe(24)
    parsed = _parse_oracle_uri(
        f"oracle://ADK_USER:{password}@192.0.2.10:1521/FREEPDB1"
    )

    self.assertEqual(parsed["dsn"], "192.0.2.10:1521/FREEPDB1")
    self.assertEqual(parsed["password"], password)


if __name__ == "__main__":
  unittest.main()
