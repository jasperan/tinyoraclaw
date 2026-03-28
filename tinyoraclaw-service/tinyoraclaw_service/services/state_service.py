import json
import logging

import oracledb

logger = logging.getLogger(__name__)


async def _read_lob(val):
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


class StateService:
    def __init__(self, pool):
        self.pool = pool

    async def get_state(self, state_key: str, agent_id: str = 'default') -> dict | None:
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                "SELECT value FROM TINY_STATE WHERE agent_id = :agent_id AND key = :state_key",
                {"agent_id": agent_id, "state_key": state_key},
            )
            row = await cursor.fetchone()
            if not row:
                return None
            raw = await _read_lob(row[0])
            if not raw:
                return None
            return json.loads(raw)

    async def set_state(self, state_key: str, value: dict, agent_id: str = 'default') -> None:
        payload = json.dumps(value)
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                """
                MERGE INTO TINY_STATE s
                USING (SELECT :agent_id AS agent_id, :state_key AS state_key FROM DUAL) src
                ON (s.agent_id = src.agent_id AND s.key = src.state_key)
                WHEN MATCHED THEN
                    UPDATE SET value = :payload, updated_at = CURRENT_TIMESTAMP
                WHEN NOT MATCHED THEN
                    INSERT (agent_id, key, value, updated_at)
                    VALUES (:agent_id, :state_key, :payload, CURRENT_TIMESTAMP)
                """,
                {"agent_id": agent_id, "state_key": state_key, "payload": payload},
            )
            await conn.commit()
            logger.info("Stored state %s for agent %s", state_key, agent_id)

    async def delete_state(self, state_key: str, agent_id: str = 'default') -> bool:
        async with self.pool.acquire() as conn:
            cursor = conn.cursor()
            await cursor.execute(
                "DELETE FROM TINY_STATE WHERE agent_id = :agent_id AND key = :state_key",
                {"agent_id": agent_id, "state_key": state_key},
            )
            deleted = cursor.rowcount > 0
            await conn.commit()
            return deleted
