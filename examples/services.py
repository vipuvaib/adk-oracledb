from pathlib import Path
import sys

from adk_oracledb.registry import register_oracle_services

EXAMPLES_DIR = Path(__file__).resolve().parent
if str(EXAMPLES_DIR) not in sys.path:
  sys.path.insert(0, str(EXAMPLES_DIR))

from oracle_env import configure_genai_provider_env
from oracle_env import load_repo_env


load_repo_env(__file__)
configure_genai_provider_env()
register_oracle_services()
