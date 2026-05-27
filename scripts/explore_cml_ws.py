#!/usr/bin/env python3
"""Exploration script: Probe CML WebSocket endpoint authentication.

Tests how to authenticate with the CML /ws/ui WebSocket endpoint.
Based on screenshot showing wss://<host>/ws/ui with 101 Switching Protocols.

Usage:
    python scripts/explore_cml_ws.py <host> [username] [password]

This is a temporary exploration script - not part of the main codebase.
"""

import asyncio
import json
import logging
import ssl
import sys
import time

import httpx

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Try websockets library (pip install websockets)
try:
    import websockets
    import websockets.client

    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    logger.warning("websockets library not installed. Install with: pip install websockets")


async def get_cml_token(host: str, username: str, password: str) -> str:
    """Authenticate with CML and get bearer token."""
    url = f"https://{host}/api/v0/authenticate"
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
        response = await client.post(url, json={"username": username, "password": password})
        response.raise_for_status()
        token = response.json()
        logger.info(f"Got CML token: {token[:20]}...")
        return token


async def probe_ws_no_auth(host: str):
    """Try connecting without authentication."""
    if not HAS_WEBSOCKETS:
        return

    uri = f"wss://{host}/ws/ui"
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    logger.info(f"Probing {uri} WITHOUT auth...")
    try:
        async with websockets.client.connect(uri, ssl=ssl_context, open_timeout=10) as ws:
            logger.info("Connected! (no auth needed for WS handshake)")
            logger.info(f"Response headers: {ws.response_headers}")
            # Read a few messages
            for i in range(5):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=15.0)
                    data = json.loads(msg)
                    logger.info(f"Message {i + 1}: event_type={data.get('event_type')}, keys={list(data.keys())}")
                except asyncio.TimeoutError:
                    logger.info(f"No message received in 15s (message {i + 1})")
                    break
    except websockets.exceptions.InvalidStatusCode as e:
        logger.info(f"Rejected without auth: HTTP {e.status_code}")
    except Exception as e:
        logger.error(f"Error (no auth): {type(e).__name__}: {e}")


async def probe_ws_with_token(host: str, token: str):
    """Try connecting with bearer token in various ways."""
    if not HAS_WEBSOCKETS:
        return

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    # Attempt 1: Token in query parameter
    uri = f"wss://{host}/ws/ui?token={token}"
    logger.info(f"Probing {uri[:60]}... (token in query)")
    try:
        async with websockets.client.connect(uri, ssl=ssl_context, open_timeout=10) as ws:
            logger.info("Connected with query token!")
            for i in range(5):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=15.0)
                    data = json.loads(msg)
                    logger.info(f"Message {i + 1}: event_type={data.get('event_type')}, size={len(msg)}")
                    if i == 0:
                        logger.info(f"Full first message: {json.dumps(data, indent=2)[:500]}")
                except asyncio.TimeoutError:
                    logger.info("No message in 15s")
                    break
    except websockets.exceptions.InvalidStatusCode as e:
        logger.info(f"Rejected with query token: HTTP {e.status_code}")
    except Exception as e:
        logger.error(f"Error (query token): {type(e).__name__}: {e}")

    # Attempt 2: Token in Authorization header
    uri = f"wss://{host}/ws/ui"
    headers = {"Authorization": f"Bearer {token}"}
    logger.info(f"Probing {uri} with Authorization header...")
    try:
        async with websockets.client.connect(uri, ssl=ssl_context, open_timeout=10, additional_headers=headers) as ws:
            logger.info("Connected with Authorization header!")
            for i in range(5):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=15.0)
                    data = json.loads(msg)
                    logger.info(f"Message {i + 1}: event_type={data.get('event_type')}, size={len(msg)}")
                    if i == 0:
                        logger.info(f"Full first message: {json.dumps(data, indent=2)[:500]}")
                except asyncio.TimeoutError:
                    logger.info("No message in 15s")
                    break
    except websockets.exceptions.InvalidStatusCode as e:
        logger.info(f"Rejected with header: HTTP {e.status_code}")
    except Exception as e:
        logger.error(f"Error (header): {type(e).__name__}: {e}")

    # Attempt 3: Token as cookie
    uri = f"wss://{host}/ws/ui"
    headers_cookie = {"Cookie": f"token={token}"}
    logger.info(f"Probing {uri} with Cookie header...")
    try:
        async with websockets.client.connect(uri, ssl=ssl_context, open_timeout=10, additional_headers=headers_cookie) as ws:
            logger.info("Connected with Cookie!")
            for i in range(3):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=15.0)
                    data = json.loads(msg)
                    logger.info(f"Message {i + 1}: event_type={data.get('event_type')}, size={len(msg)}")
                except asyncio.TimeoutError:
                    logger.info("No message in 15s")
                    break
    except websockets.exceptions.InvalidStatusCode as e:
        logger.info(f"Rejected with cookie: HTTP {e.status_code}")
    except Exception as e:
        logger.error(f"Error (cookie): {type(e).__name__}: {e}")


