import time
import uuid
import logging

import oracledb

logger = logging.getLogger(__name__)


async def _read_lob(val):
    """Read a LOB value to string, or return as-is if already a string."""
    if val is None:
        return None
    if isinstance(val, (oracledb.AsyncLOB,)):
        return await val.read()
    if hasattr(val, 'read') and not isinstance(val, str):
        result = val.read()
        if hasattr(result, '__await__'):
            return await result
        return result
    return val


class TranscriptService:
    def __init__(self, pool):
        self.pool = pool

    async def log_transcript(self, agent_id="default", team_id=None, session_id=None,
                             channel=None, role=None, event_type="message", content="") -> dict:
        """Log a transcript entry with auto-incrementing sequence number."""
        transcript_id = str(uuid.uuid4())
        if not session_id:
            session_id = str(uuid.uuid4())

        # Get next sequence number for this session
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                "SELECT COALESCE(MAX(sequence_num), 0) + 1 FROM TINY_TRANSCRIPTS WHERE session_id = :sid",
                {"sid": session_id}
            )
            row = await cursor.fetchone()
            seq_num = row[0] if row else 1

            await cursor.execute("""
                INSERT INTO TINY_TRANSCRIPTS (id, session_id, agent_id, team_id, channel, role, sequence_num, event_type, event_data)
                VALUES (:id, :session_id, :agent_id, :team_id, :channel, :role, :seq_num, :event_type, :event_data)
            """, {
                "id": transcript_id, "session_id": session_id,
                "agent_id": agent_id, "team_id": team_id,
                "channel": channel, "role": role,
                "seq_num": seq_num, "event_type": event_type,
                "event_data": content,
            })
            await conn.commit()
        return {"transcript_id": transcript_id, "sequence_num": seq_num}

    async def get_transcripts(self, agent_id: str, limit: int = 50) -> list[dict]:
        """Get transcripts for a specific agent."""
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute("""
                SELECT id, session_id, agent_id, team_id, channel, role, sequence_num, event_type, event_data, created_at
                FROM TINY_TRANSCRIPTS WHERE agent_id = :agent_id
                ORDER BY created_at DESC FETCH FIRST :lim ROWS ONLY
            """, {"agent_id": agent_id, "lim": limit})
            rows = await cursor.fetchall()
            results = []
            for r in rows:
                data = await _read_lob(r[8])
                results.append({
                    "id": r[0], "session_id": r[1], "agent_id": r[2],
                    "team_id": r[3], "channel": r[4], "role": r[5],
                    "sequence_num": r[6], "event_type": r[7],
                    "content": data, "created_at": str(r[9]),
                })
        return results

    async def get_transcripts_by_team(self, team_id: str, limit: int = 50) -> list[dict]:
        """Get transcripts for a specific team."""
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute("""
                SELECT id, session_id, agent_id, team_id, channel, role, sequence_num, event_type, event_data, created_at
                FROM TINY_TRANSCRIPTS WHERE team_id = :team_id
                ORDER BY created_at DESC FETCH FIRST :lim ROWS ONLY
            """, {"team_id": team_id, "lim": limit})
            rows = await cursor.fetchall()
            results = []
            for r in rows:
                data = await _read_lob(r[8])
                results.append({
                    "id": r[0], "session_id": r[1], "agent_id": r[2],
                    "team_id": r[3], "channel": r[4], "role": r[5],
                    "sequence_num": r[6], "event_type": r[7],
                    "content": data, "created_at": str(r[9]),
                })
        return results
