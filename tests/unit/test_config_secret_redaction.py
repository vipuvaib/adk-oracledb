"""Secrets stay redacted until an Oracle/provider transport needs their value."""
from __future__ import annotations

import json
import importlib.util
import logging
from pathlib import Path
from secrets import token_urlsafe
from types import SimpleNamespace
from unittest.mock import Mock

from pydantic import SecretStr, ValidationError
import pytest

from adk_oracledb import connection as connection_module
from adk_oracledb.artifacts import OracleArtifactServiceConfig
from adk_oracledb.memory import OracleMemoryService, OracleMemoryServiceConfig
from adk_oracledb.memory import service as memory_module
from adk_oracledb.sessions import OracleSessionServiceConfig


CONFIGS = (OracleSessionServiceConfig, OracleArtifactServiceConfig, OracleMemoryServiceConfig)


@pytest.fixture(params=CONFIGS, ids=lambda cls: cls.__name__)
def config_case(request):
  values = {"user": "test_user", "password": token_urlsafe(24), "dsn": "localhost/test"}
  if request.param is OracleMemoryServiceConfig:
    values.update(embedder_model="test/embedding", llm_model="test/chat",
                  embedder_api_key=token_urlsafe(24), llm_api_key=token_urlsafe(24))
  return request.param, values


def _secret_fields(values):
  return {name: values[name] for name in ("password", "embedder_api_key", "llm_api_key")
          if values.get(name) is not None}


def _assert_redacted(config, values):
  rendered = (str(config), repr(config), repr(config.model_dump()),
              json.dumps(config.model_dump(mode="json")), config.model_dump_json())
  payload = json.loads(config.model_dump_json())
  for name, value in _secret_fields(values).items():
    assert all(value not in output for output in rendered)
    assert payload[name] == "**********"
    assert isinstance(getattr(config, name), SecretStr)
    assert getattr(config, name).get_secret_value() == value


def test_config_output_and_logging_redact_credentials(config_case, caplog):
  cls, values = config_case
  config = cls(**values)
  _assert_redacted(config, values)
  with caplog.at_level(logging.INFO):
    logging.getLogger(__name__).info("Settings: %s; fields: %s", config, config.model_dump())
  for value in _secret_fields(values).values():
    assert value not in caplog.text


def test_assigned_credentials_remain_secret_values(config_case):
  cls, values = config_case
  config = cls(**values)
  values = dict(values)
  for name in _secret_fields(values):
    values[name] = token_urlsafe(24)
    setattr(config, name, values[name])
  _assert_redacted(config, values)


@pytest.mark.parametrize("invalid", ["pool_bounds", "pool_type", "missing_user", "password_type"])
@pytest.mark.parametrize("method", ["constructor", "model_validate", "model_validate_json"])
def test_validation_errors_do_not_expose_credential_inputs(config_case, invalid, method, caplog):
  cls, values = config_case
  invalid_values = dict(values)
  if invalid == "pool_bounds":
    invalid_values.update(pool_min=4, pool_max=1)
  elif invalid == "pool_type":
    invalid_values["pool_min"] = "not-an-integer"
  elif invalid == "missing_user":
    invalid_values.pop("user")
  else:
    invalid_values["password"] = {"unexpected": values["password"]}
  with pytest.raises(ValidationError) as caught:
    if method == "constructor":
      cls(**invalid_values)
    elif method == "model_validate":
      cls.model_validate(invalid_values)
    else:
      cls.model_validate_json(json.dumps(invalid_values))
  error = caught.value
  rendered = (str(error), repr(error), repr(error.errors()), error.json())
  with caplog.at_level(logging.ERROR):
    logging.getLogger(__name__).error("Configuration rejected: %s; details: %s", error, error.errors())
  for value in _secret_fields(values).values():
    assert all(value not in output for output in rendered)
    assert value not in caplog.text
  assert error.errors()
  assert any(record["loc"] or invalid == "pool_bounds" for record in error.errors())


