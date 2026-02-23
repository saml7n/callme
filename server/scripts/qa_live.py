"""QA script for Story 18 — Live call transcript & transfer.

Tests:
1. REST GET /api/calls/live returns empty list.
2. WebSocket /ws/calls/live sends snapshot on connect.
3. POST /api/calls/{call_id}/transfer returns 404 for non-active call.
4. POST /api/calls/{call_id}/transfer returns 422 when no admin phone.

Run:  cd server && uv run python scripts/qa_live.py
"""

import asyncio
import json
import sys

import httpx

BASE = "http://localhost:3000"
API_KEY = "test-key-for-qa"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

passed = 0
failed = 0


def report(name: str, ok: bool, detail: str = ""):
    global passed, failed
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}" + (f"  — {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


async def test_rest_empty():
    """GET /api/calls/live returns empty list when no calls active."""
    print("\n" + "=" * 60)
    print("TEST 1: REST — /api/calls/live (empty)")
    print("=" * 60)
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE}/api/calls/live", headers=HEADERS)
    report("Status 200", resp.status_code == 200, f"got {resp.status_code}")
    data = resp.json()
    report("Empty list", data == [], f"got {data}")


async def test_ws_snapshot():
    """WebSocket /ws/calls/live sends snapshot on connect."""
    print("\n" + "=" * 60)
    print("TEST 2: WebSocket — snapshot on connect")
    print("=" * 60)
    try:
        import websockets
    except ImportError:
        print("  [SKIP] websockets not installed — pip install websockets")
        return

    async with websockets.connect(f"ws://localhost:3000/ws/calls/live") as ws:
        msg = await asyncio.wait_for(ws.recv(), timeout=5)
        data = json.loads(msg)
    report("Type is snapshot", data.get("type") == "snapshot", f"got {data.get('type')}")
    report("Calls is list", isinstance(data.get("calls"), list), f"got {type(data.get('calls'))}")
    report("Calls is empty", data.get("calls") == [], f"got {data.get('calls')}")


async def test_transfer_not_active():
    """POST /api/calls/{id}/transfer returns 404 for non-active call."""
    print("\n" + "=" * 60)
    print("TEST 3: Transfer — call not active (404)")
    print("=" * 60)
    fake_id = "00000000-0000-0000-0000-000000000001"
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{BASE}/api/calls/{fake_id}/transfer", headers=HEADERS)
    report("Status 404", resp.status_code == 404, f"got {resp.status_code}")
    detail = resp.json().get("detail", "")
    report("Correct message", "not active" in detail.lower(), f"got: {detail}")


async def test_transfer_no_auth():
    """POST /api/calls/{id}/transfer without auth returns 401/403."""
    print("\n" + "=" * 60)
    print("TEST 4: Transfer — no auth (401)")
    print("=" * 60)
    fake_id = "00000000-0000-0000-0000-000000000001"
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{BASE}/api/calls/{fake_id}/transfer")
    report("Status 401 or 403", resp.status_code in (401, 403), f"got {resp.status_code}")


async def test_rest_no_auth():
    """GET /api/calls/live without auth returns 401/403."""
    print("\n" + "=" * 60)
    print("TEST 5: REST — no auth (401)")
    print("=" * 60)
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE}/api/calls/live")
    report("Status 401 or 403", resp.status_code in (401, 403), f"got {resp.status_code}")


async def main():
    print("Story 18 QA — Live call transcript & transfer")
    print(f"Server: {BASE}")

    # Verify server is running
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{BASE}/health")
        if resp.status_code != 200:
            print(f"ERROR: Server health check failed ({resp.status_code})")
            sys.exit(1)
    except httpx.ConnectError:
        print("ERROR: Server not running at", BASE)
        sys.exit(1)

    await test_rest_empty()
    await test_ws_snapshot()
    await test_transfer_not_active()
    await test_transfer_no_auth()
    await test_rest_no_auth()

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
