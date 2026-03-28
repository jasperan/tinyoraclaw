import logging

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "0.1.0"

DDL_STATEMENTS = [
    # ---- TINY_META ----
    """
    CREATE TABLE TINY_META (
        meta_key   VARCHAR2(100)  PRIMARY KEY,
        meta_value VARCHAR2(4000) NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # ---- TINY_MESSAGES ----
    """
    CREATE TABLE TINY_MESSAGES (
        id            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        message_id    VARCHAR2(512)  NOT NULL UNIQUE,
        channel       VARCHAR2(128)  NOT NULL,
        sender        VARCHAR2(512)  NOT NULL,
        sender_id     VARCHAR2(512),
        message       CLOB           NOT NULL,
        agent         VARCHAR2(128),
        files         CLOB,
        conversation_id VARCHAR2(512),
        from_agent    VARCHAR2(128),
        status        VARCHAR2(20)   DEFAULT 'pending' NOT NULL,
        retry_count   NUMBER(5)      DEFAULT 0 NOT NULL,
        last_error    CLOB,
        created_at    NUMBER(20)     NOT NULL,
        updated_at    NUMBER(20)     NOT NULL,
        claimed_by    VARCHAR2(128)
    )
    """,
    # ---- TINY_RESPONSES ----
    """
    CREATE TABLE TINY_RESPONSES (
        id              NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        message_id      VARCHAR2(512)  NOT NULL,
        channel         VARCHAR2(128)  NOT NULL,
        sender          VARCHAR2(512)  NOT NULL,
        sender_id       VARCHAR2(512),
        message         CLOB           NOT NULL,
        original_message CLOB          NOT NULL,
        agent           VARCHAR2(128),
        files           CLOB,
        metadata        CLOB,
        status          VARCHAR2(20)   DEFAULT 'pending' NOT NULL,
        created_at      NUMBER(20)     NOT NULL,
        acked_at        NUMBER(20)
    )
    """,
    # ---- TINY_MEMORIES ----
    """
    CREATE TABLE TINY_MEMORIES (
        memory_id   VARCHAR2(200)  PRIMARY KEY,
        agent_id    VARCHAR2(128)  DEFAULT 'default',
        text        CLOB           NOT NULL,
        importance  NUMBER(3,2)    DEFAULT 0.7,
        category    VARCHAR2(100)  DEFAULT 'other',
        embedding   VECTOR,
        created_at  TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
        accessed_at TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
        access_count NUMBER(10)    DEFAULT 0
    )
    """,
    # ---- TINY_SESSIONS ----
    """
    CREATE TABLE TINY_SESSIONS (
        session_key  VARCHAR2(200)  PRIMARY KEY,
        session_id   VARCHAR2(200)  NOT NULL,
        team_id      VARCHAR2(200)  NOT NULL,
        agent_id     VARCHAR2(128)  DEFAULT 'default',
        updated_at   NUMBER(20)     NOT NULL,
        session_data CLOB,
        channel      VARCHAR2(100),
        label        VARCHAR2(500)
    )
    """,
    # ---- TINY_TRANSCRIPTS ----
    """
    CREATE TABLE TINY_TRANSCRIPTS (
        id           VARCHAR2(200)  PRIMARY KEY,
        session_id   VARCHAR2(200)  NOT NULL,
        agent_id     VARCHAR2(128)  DEFAULT 'default',
        team_id      VARCHAR2(200),
        channel      VARCHAR2(100),
        role         VARCHAR2(50),
        sequence_num NUMBER(10)     NOT NULL,
        event_type   VARCHAR2(100)  NOT NULL,
        event_data   CLOB,
        created_at   TIMESTAMP      DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # ---- TINY_STATE ----
    """
    CREATE TABLE TINY_STATE (
        agent_id  VARCHAR2(128)  NOT NULL,
        key       VARCHAR2(256)  NOT NULL,
        value     CLOB,
        updated_at TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT pk_tiny_state PRIMARY KEY (agent_id, key)
    )
    """,
]

INDEX_STATEMENTS = [
    "CREATE INDEX IDX_TINY_MSG_STATUS_AGENT ON TINY_MESSAGES(status, agent, created_at)",
    "CREATE INDEX IDX_TINY_RESP_CHANNEL ON TINY_RESPONSES(channel, status)",
    "CREATE INDEX IDX_TINY_MEM_AGENT ON TINY_MEMORIES(agent_id)",
    "CREATE INDEX IDX_TINY_SESS_TEAM ON TINY_SESSIONS(team_id)",
    "CREATE INDEX IDX_TINY_TRANS_SESSION ON TINY_TRANSCRIPTS(session_id, sequence_num)",
]

VECTOR_INDEX_STATEMENTS = [
    """
    CREATE VECTOR INDEX IDX_TINY_MEM_VEC ON TINY_MEMORIES(embedding)
    ORGANIZATION NEIGHBOR PARTITIONS
    DISTANCE COSINE
    WITH TARGET ACCURACY 95
    """,
]

ALL_TABLES = [
    "TINY_META",
    "TINY_MESSAGES",
    "TINY_RESPONSES",
    "TINY_MEMORIES",
    "TINY_SESSIONS",
    "TINY_TRANSCRIPTS",
    "TINY_STATE",
]


async def init_schema(pool) -> dict:
    """Create all tables and indexes idempotently. Returns status dict."""
    tables_created = []
    indexes_created = []
    errors = []

    async with pool.acquire() as conn:
        # Create tables
        for ddl in DDL_STATEMENTS:
            table_name = _extract_table_name(ddl)
            try:
                cursor = conn.cursor()
                await cursor.execute(ddl)
                tables_created.append(table_name)
                logger.info("Created table %s", table_name)
            except Exception as e:
                if "ORA-00955" in str(e):
                    logger.debug("Table %s already exists", table_name)
                else:
                    logger.error("Error creating table %s: %s", table_name, e)
                    errors.append({"table": table_name, "error": str(e)})

        # Lightweight migrations for additive columns on existing tables
        migrations = [
            ("ALTER TABLE TINY_RESPONSES ADD metadata CLOB", "metadata"),
        ]
        for ddl, label in migrations:
            try:
                cursor = conn.cursor()
                await cursor.execute(ddl)
                logger.info("Applied migration for %s", label)
            except Exception as e:
                if "ORA-01430" in str(e):
                    logger.debug("Column %s already exists", label)
                else:
                    logger.warning("Migration for %s failed: %s", label, e)
                    errors.append({"migration": label, "error": str(e)})

        # Create regular indexes
        for idx_ddl in INDEX_STATEMENTS:
            idx_name = _extract_index_name(idx_ddl)
            try:
                cursor = conn.cursor()
                await cursor.execute(idx_ddl)
                indexes_created.append(idx_name)
                logger.info("Created index %s", idx_name)
            except Exception as e:
                if "ORA-00955" in str(e) or "ORA-01408" in str(e):
                    logger.debug("Index %s already exists", idx_name)
                else:
                    logger.error("Error creating index %s: %s", idx_name, e)
                    errors.append({"index": idx_name, "error": str(e)})

        # Create vector indexes
        for vidx_ddl in VECTOR_INDEX_STATEMENTS:
            idx_name = _extract_index_name(vidx_ddl)
            try:
                cursor = conn.cursor()
                await cursor.execute(vidx_ddl)
                indexes_created.append(idx_name)
                logger.info("Created vector index %s", idx_name)
            except Exception as e:
                if "ORA-00955" in str(e) or "ORA-01408" in str(e):
                    logger.debug("Vector index %s already exists", idx_name)
                else:
                    logger.warning("Vector index %s error (may need manual setup): %s", idx_name, e)
                    errors.append({"index": idx_name, "error": str(e)})

        # Set schema version
        await set_schema_version(pool, SCHEMA_VERSION)

        await conn.commit()

    return {
        "tables_created": tables_created,
        "indexes_created": indexes_created,
        "errors": errors,
    }


async def check_tables_exist(pool) -> dict[str, bool]:
    """Check which tables exist."""
    result = {}
    async with pool.acquire() as conn:
        cursor = conn.cursor()
        await cursor.execute(
            "SELECT table_name FROM user_tables WHERE table_name LIKE 'TINY_%'"
        )
        rows = await cursor.fetchall()
        existing = {row[0] for row in rows}
        for table in ALL_TABLES:
            result[table] = table in existing
    return result


async def get_schema_version(pool) -> str:
    """Get current schema version from TINY_META."""
    try:
        async with pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                "SELECT meta_value FROM TINY_META WHERE meta_key = 'schema_version'"
            )
            row = await cursor.fetchone()
            return row[0] if row else "unknown"
    except Exception:
        return "unknown"


