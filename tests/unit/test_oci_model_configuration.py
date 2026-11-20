"""The OCI ADK connector must omit only unsupported stream usage options."""
from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples"))
from oracle_env import agent_model_from_env


class OciModelConfigurationTest(unittest.TestCase):
  def test_oci_omits_unsupported_stream_options_without_global_param_dropping(self):
    with (
        patch.dict(os.environ, {"GENAI_MODEL": "oci/openai.gpt-oss-120b"}, clear=True),
        patch("google.adk.models.lite_llm.LiteLlm") as constructor,
    ):
      agent_model_from_env()
    constructor.assert_called_once_with(
        model="oci/openai.gpt-oss-120b", additional_drop_params=["stream_options"]
    )

  def test_other_provider_keeps_its_stream_options(self):
    with (
        patch.dict(os.environ, {"GENAI_MODEL": "openai/test-model"}, clear=True),
        patch("google.adk.models.lite_llm.LiteLlm") as constructor,
    ):
      agent_model_from_env()
    constructor.assert_called_once_with(model="openai/test-model")


if __name__ == "__main__":
  unittest.main()
