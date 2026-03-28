import array
import asyncio
import logging
import threading

import oracledb

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Embedding service using Oracle's in-database ONNX model via VECTOR_EMBEDDING().

    Uses a dedicated synchronous connection for embedding operations,
    following the OracLaw pattern. A threading lock protects the shared
    connection from concurrent access via run_in_executor.
    """

    def __init__(self, settings):
        self.settings = settings
        self._conn: oracledb.Connection | None = None
        self._lock = threading.Lock()

    def _create_sync_connection(self) -> oracledb.Connection:
        """Create a synchronous connection for Oracle embedding operations."""
        params = {
            "user": self.settings.oracle_user,
            "password": self.settings.oracle_password,
            "dsn": self.settings.get_dsn(),
        }
        if self.settings.uses_wallet:
            params["config_dir"] = self.settings.oracle_wallet_path
            if self.settings.oracle_wallet_password:
                params["wallet_password"] = self.settings.oracle_wallet_password
        return oracledb.connect(**params)

    async def initialize(self):
        """Create a dedicated synchronous connection for embedding ops."""
        loop = asyncio.get_running_loop()

        if await self.check_onnx_loaded():
            try:
                self._conn = await loop.run_in_executor(
                    None, self._create_sync_connection
                )
                test_result = await loop.run_in_executor(
                    None, self._test_db_embedding, self._conn
                )
                if test_result:
                    logger.info(
                        "EmbeddingService initialized (model: %s)",
                        self.settings.oracle_onnx_model,
                    )
                    return
                else:
                    self._conn.close()
                    self._conn = None
            except Exception as e:
                logger.debug("Database embedding test failed: %s", e)
                if self._conn:
                    self._conn.close()
                    self._conn = None

        logger.warning(
            "EmbeddingService: ONNX model %s not available, embeddings will fail",
            self.settings.oracle_onnx_model,
        )

    def _test_db_embedding(self, conn) -> bool:
        """Test if VECTOR_EMBEDDING works with the loaded model."""
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT VECTOR_EMBEDDING({self.settings.oracle_onnx_model} "
                "USING 'test' AS DATA) FROM DUAL"
            )
            row = cursor.fetchone()
            return row is not None and row[0] is not None
        except Exception:
            return False

    async def check_onnx_loaded(self) -> bool:
        """Check if ONNX model is loaded in the database."""
        try:
            loop = asyncio.get_running_loop()
            conn = await loop.run_in_executor(None, self._create_sync_connection)
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM USER_MINING_MODELS WHERE MODEL_NAME = :model_name",
                    {"model_name": self.settings.oracle_onnx_model},
                )
                row = cursor.fetchone()
                return row[0] > 0 if row else False
            finally:
                conn.close()
        except Exception as e:
            logger.debug("ONNX model check failed: %s", e)
            return False

    async def load_onnx_model(self):
        """Load the ONNX embedding model into Oracle."""
        loop = asyncio.get_running_loop()
        conn = await loop.run_in_executor(None, self._create_sync_connection)
        try:
            cursor = conn.cursor()
            cursor.execute(f"""
                BEGIN
                    DBMS_VECTOR.LOAD_ONNX_MODEL(
                        '{self.settings.oracle_onnx_model}',
                        'doc',
                        JSON('{{"function":"embedding","embeddingOutput":"embedding","input":{{"input":["DATA"]}}}}')
                    );
                END;
            """)
            conn.commit()
            logger.info("ONNX model %s loaded into database", self.settings.oracle_onnx_model)
        except Exception as e:
            logger.warning("ONNX model load failed: %s", e)
            raise
        finally:
            conn.close()

    async def embed_query(self, text: str) -> list[float]:
        """Generate embedding using in-database VECTOR_EMBEDDING."""
        if not self._conn:
            raise RuntimeError("EmbeddingService not initialized or ONNX model not available")

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._embed_query_sync, text)

    def _embed_query_sync(self, text: str) -> list[float]:
        """Synchronous database embedding for a single text.

        Thread-safe: uses a lock to protect the shared connection.
        """
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                f"SELECT VECTOR_EMBEDDING({self.settings.oracle_onnx_model} "
                "USING :text AS DATA) FROM DUAL",
                {"text": text[:8000]},  # Truncate to model limit
            )
            row = cursor.fetchone()
            if not row or row[0] is None:
                return []
            vec = row[0]
            if isinstance(vec, bytes):
                return list(array.array("f", vec))
            return list(vec)

    async def close(self):
        """Release resources."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    @property
    def dimensions(self) -> int:
        return 384  # all-MiniLM-L12-v2 produces 384-dim vectors
