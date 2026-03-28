import json
import logging
import time

import oracledb

from ..models.queue import EnqueueMessageRequest, EnqueueResponseRequest

logger = logging.getLogger(__name__)

MAX_RETRIES = 5


async def _read_lob(val):
    """Read a LOB value to string, or return as-is if already a string."""
    if val is None:
        return None
    if isinstance(val, (oracledb.AsyncLOB,)):
        return await val.read()
    if hasattr(val, 'read'):
        result = val.read()
        if hasattr(result, '__await__'):
            return await result
        return result
    return val


def _now_ms() -> int:
    """Current time in milliseconds, matching JavaScript's Date.now()."""
    return int(time.time() * 1000)


class QueueService:
    def __init__(self, pool):
        self.pool = pool

    # ── Messages (incoming queue) ─────────────────────────────────────────

    async def enqueue_message(self, data: EnqueueMessageRequest) -> int:
        """INSERT into TINY_MESSAGES with status='pending', return generated id."""
        now = _now_ms()
        files_json = json.dumps(data.files) if data.files else None

        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            id_var = cursor.var(oracledb.NUMBER)
            await cursor.execute(
                """
                INSERT INTO TINY_MESSAGES
                    (message_id, channel, sender, sender_id, message, agent,
                     files, conversation_id, from_agent, status, created_at, updated_at)
                VALUES
                    (:message_id, :channel, :sender, :sender_id, :message, :agent,
                     :files, :conversation_id, :from_agent, 'pending', :created_at, :updated_at)
                RETURNING id INTO :out_id
                """,
                {
                    "message_id": data.messageId,
                    "channel": data.channel,
                    "sender": data.sender,
                    "sender_id": data.senderId,
                    "message": data.message,
                    "agent": data.agent,
                    "files": files_json,
                    "conversation_id": data.conversationId,
                    "from_agent": data.fromAgent,
                    "created_at": now,
                    "updated_at": now,
                    "out_id": id_var,
                },
            )
            await conn.commit()
            row_id = int(id_var.getvalue()[0])
            logger.info("Enqueued message %s (row %d, agent=%s)", data.messageId, row_id, data.agent)
            return row_id

    async def claim_next_message(self, agent_id: str) -> dict | None:
        """Atomically claim the oldest pending message for a given agent.

        Uses SELECT ... FOR UPDATE SKIP LOCKED so concurrent workers never
        claim the same row.
        """
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                """
                SELECT id, message_id, channel, sender, sender_id, message,
                       agent, files, conversation_id, from_agent, status,
                       retry_count, last_error, created_at, updated_at, claimed_by
                FROM TINY_MESSAGES
                WHERE status = 'pending'
                  AND (agent = :agent_id OR (agent IS NULL AND :agent_id2 = 'default'))
                ORDER BY created_at ASC
                FETCH FIRST 1 ROWS ONLY
                FOR UPDATE SKIP LOCKED
                """,
                {"agent_id": agent_id, "agent_id2": agent_id},
            )
            row = await cursor.fetchone()
            if not row:
                return None

            row_id = row[0]
            now = _now_ms()
            await cursor.execute(
                """
                UPDATE TINY_MESSAGES
                SET status = 'processing', claimed_by = :agent_id, updated_at = :now
                WHERE id = :row_id
                """,
                {"agent_id": agent_id, "now": now, "row_id": row_id},
            )
            await conn.commit()

            return {
                "id": row[0],
                "message_id": await _read_lob(row[1]),
                "channel": await _read_lob(row[2]),
                "sender": await _read_lob(row[3]),
                "sender_id": await _read_lob(row[4]),
                "message": await _read_lob(row[5]),
                "agent": await _read_lob(row[6]),
                "files": await _read_lob(row[7]),
                "conversation_id": await _read_lob(row[8]),
                "from_agent": await _read_lob(row[9]),
                "status": "processing",
                "retry_count": row[11],
                "last_error": await _read_lob(row[12]),
                "created_at": row[13],
                "updated_at": now,
                "claimed_by": agent_id,
            }

    async def complete_message(self, row_id: int) -> None:
        """Mark a message as completed."""
        now = _now_ms()
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                """
                UPDATE TINY_MESSAGES SET status = 'completed', updated_at = :now
                WHERE id = :row_id
                """,
                {"now": now, "row_id": row_id},
            )
            await conn.commit()

    async def fail_message(self, row_id: int, error: str) -> None:
        """Increment retry_count; move to 'dead' if max retries exceeded."""
        now = _now_ms()
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                "SELECT retry_count FROM TINY_MESSAGES WHERE id = :row_id",
                {"row_id": row_id},
            )
            row = await cursor.fetchone()
            if not row:
                return

            new_count = row[0] + 1
            new_status = "dead" if new_count >= MAX_RETRIES else "pending"

            await cursor.execute(
                """
                UPDATE TINY_MESSAGES
                SET status = :status, retry_count = :cnt, last_error = :err,
                    claimed_by = NULL, updated_at = :now
                WHERE id = :row_id
                """,
                {
                    "status": new_status,
                    "cnt": new_count,
                    "err": error,
                    "now": now,
                    "row_id": row_id,
                },
            )
            await conn.commit()

    # ── Responses (outgoing queue) ────────────────────────────────────────

    async def enqueue_response(self, data: EnqueueResponseRequest) -> int:
        """INSERT into TINY_RESPONSES with status='pending', return generated id."""
        now = _now_ms()
        files_json = json.dumps(data.files) if data.files else None
        metadata_json = json.dumps(data.metadata) if data.metadata else None

        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            id_var = cursor.var(oracledb.NUMBER)
            await cursor.execute(
                """
                INSERT INTO TINY_RESPONSES
                    (message_id, channel, sender, sender_id, message,
                     original_message, agent, files, metadata, status, created_at)
                VALUES
                    (:message_id, :channel, :sender, :sender_id, :message,
                     :original_message, :agent, :files, :metadata, 'pending', :created_at)
                RETURNING id INTO :out_id
                """,
                {
                    "message_id": data.messageId,
                    "channel": data.channel,
                    "sender": data.sender,
                    "sender_id": data.senderId,
                    "message": data.message,
                    "original_message": data.originalMessage,
                    "agent": data.agent,
                    "files": files_json,
                    "metadata": metadata_json,
                    "created_at": now,
                    "out_id": id_var,
                },
            )
            await conn.commit()
            row_id = int(id_var.getvalue()[0])
            logger.info("Enqueued response for message %s (row %d)", data.messageId, row_id)
            return row_id

    async def get_responses_for_channel(self, channel: str) -> list[dict]:
        """Get all pending responses for a channel, ordered by creation time."""
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                """
                SELECT id, message_id, channel, sender, sender_id, message,
                       original_message, agent, files, metadata, status, created_at, acked_at
                FROM TINY_RESPONSES
                WHERE channel = :channel AND status = 'pending'
                ORDER BY created_at ASC
                """,
                {"channel": channel},
            )
            rows = await cursor.fetchall()
            return [await self._row_to_response(r) for r in rows]

    async def ack_response(self, response_id: int) -> None:
        """Mark a response as acknowledged."""
        now = _now_ms()
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                """
                UPDATE TINY_RESPONSES SET status = 'acked', acked_at = :now
                WHERE id = :response_id
                """,
                {"now": now, "response_id": response_id},
            )
            await conn.commit()

    async def get_recent_responses(self, limit: int) -> list[dict]:
        """Get the most recent responses regardless of status."""
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                """
                SELECT id, message_id, channel, sender, sender_id, message,
                       original_message, agent, files, metadata, status, created_at, acked_at
                FROM TINY_RESPONSES
                ORDER BY created_at DESC
                FETCH FIRST :limit ROWS ONLY
                """,
                {"limit": limit},
            )
            rows = await cursor.fetchall()
            return [await self._row_to_response(r) for r in rows]

    # ── Queue status & management ─────────────────────────────────────────

    async def get_queue_status(self) -> dict:
        """Get message counts grouped by status, plus pending response count."""
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                "SELECT status, COUNT(*) AS cnt FROM TINY_MESSAGES GROUP BY status"
            )
            rows = await cursor.fetchall()

            result = {"pending": 0, "processing": 0, "completed": 0, "dead": 0, "responsesPending": 0}
            for row in rows:
                status = row[0]
                if status in result:
                    result[status] = row[1]

            await cursor.execute(
                "SELECT COUNT(*) FROM TINY_RESPONSES WHERE status = 'pending'"
            )
            resp_row = await cursor.fetchone()
            result["responsesPending"] = resp_row[0] if resp_row else 0

            return result

    async def get_dead_messages(self) -> list[dict]:
        """Get all dead-letter messages."""
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                """
                SELECT id, message_id, channel, sender, sender_id, message,
                       agent, files, conversation_id, from_agent, status,
                       retry_count, last_error, created_at, updated_at, claimed_by
                FROM TINY_MESSAGES
                WHERE status = 'dead'
                ORDER BY updated_at DESC
                """
            )
            rows = await cursor.fetchall()
            return [await self._row_to_message(r) for r in rows]

    async def retry_dead_message(self, row_id: int) -> bool:
        """Reset a dead message back to pending for re-processing."""
        now = _now_ms()
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                """
                UPDATE TINY_MESSAGES
                SET status = 'pending', retry_count = 0, claimed_by = NULL, updated_at = :now
                WHERE id = :row_id AND status = 'dead'
                """,
                {"now": now, "row_id": row_id},
            )
            changed = cursor.rowcount
            await conn.commit()
            return changed > 0

    async def delete_dead_message(self, row_id: int) -> bool:
        """Permanently delete a dead message."""
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                "DELETE FROM TINY_MESSAGES WHERE id = :row_id AND status = 'dead'",
                {"row_id": row_id},
            )
            changed = cursor.rowcount
            await conn.commit()
            return changed > 0

    async def recover_stale_messages(self, threshold_ms: int = 600000) -> int:
        """Recover messages stuck in 'processing' longer than threshold (default 10 min)."""
        now = _now_ms()
        cutoff = now - threshold_ms
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                """
                UPDATE TINY_MESSAGES
                SET status = 'pending', claimed_by = NULL, updated_at = :now
                WHERE status = 'processing' AND updated_at < :cutoff
                """,
                {"now": now, "cutoff": cutoff},
            )
            changed = cursor.rowcount
            await conn.commit()
            return changed

    async def prune_acked_responses(self, older_than_ms: int = 86400000) -> int:
        """Delete acked responses older than threshold (default 24h)."""
        cutoff = _now_ms() - older_than_ms
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                "DELETE FROM TINY_RESPONSES WHERE status = 'acked' AND acked_at < :cutoff",
                {"cutoff": cutoff},
            )
            changed = cursor.rowcount
            await conn.commit()
            return changed

    async def prune_completed_messages(self, older_than_ms: int = 86400000) -> int:
        """Delete completed messages older than threshold (default 24h).
        Dead messages are kept for manual review/retry."""
        cutoff = _now_ms() - older_than_ms
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                "DELETE FROM TINY_MESSAGES WHERE status = 'completed' AND updated_at < :cutoff",
                {"cutoff": cutoff},
            )
            changed = cursor.rowcount
            await conn.commit()
            return changed

    async def get_pending_agents(self) -> list[str]:
        """Get distinct agent identifiers from pending messages."""
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                """
                SELECT DISTINCT COALESCE(agent, 'default') AS agent
                FROM TINY_MESSAGES
                WHERE status = 'pending'
                """
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_agent_queue_status(self) -> list[dict]:
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                """
                SELECT COALESCE(agent, 'default') AS agent,
                       SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                       SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) AS processing
                FROM TINY_MESSAGES
                WHERE status IN ('pending', 'processing')
                GROUP BY COALESCE(agent, 'default')
                """
            )
            rows = await cursor.fetchall()
            return [
                {
                    'agent': row[0],
                    'pending': row[1] or 0,
                    'queued': 0,
                    'processing': row[2] or 0,
                }
                for row in rows
            ]

    async def get_processing_messages(self) -> list[dict]:
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                """
                SELECT id, message_id, channel, sender, sender_id, message,
                       agent, files, conversation_id, from_agent, status,
                       retry_count, last_error, created_at, updated_at, claimed_by
                FROM TINY_MESSAGES
                WHERE status = 'processing'
                ORDER BY updated_at ASC
                """
            )
            rows = await cursor.fetchall()
            return [await self._row_to_message(r) for r in rows]

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _row_to_message(self, row) -> dict:
        """Convert a TINY_MESSAGES row tuple to a dict, reading LOBs."""
        return {
            "id": row[0],
            "message_id": await _read_lob(row[1]),
            "channel": await _read_lob(row[2]),
            "sender": await _read_lob(row[3]),
            "sender_id": await _read_lob(row[4]),
            "message": await _read_lob(row[5]),
            "agent": await _read_lob(row[6]),
            "files": await _read_lob(row[7]),
            "conversation_id": await _read_lob(row[8]),
            "from_agent": await _read_lob(row[9]),
            "status": await _read_lob(row[10]),
            "retry_count": row[11],
            "last_error": await _read_lob(row[12]),
            "created_at": row[13],
            "updated_at": row[14],
            "claimed_by": await _read_lob(row[15]),
        }

    async def _row_to_response(self, row) -> dict:
        """Convert a TINY_RESPONSES row tuple to a dict, reading LOBs."""
        return {
            "id": row[0],
            "message_id": await _read_lob(row[1]),
            "channel": await _read_lob(row[2]),
            "sender": await _read_lob(row[3]),
            "sender_id": await _read_lob(row[4]),
            "message": await _read_lob(row[5]),
            "original_message": await _read_lob(row[6]),
            "agent": await _read_lob(row[7]),
            "files": await _read_lob(row[8]),
            "metadata": await _read_lob(row[9]),
            "status": await _read_lob(row[10]),
            "created_at": row[11],
            "acked_at": row[12],
        }
