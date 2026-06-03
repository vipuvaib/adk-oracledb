CREATE TABLE ADK_ARTIFACTS (
  app_name VARCHAR2(255 CHAR) NOT NULL,
  user_id VARCHAR2(255 CHAR) NOT NULL,
  scope_type VARCHAR2(16 CHAR) NOT NULL,
  scope_id VARCHAR2(255 CHAR) NOT NULL,
  session_id VARCHAR2(255 CHAR),
  filename VARCHAR2(1024 CHAR) NOT NULL,
  filename_hash VARCHAR2(64 CHAR) NOT NULL,
  version NUMBER(10) NOT NULL,
  payload_kind VARCHAR2(32 CHAR) NOT NULL,
  mime_type VARCHAR2(255 CHAR),
  payload_blob BLOB NOT NULL,
  part_json JSON,
  custom_metadata JSON,
  canonical_uri VARCHAR2(2048 CHAR) NOT NULL,
  content_size NUMBER(19),
  sha256 VARCHAR2(64 CHAR),
  create_time TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT ADK_ARTIFACTS_PK PRIMARY KEY (
    app_name,
    user_id,
    scope_type,
    scope_id,
    filename_hash,
    version
  ),
  CONSTRAINT ADK_ARTIFACTS_SCOPE_CK CHECK (
    scope_type IN ('USER', 'SESSION')
  ),
  CONSTRAINT ADK_ARTIFACTS_KIND_CK CHECK (
    payload_kind IN ('TEXT', 'INLINE_DATA')
  )
);

CREATE INDEX ADK_ARTIFACTS_KEYS_IX
  ON ADK_ARTIFACTS (
    app_name,
    user_id,
    scope_type,
    scope_id,
    filename
  );

CREATE INDEX ADK_ARTIFACTS_LATEST_IX
  ON ADK_ARTIFACTS (
    app_name,
    user_id,
    scope_type,
    scope_id,
    filename_hash,
    version DESC
  );
