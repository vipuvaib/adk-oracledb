#!/bin/python
#
# $Header: test_vector_models.py 23-jul-2026.18:34:30 dascenci Exp $
#
# test_vector_models.py
#
# Copyright (c) 2026, Oracle and/or its affiliates.
#
#    NAME
#      test_vector_models.py - Oracle vector model contract tests
#
#    DESCRIPTION
#      Verifies that the Oracle database exposes the ONNX models, privileges,
#      and tablespace capacity required by vector-backed operations.
#
#    NOTES
#      These tests validate database capabilities through Oracle metadata views;
#      they are independent of any particular test harness or setup script.
#
#    MODIFIED   (MM/DD/YY)
#    dascenci    08/04/26 - fix ADK functional test regressions
#    dascenci    07/23/26 - Add Oracle vector model functional tests
#    dascenci    07/23/26 - Creation
#
"""Real-Oracle validation of vector model database capabilities."""

from __future__ import annotations

import os

import oracledb
import pytest

from conftest import _connect
from conftest import index_names as _index_names
from conftest import query_scalar as _query_scalar
from conftest import table_names as _table_names


pytestmark = pytest.mark.oracle

@pytest.fixture
def db_connection() -> oracledb.Connection:
  connection = _connect()
  try:
    yield connection
  finally:
    connection.close()


def test_loaded_onnx_models_are_visible_to_integration_user(db_connection) -> None:
  """The configured ONNX models are visible to the integration user."""
  with db_connection.cursor() as cursor:
    cursor.execute(
        """
        SELECT model_name
        FROM user_mining_models
        WHERE model_name IN (:first_model, :second_model)
        """,
        first_model="ALLMINILM",
        second_model="ALL_MINILM_L12_V2",
    )
    model_names = {row[0].upper() for row in cursor}

  assert model_names == {"ALLMINILM", "ALL_MINILM_L12_V2"}


def test_integration_user_has_vector_model_and_directory_privileges(
    db_connection,
) -> None:
  """The integration user has required model and directory privileges."""
  with db_connection.cursor() as cursor:
    cursor.execute(
        """
        SELECT privilege
        FROM session_privs
        WHERE privilege IN ('CREATE MINING MODEL', 'CREATE ANY DIRECTORY')
        """
    )
    privileges = {row[0] for row in cursor}

  assert {"CREATE MINING MODEL", "CREATE ANY DIRECTORY"} <= privileges


def test_integration_user_has_unlimited_vector_tablespace_quota(
    db_connection,
) -> None:
  """The integration user can allocate the required vector objects."""
  with db_connection.cursor() as cursor:
    cursor.execute(
        """
        SELECT max_bytes
        FROM user_ts_quotas
        WHERE tablespace_name = 'VECTOR_TBS'
        """
    )
    row = cursor.fetchone()

  assert row is not None
  assert row[0] == -1
