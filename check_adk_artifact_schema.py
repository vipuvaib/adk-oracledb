import hashlib
import os
from pathlib import Path
import re
import uuid

import oracledb


SCHEMA = (
    Path(__file__).resolve().parent
    / "src/adk_oracledb/artifacts/schema.sql"
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


# Validate the edited file before connecting.
text = "\n".join(
    line for line in SCHEMA.read_text().splitlines()
    if not line.lstrip().startswith("--")
)
statements = [part.strip() for part in text.split(";") if part.strip()]

require(len(statements) == 2, "Expected only CREATE TABLE and CREATE INDEX.")
require(
    re.match(r"CREATE\s+TABLE\s+ADK_ARTIFACTS\s*\(", statements[0], re.I),
    "Unexpected table statement.",
)
require(
    re.match(
        r"CREATE\s+INDEX\s+ADK_ARTIFACTS_LATEST_IX\s+ON\s+ADK_ARTIFACTS\s*\(",
        statements[1],
        re.I,
    ),
    "Unexpected remaining index statement.",
)
require("ADK_ARTIFACTS_KEYS_IX" not in text.upper(), "Oversized index remains.")
print("PASS: edited SQL contains only the expected creation statements.")

required = ("ORACLE_AI_DB_USER", "ORACLE_AI_DB_PASSWORD", "ORACLE_AI_DB_DSN")
missing = [name for name in required if not os.environ.get(name)]
require(not missing, "Missing environment variables: " + ", ".join(missing))

credentials = {
    "user": os.environ["ORACLE_AI_DB_USER"],
    "password": os.environ["ORACLE_AI_DB_PASSWORD"],
    "dsn": os.environ["ORACLE_AI_DB_DSN"],
}

# Rename every artifact table/index/constraint reference.
table = "ADKCHK_" + uuid.uuid4().hex[:8].upper()
ddl = [
    re.sub("ADK_ARTIFACTS", table, statement, flags=re.I)
    for statement in statements
]
print("Testing disposable table:", table)

insert_sql = f"""
INSERT INTO {table} (
    app_name, user_id, scope_type, scope_id,
    filename, filename_hash, version, payload_kind,
    payload_blob, canonical_uri
) VALUES (
    :app, :uid, 'USER', :scope,
    :filename, :file_hash, :version, :kind,
    :payload, :uri
)
"""

with oracledb.connect(**credentials) as writer:
    created = False
    try:
        with writer.cursor() as cur:
            cur.execute(ddl[0])
            created = True
            cur.execute(ddl[1])
            print("PASS: fresh table and indexes created.")

            cur.execute(
                "SELECT value FROM nls_database_parameters "
                "WHERE parameter = 'NLS_CHARACTERSET'"
            )
            charset = cur.fetchone()[0]

            cur.execute(
                """
                SELECT ts.block_size
                FROM user_indexes ix
                JOIN user_tablespaces ts
                  ON ts.tablespace_name = ix.tablespace_name
                WHERE ix.index_name = :name
                """,
                name=table + "_LATEST_IX",
            )
            result = cur.fetchone()
            require(result is not None, "Cannot determine index block size.")
            block_size = result[0]
            print(f"Database charset={charset}; index block size={block_size}")

            filename = ("\u754c" if charset == "AL32UTF8" else "x") * 1024
            values = {
                "app": "adk_sql_check",
                "uid": "test_user",
                "scope": "test_user",
                "filename": filename,
                "file_hash": hashlib.sha256(filename.encode()).hexdigest(),
                "version": 0,
                "kind": "INLINE_DATA",
                "payload": b"schema-check",
                "uri": "oracle://schema-check",
            }

            cur.setinputsizes(payload=oracledb.DB_TYPE_BLOB)
            cur.execute(insert_sql, values)
            writer.commit()
            print("PASS: a 1024-character filename can be inserted.")

            try:
                cur.execute(
                    insert_sql,
                    {**values, "version": 1, "kind": "INVALID"},
                )
            except oracledb.DatabaseError as exc:
                require(
                    exc.args[0].code == 2290,
                    f"Expected ORA-02290; received {exc}",
                )
            else:
                raise RuntimeError("Invalid payload_kind was accepted!")
            writer.rollback()
            print("PASS: the retained KIND check constraint rejects invalid data.")

            # Keep a valid write uncommitted while another session initializes.
            cur.execute(insert_sql, {**values, "version": 2})

            with oracledb.connect(**credentials) as initializer:
                with initializer.cursor() as other:
                    other.execute("ALTER SESSION SET ddl_lock_timeout = 1")

                    for statement in ddl:
                        try:
                            other.execute(statement)
                        except oracledb.DatabaseError as exc:
                            if exc.args[0].code != 955:  # Already exists.
                                raise

                    other.execute(
                        """
                        SELECT status
                        FROM user_constraints
                        WHERE table_name = :table_name
                          AND constraint_name = :constraint_name
                        """,
                        table_name=table,
                        constraint_name=table + "_KIND_CK",
                    )
                    require(
                        other.fetchone() == ("ENABLED",),
                        "KIND constraint is missing or disabled.",
                    )

            print("PASS: repeated initialization succeeded during a pending write.")

            if charset == "AL32UTF8" and block_size == 8192:
                print("PASS: the specific 8 KB AL32UTF8 configuration was tested.")
            else:
                print(
                    "NOTE: this passed on your configuration; "
                    "the specific 8 KB AL32UTF8 case still needs validation."
                )
    finally:
        writer.rollback()
        if created:
            with writer.cursor() as cleanup:
                cleanup.execute(f"DROP TABLE {table} PURGE")
            print("CLEANUP: disposable test table removed.")

print("All targeted SQL checks passed.")