async def set_schema_version(pool, version: str):
    """Set schema version in TINY_META."""
    async with pool.acquire() as conn:
        cursor = conn.cursor()
        await cursor.execute(
            """
            MERGE INTO TINY_META m
            USING (SELECT 'schema_version' AS meta_key FROM DUAL) s
            ON (m.meta_key = s.meta_key)
            WHEN MATCHED THEN
                UPDATE SET meta_value = :val, updated_at = CURRENT_TIMESTAMP
            WHEN NOT MATCHED THEN
                INSERT (meta_key, meta_value) VALUES ('schema_version', :val)
            """,
            {"val": version},
        )
        await conn.commit()


def _extract_table_name(ddl: str) -> str:
    """Extract table name from CREATE TABLE statement."""
    parts = ddl.strip().split()
    for i, p in enumerate(parts):
        if p.upper() == "TABLE" and i + 1 < len(parts):
            return parts[i + 1].strip("(").upper()
    return "UNKNOWN"


def _extract_index_name(ddl: str) -> str:
    """Extract index name from CREATE INDEX statement."""
    parts = ddl.strip().split()
    for i, p in enumerate(parts):
        if p.upper() == "INDEX" and i + 1 < len(parts):
            name = parts[i + 1].strip().upper()
            if name == "IF":
                continue
            return name
    return "UNKNOWN"