async def probe_ws_msg_auth(host: str, token: str):
    """Try authenticating via WebSocket message after connection.

    CML appears to accept the WS handshake without auth, then waits ~10s
    for an auth message before sending CLOSE 3000 Unauthorized.
    """
    if not HAS_WEBSOCKETS:
        return

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    uri = f"wss://{host}/ws/ui"

    # Try various auth message formats
    auth_messages = [
        # Format 1: Just the token as a string
        ("raw token", token),
        # Format 2: JSON with token field
        ("json {token}", json.dumps({"token": token})),
        # Format 3: JSON with authorization field
        ("json {authorization}", json.dumps({"authorization": f"Bearer {token}"})),
        # Format 4: JSON authenticate command
        ("json authenticate cmd", json.dumps({"type": "authenticate", "token": token})),
        # Format 5: Bearer prefix
        ("Bearer prefix", f"Bearer {token}"),
    ]

    for label, auth_msg in auth_messages:
        logger.info(f"\n--- Trying WS msg auth: {label} ---")
        try:
            async with websockets.client.connect(uri, ssl=ssl_context, open_timeout=10) as ws:
                logger.info(f"Connected. Sending auth message ({label})...")
                await ws.send(auth_msg)
                logger.info("Auth message sent. Waiting for response...")

                # Try to receive messages
                for i in range(5):
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=12.0)
                        data = json.loads(msg) if msg.startswith("{") else msg
                        if isinstance(data, dict):
                            logger.info(f"✅ Message {i + 1}: event_type={data.get('event_type')}, keys={list(data.keys())}")
                            if i == 0:
                                logger.info(f"Full message: {json.dumps(data, indent=2)[:800]}")
                        else:
                            logger.info(f"Message {i + 1} (raw): {str(data)[:200]}")
                    except asyncio.TimeoutError:
                        logger.info(f"No message in 12s after auth (message {i + 1})")
                        break
        except Exception as e:
            logger.error(f"Error ({label}): {type(e).__name__}: {e}")


async def probe_ws_with_extra_headers(host: str, token: str):
    """Try connecting with token in extra_headers (websockets v12+ API)."""
    if not HAS_WEBSOCKETS:
        return

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    uri = f"wss://{host}/ws/ui"

    # websockets v12+ uses `extra_headers` instead of `additional_headers`
    logger.info("\n--- Trying extra_headers with Authorization: Bearer ---")
    try:
        async with websockets.client.connect(
            uri,
            ssl=ssl_context,
            open_timeout=10,
            extra_headers={"Authorization": f"Bearer {token}"},
        ) as ws:
            logger.info("Connected with extra_headers Authorization!")
            for i in range(5):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=12.0)
                    data = json.loads(msg)
                    logger.info(f"✅ Message {i + 1}: event_type={data.get('event_type')}, size={len(msg)}")
                    if i == 0:
                        logger.info(f"Full message: {json.dumps(data, indent=2)[:800]}")
                except asyncio.TimeoutError:
                    logger.info("No message in 12s")
                    break
    except Exception as e:
        logger.error(f"Error (extra_headers auth): {type(e).__name__}: {e}")

    # Also try Cookie with extra_headers
    logger.info("\n--- Trying extra_headers with Cookie ---")
    try:
        async with websockets.client.connect(
            uri,
            ssl=ssl_context,
            open_timeout=10,
            extra_headers={"Cookie": f"token={token}"},
        ) as ws:
            logger.info("Connected with extra_headers Cookie!")
            for i in range(5):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=12.0)
                    data = json.loads(msg)
                    logger.info(f"✅ Message {i + 1}: event_type={data.get('event_type')}, size={len(msg)}")
                    if i == 0:
                        logger.info(f"Full message: {json.dumps(data, indent=2)[:800]}")
                except asyncio.TimeoutError:
                    logger.info("No message in 12s")
                    break
    except Exception as e:
        logger.error(f"Error (extra_headers cookie): {type(e).__name__}: {e}")


