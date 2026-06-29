-- Initial OracleSessionService schema.
--
-- The default table prefix is ADK. If OracleSessionServiceConfig.table_prefix is
-- changed, generated DDL should replace the ADK_ prefix in table, constraint,
-- and index names with the configured prefix.
--
-- Auto-created session tables use Oracle native JSON columns.
-- Use an Oracle Database release that supports the native JSON data type.

CREATE TABLE ADK_SESSIONS (
  app_name VARCHAR2(255 CHAR) NOT NULL,
  user_id VARCHAR2(255 CHAR) NOT NULL,
  session_id VARCHAR2(255 CHAR) NOT NULL,
  state_json JSON,
  create_time TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  last_update_time TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT ADK_SESSIONS_PK PRIMARY KEY (
    app_name,
    user_id,
    session_id
  )
);

CREATE TABLE ADK_EVENTS (
  app_name VARCHAR2(255 CHAR) NOT NULL,
  user_id VARCHAR2(255 CHAR) NOT NULL,
  session_id VARCHAR2(255 CHAR) NOT NULL,
  event_id VARCHAR2(255 CHAR) NOT NULL,
  event_ts TIMESTAMP WITH TIME ZONE NOT NULL,
  event_json JSON NOT NULL,
  CONSTRAINT ADK_EVENTS_PK PRIMARY KEY (
    app_name,
    user_id,
    session_id,
    event_id
  ),
  CONSTRAINT ADK_EVENTS_SESSION_FK FOREIGN KEY (
    app_name,
    user_id,
    session_id
  )
  REFERENCES ADK_SESSIONS (
    app_name,
    user_id,
    session_id
  )
  ON DELETE CASCADE
);

CREATE INDEX ADK_EVENTS_ORDER_IX
  ON ADK_EVENTS (
    app_name,
    user_id,
    session_id,
    event_ts,
    event_id
  );