@pytest.mark.asyncio
@pytest.mark.parametrize("thin", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("operation", ["connection", "pool"])
async def test_oracle_transport_receives_original_password(config_case, thin, operation, monkeypatch):
  cls, values = config_case
  config = cls(**values)
  sentinel = object()
  driver = SimpleNamespace(is_thin_mode=lambda: thin,
      connect=Mock(return_value=sentinel), connect_async=Mock(return_value=sentinel),
      create_pool=Mock(return_value=sentinel), create_pool_async=Mock(return_value=sentinel))
  monkeypatch.setattr(connection_module, "_load_oracledb", lambda: driver)
  factory = connection_module.OracleConnectionFactory(config)
  if operation == "connection":
    assert await factory.create_connection() is sentinel
    call = driver.connect_async if thin else driver.connect
  else:
    assert await factory.create_pool() is sentinel
    call = driver.create_pool_async if thin else driver.create_pool
  call.assert_called_once()
  assert type(call.call_args.kwargs["password"]) is str
  assert call.call_args.kwargs["password"] == values["password"]


def test_memory_pool_receives_original_password(monkeypatch):
  password = token_urlsafe(24)
  config = OracleMemoryServiceConfig(user="test", password=password, dsn="localhost/test")
  create_pool = Mock(return_value=object())
  monkeypatch.setattr(memory_module, "_load_oracledb", lambda: SimpleNamespace(create_pool=create_pool))
  OracleMemoryService(config)._create_pool_sync()
  assert type(create_pool.call_args.kwargs["password"]) is str
  assert create_pool.call_args.kwargs["password"] == password


def test_query_document_embedders_and_llm_receive_original_keys():
  embedding_key, llm_key = token_urlsafe(24), token_urlsafe(24)
  config = OracleMemoryServiceConfig(user="test", password=token_urlsafe(24), dsn="localhost/test",
      embedder_model="test/embedding", llm_model="test/chat",
      embedder_api_key=embedding_key, llm_api_key=llm_key,
      embedder_query_input_type="search_query", embedder_document_input_type="search_document")
  service = OracleMemoryService(config)
  embedder, llm = Mock(), Mock()
  service._build_embedder(embedder)
  service._build_llm(llm)
  assert embedder.call_count == 2
  for call in embedder.call_args_list:
    assert type(call.kwargs["api_key"]) is str
    assert call.kwargs["api_key"] == embedding_key
  assert llm.call_args.kwargs["api_key"] == llm_key
  assert type(llm.call_args.kwargs["api_key"]) is str


@pytest.mark.parametrize("key", [None, ""])
def test_optional_provider_keys_preserve_none_and_empty_behavior(key):
  service = OracleMemoryService(OracleMemoryServiceConfig(
      user="test", password=token_urlsafe(24), dsn="localhost/test",
      embedder_model="test/embedding", llm_model="test/chat", embedder_api_key=key, llm_api_key=key))
  embedder, llm = Mock(), Mock()
  service._build_embedder(embedder)
  service._build_llm(llm)
  for constructor in (embedder, llm):
    if key is None:
      assert "api_key" not in constructor.call_args.kwargs
    else:
      assert constructor.call_args.kwargs["api_key"] == key


def test_dotenv_credentials_are_redacted_by_registry_configs(tmp_path, monkeypatch):
  from adk_oracledb.registry import _artifact_config_from_uri
  from adk_oracledb.registry import _memory_config_from_uri
  from adk_oracledb.registry import _session_config_from_uri

  values = {"ORACLE_AI_DB_USER": "test_user", "ORACLE_AI_DB_PASSWORD": token_urlsafe(24),
            "ORACLE_AI_DB_DSN": "localhost/test", "GENAI_MODEL": "test/chat",
            "GENAI_API_KEY": token_urlsafe(24), "EMBEDDING_MODEL": "test/embedding",
            "EMBEDDING_API_KEY": token_urlsafe(24)}
  for name in values:
    # Register restoration even when the variable was originally absent.
    monkeypatch.setenv(name, "")
    monkeypatch.delenv(name)
  path = tmp_path / ".env"
  path.write_text("\n".join(name + "=" + value for name, value in values.items()))
  path.chmod(0o600)
  spec = importlib.util.spec_from_file_location("redaction_oracle_env", Path(__file__).resolve().parents[2] / "examples/oracle_env.py")
  loader = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(loader)
  loader.load_repo_env(tmp_path / "agent.py")

  expected = {"password": values["ORACLE_AI_DB_PASSWORD"]}
  for factory in (_session_config_from_uri, _artifact_config_from_uri, _memory_config_from_uri):
    config = factory("oracle://")
    fields = dict(expected)
    if isinstance(config, OracleMemoryServiceConfig):
      fields.update(embedder_api_key=values["EMBEDDING_API_KEY"], llm_api_key=values["GENAI_API_KEY"])
    _assert_redacted(config, fields)
