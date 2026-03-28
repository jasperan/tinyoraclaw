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


class SessionService:
    def __init__(self, pool):
        self.pool = pool

    async def save_session(self, team_id, agent_id="default", session_id=None,
                           history="", channel=None, label=None) -> dict:
        session_key = f"{team_id}_{agent_id}_{int(time.time() * 1000)}"
        if not session_id:
            session_id = str(uuid.uuid4())
        now_ms = int(time.time() * 1000)

        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute("""
                INSERT INTO TINY_SESSIONS (session_key, session_id, team_id, agent_id, updated_at, session_data, channel, label)
                VALUES (:session_key, :session_id, :team_id, :agent_id, :updated_at, :session_data, :channel, :label)
            """, {
                "session_key": session_key, "session_id": session_id,
                "team_id": team_id, "agent_id": agent_id,
                "updated_at": now_ms, "session_data": history,
                "channel": channel, "label": label,
            })
            await conn.commit()
        return {"session_key": session_key, "session_id": session_id, "stored": True}

    async def get_session(self, team_id: str) -> list[dict]:
        """Get all sessions for a team."""
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute("""
                SELECT session_key, session_id, team_id, agent_id, updated_at, session_data, channel, label
                FROM TINY_SESSIONS WHERE team_id = :team_id ORDER BY updated_at DESC
            """, {"team_id": team_id})
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                data = await _read_lob(row[5])
                results.append({
                    "session_key": row[0], "session_id": row[1], "team_id": row[2],
                    "agent_id": row[3], "updated_at": row[4], "session_data": data,
                    "channel": row[6], "label": row[7],
                })
        return results

    async def list_sessions(self) -> list[dict]:
        """List all sessions ordered by most recent."""
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute("""
                SELECT session_key, session_id, team_id, agent_id, updated_at, channel, label
                FROM TINY_SESSIONS ORDER BY updated_at DESC
            """)
            rows = await cursor.fetchall()
            return [
                {"session_key": r[0], "session_id": r[1], "team_id": r[2],
                 "agent_id": r[3], "updated_at": r[4], "channel": r[5], "label": r[6]}
                for r in rows
            ]

    async def delete_session(self, session_key: str) -> dict:
        """Delete a session by its key."""
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute("DELETE FROM TINY_SESSIONS WHERE session_key = :sk", {"sk": session_key})
            deleted = cursor.rowcount
            await conn.commit()
        return {"deleted": deleted}
