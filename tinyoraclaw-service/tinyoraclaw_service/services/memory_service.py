import array
import logging
import uuid

import oracledb

logger = logging.getLogger(__name__)


def _to_vector(embedding: list[float]) -> array.array:
    """Convert a Python list of floats to an array.array for Oracle VECTOR binding."""
    return array.array("f", embedding)


async def _read_lob(val):
    """Read a LOB value to string, or return as-is if already a string."""
    if val is None:
        return None
    if isinstance(val, (oracledb.AsyncLOB,)):
        return await val.read()
    if hasattr(val, "read"):
        result = val.read()
        if hasattr(result, "__await__"):
            return await result
        return result
    return val


class MemoryService:
    """Memory service for TinyOraClaw.

    Provides remember/recall/forget operations backed by Oracle AI Database
    with vector embeddings for semantic similarity search.
    """

    def __init__(self, pool, embedding_service, settings):
        self.pool = pool
        self.embedding_service = embedding_service
        self.settings = settings

    async def initialize(self):
        """Initialize the memory service and verify table access."""
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute("SELECT COUNT(*) FROM TINY_MEMORIES")
            row = await cursor.fetchone()
            logger.info(
                "MemoryService initialized (existing memories: %d)",
                row[0] if row else 0,
            )

    async def remember(
        self,
        text: str,
        agent_id: str = "default",
        importance: float = 0.7,
        category: str = "other",
    ) -> dict:
        """Store a memory with auto-embedding."""
        memory_id = str(uuid.uuid4())
        embedding = await self.embedding_service.embed_query(text)

        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                """
                INSERT INTO TINY_MEMORIES
                    (memory_id, agent_id, text, importance, category, embedding)
                VALUES (:memory_id, :agent_id, :text, :importance, :category, :embedding)
                """,
                {
                    "memory_id": memory_id,
                    "agent_id": agent_id,
                    "text": text,
                    "importance": importance,
                    "category": category,
                    "embedding": _to_vector(embedding),
                },
            )
            await conn.commit()

        return {"memory_id": memory_id, "stored": True}

    async def recall(
        self,
        query: str,
        agent_id: str = "default",
        max_results: int = 5,
        min_score: float = 0.3,
    ) -> list[dict]:
        """Search memories by vector similarity."""
        query_embedding = await self.embedding_service.embed_query(query)

        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                """
                SELECT memory_id, agent_id, text, importance, category,
                       VECTOR_DISTANCE(embedding, :query_vec, COSINE) AS distance,
                       created_at, accessed_at, access_count
                FROM TINY_MEMORIES
                WHERE agent_id = :agent_id AND embedding IS NOT NULL
                ORDER BY distance ASC
                FETCH FIRST :max_results ROWS ONLY
                """,
                {
                    "query_vec": _to_vector(query_embedding),
                    "agent_id": agent_id,
                    "max_results": max_results,
                },
            )
            rows = await cursor.fetchall()

            results = []
            memory_ids = []
            for row in rows:
                distance = float(row[5])
                similarity = 1.0 - distance
                if similarity < min_score:
                    continue
                text_val = await _read_lob(row[2])
                results.append(
                    {
                        "memory_id": row[0],
                        "agent_id": row[1],
                        "text": text_val,
                        "importance": float(row[3]),
                        "category": row[4],
                        "score": round(similarity, 4),
                        "created_at": str(row[6]),
                        "accessed_at": str(row[7]) if row[7] else None,
                        "access_count": row[8],
                    }
                )
                memory_ids.append(row[0])

            # Update access timestamps for recalled memories
            if memory_ids:
                placeholders = ", ".join(f":id{i}" for i in range(len(memory_ids)))
                params = {f"id{i}": mid for i, mid in enumerate(memory_ids)}
                update_cursor = conn.cursor()
                await update_cursor.execute(
                    f"""
                    UPDATE TINY_MEMORIES
                    SET accessed_at = CURRENT_TIMESTAMP, access_count = access_count + 1
                    WHERE memory_id IN ({placeholders})
                    """,
                    params,
                )
                await conn.commit()

        return results

    async def forget(self, memory_id: str) -> dict:
        """Delete a memory by ID."""
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                "DELETE FROM TINY_MEMORIES WHERE memory_id = :memory_id",
                {"memory_id": memory_id},
            )
            deleted = cursor.rowcount
            await conn.commit()
        return {"deleted": deleted}

    async def count_memories(self, agent_id: str = "default") -> dict:
        """Count memories for an agent."""
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                "SELECT COUNT(*) FROM TINY_MEMORIES WHERE agent_id = :agent_id",
                {"agent_id": agent_id},
            )
            row = await cursor.fetchone()
        return {"agent_id": agent_id, "count": row[0] if row else 0}

    async def get_status(self) -> dict:
        """Get memory status: table counts for core tables."""
        async with self.pool.acquire() as conn:
            counts = {}
            cursor = conn.cursor()
            for table, key in [
                ("TINY_MEMORIES", "memory_count"),
                ("TINY_MESSAGES", "message_count"),
                ("TINY_SESSIONS", "session_count"),
            ]:
                try:
                    await cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    row = await cursor.fetchone()
                    counts[key] = row[0] if row else 0
                except Exception:
                    counts[key] = 0
        return counts
