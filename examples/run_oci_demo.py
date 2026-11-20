"""Launch the existing ADK demos with the private OCI test configuration.

Examples:
  .venv/bin/python examples/run_oci_demo.py
  .venv/bin/python examples/run_oci_demo.py run --agent oracle_travel_agent
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shlex
import stat
import sys
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = Path.home() / ".config/agno-oracle-demo/google-adk-python-test.env"
AGENTS = ("oracle_runtime_agent", "oracle_travel_agent")


def load_demo_environment(path: Path) -> dict[str, str]:
  """Read a private shell-style env snapshot without executing its contents."""
  path = path.expanduser()
  info = path.lstat()
  if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
    raise ValueError("The demo env must be a user-owned regular file with mode 600")
  result = {}
  for number, line in enumerate(path.read_text().splitlines(), start=1):
    fields = shlex.split(line, comments=True)
    if not fields:
      continue
    if fields[0] == "export":
      fields = fields[1:]
    if len(fields) != 1 or "=" not in fields[0]:
      raise ValueError(f"Unsupported demo env syntax on line {number}")
    key, value = fields[0].split("=", 1)
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
      raise ValueError(f"Invalid demo env key on line {number}")
    result[key] = value
  required = ("ORACLE_AI_DB_USER", "ORACLE_AI_DB_PASSWORD", "ORACLE_AI_DB_DSN",
              "GENAI_MODEL", "EMBEDDING_MODEL")
  missing = [name for name in required if not result.get(name)]
  if missing:
    raise ValueError("Missing demo configuration: " + ", ".join(missing))
  if result["GENAI_MODEL"].startswith("oci/") or result["EMBEDDING_MODEL"].startswith("oci/"):
    signing = ("OCI_REGION", "OCI_USER", "OCI_TENANCY", "OCI_FINGERPRINT", "OCI_COMPARTMENT_ID")
    missing = [name for name in signing if not result.get(name)]
    if not (result.get("OCI_KEY_FILE") or result.get("OCI_KEY")):
      missing.append("OCI_KEY_FILE or OCI_KEY")
    if missing:
      raise ValueError("Missing OCI signing configuration: " + ", ".join(missing))
  return result


def service_arguments(config: dict[str, str], prefix: str | None = None) -> list[str]:
  """Build credential-free service URIs while credentials stay in the env."""
  if prefix is not None:
    prefix = prefix.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", prefix):
      raise ValueError("table-prefix must be an Oracle identifier")
  entries = (
      ("session", "table_prefix", prefix or config.get("ORACLE_SESSION_TABLE_PREFIX") or "ADK_OCI_DEMO"),
      ("memory", "memory_table_prefix", (prefix + "_MEM") if prefix else config.get("ORACLE_MEMORY_TABLE_PREFIX") or "ADK_OCI_DEMO_MEM"),
      ("artifact", "artifact_table_prefix", (prefix + "_ART") if prefix else config.get("ORACLE_ARTIFACT_TABLE_PREFIX") or "ADK_OCI_DEMO_ART"),
  )
  result = []
  for service, key, value in entries:
    result.extend(["--" + service + "_service_uri", "oracle://?" + urlencode({key: value})])
  return result


def build_command(args: argparse.Namespace, config: dict[str, str]) -> list[str]:
  arguments = service_arguments(config, args.table_prefix)
  if args.command == "web":
    return ["web", str(ROOT / "examples"), "--host", args.host, "--port", str(args.port),
            "--no-reload", *arguments]
  command = ["run", str(ROOT / "examples" / args.agent), *arguments]
  if args.query is not None:
    command.append(args.query)
  return command


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("command", choices=("web", "run"), nargs="?", default="web")
  parser.add_argument("--env-file", type=Path,
      default=Path(os.environ.get("ADK_DEMO_ENV_FILE", str(DEFAULT_ENV))))
  parser.add_argument("--host", default="127.0.0.1")
  parser.add_argument("--port", type=int, default=8000)
  parser.add_argument("--agent", choices=AGENTS, default="oracle_travel_agent")
  parser.add_argument("--query")
  parser.add_argument("--table-prefix", help="Override demo tables with a separate namespace")
  args = parser.parse_args()
  try:
    config = load_demo_environment(args.env_file)
    command = build_command(args, config)
  except (OSError, ValueError) as exc:
    parser.error(str(exc))
  environment = dict(os.environ)
  environment.update(config)
  environment.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
  environment.setdefault("LITELLM_MODE", "PRODUCTION")
  environment["PYTHONDONTWRITEBYTECODE"] = "1"
  adk = Path(sys.executable).parent / "adk"
  if not adk.is_file():
    parser.error("Run this launcher with the repository .venv/bin/python")
  os.chdir(ROOT)
  print("Oracle demo: " + config["GENAI_MODEL"] + " / " + config["EMBEDDING_MODEL"], flush=True)
  print("Sessions, memory and artifacts use Oracle service factories.", flush=True)
  if args.command == "web":
    print(f"ADK Web: http://{args.host}:{args.port}", flush=True)
  os.execve(str(adk), [str(adk), *command], environment)


if __name__ == "__main__":
  main()