async def probe_ws_long_listen(host: str, token: str, auth_method: str, duration: int = 60):
    """Listen for extended period to catalog all event types.

    auth_method: one of 'msg_token', 'header', 'query', 'cookie'
    """
    if not HAS_WEBSOCKETS:
        return

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    uri = f"wss://{host}/ws/ui"
    logger.info(f"\nLong listen ({duration}s) using auth_method={auth_method}...")

    event_types: dict[str, int] = {}
    first_messages: dict[str, str] = {}
    start = time.time()

    try:
        connect_kwargs = {"ssl": ssl_context, "open_timeout": 10}
        if auth_method == "query":
            uri = f"wss://{host}/ws/ui?token={token}"
        elif auth_method == "header":
            connect_kwargs["extra_headers"] = {"Authorization": f"Bearer {token}"}
        elif auth_method == "cookie":
            connect_kwargs["extra_headers"] = {"Cookie": f"token={token}"}

        async with websockets.client.connect(uri, **connect_kwargs) as ws:
            # If msg-based auth, send immediately
            if auth_method == "msg_token":
                await ws.send(token)
                logger.info("Sent raw token as first WS message")
            elif auth_method == "json_token":
                await ws.send(json.dumps({"token": token}))
                logger.info('Sent {"token": ...} as first WS message')

            while (time.time() - start) < duration:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    data = json.loads(msg)
                    evt = data.get("event_type", "unknown")
                    event_types[evt] = event_types.get(evt, 0) + 1
                    if evt not in first_messages:
                        first_messages[evt] = json.dumps(data, indent=2)[:600]
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error during listen: {e}")
                    break
    except Exception as e:
        logger.error(f"Connection error: {e}")

    logger.info(f"\n{'=' * 60}")
    logger.info(f"EVENT TYPE CATALOG (listened {int(time.time() - start)}s)")
    logger.info(f"{'=' * 60}")
    for evt, count in sorted(event_types.items()):
        logger.info(f"  {evt}: {count} messages")
    logger.info(f"Total messages: {sum(event_types.values())}")
    logger.info("\n--- First message samples ---")
    for evt, sample in first_messages.items():
        logger.info(f"\n[{evt}]:\n{sample}")


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/explore_cml_ws.py <host> [username] [password]")
        print("Example: python scripts/explore_cml_ws.py 3.91.22.2 admin mypassword")
        sys.exit(1)

    host = sys.argv[1]
    username = sys.argv[2] if len(sys.argv) > 2 else "admin"
    password = sys.argv[3] if len(sys.argv) > 3 else ""

    if not password:
        import getpass

        password = getpass.getpass(f"CML password for {username}@{host}: ")

    # Step 1: Get auth token
    logger.info(f"Authenticating with CML at {host}...")
    token = await get_cml_token(host, username, password)

    # Step 2: Try message-based authentication (most likely based on CLOSE 3000 behavior)
    await probe_ws_msg_auth(host, token)

    # Step 3: Try extra_headers (fixed API for websockets v12+)
    await probe_ws_with_extra_headers(host, token)

    # Step 4: Long listen with the confirmed auth method
    # Confirmed: JSON {"token": "<jwt>"} sent as first WS message
    await probe_ws_long_listen(host, token, auth_method="json_token", duration=45)


if __name__ == "__main__":
    asyncio.run(main())
