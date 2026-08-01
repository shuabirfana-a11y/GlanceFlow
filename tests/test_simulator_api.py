import asyncio

import httpx

from glanceflow.simulator.app import create_app


def test_simulator_serves_ui_and_session_api():
    async def scenario():
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            page = await client.get("/")
            assert page.status_code == 200
            assert "眼镜交互模拟器" in page.text
            created = await client.post("/api/sessions", json={"motion_state":"STATIONARY"})
            assert created.status_code == 200
            sid = created.json()["session"]["session_id"]
            unknown = await client.post(f"/api/sessions/{sid}/voice", json={"text":"帮我报名","confidence":1})
            assert unknown.status_code == 200
            assert unknown.json()["session"]["status"] == "IDLE"
            assert (await client.delete(f"/api/sessions/{sid}")).status_code == 204

    asyncio.run(scenario())
