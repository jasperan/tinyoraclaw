from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_get_state_returns_value(client, app_with_mocks):
    svc = AsyncMock()
    svc.get_state.return_value = {"pending": 2, "team": "dev"}
    app_with_mocks.state.state_service = svc

    res = await client.get('/api/state/conversation%3Aabc?agentId=default')
    assert res.status_code == 200
    assert res.json() == {"value": {"pending": 2, "team": "dev"}}
    svc.get_state.assert_awaited_once_with('conversation:abc', agent_id='default')


@pytest.mark.asyncio
async def test_put_state_persists_payload(client, app_with_mocks):
    svc = AsyncMock()
    app_with_mocks.state.state_service = svc

    payload = {"pending": 3, "responses": [{"agentId": "a", "response": "hi"}]}
    res = await client.put('/api/state/conversation%3Aabc', json={"agentId": "default", "value": payload})
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    svc.set_state.assert_awaited_once_with('conversation:abc', payload, agent_id='default')


@pytest.mark.asyncio
async def test_delete_state_reports_result(client, app_with_mocks):
    svc = AsyncMock()
    svc.delete_state.return_value = True
    app_with_mocks.state.state_service = svc

    res = await client.delete('/api/state/conversation%3Aabc?agentId=default')
    assert res.status_code == 200
    assert res.json() == {"deleted": True}
    svc.delete_state.assert_awaited_once_with('conversation:abc', agent_id='default')
