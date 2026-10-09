"""Security-hardened ICY StreamTitle reader for the original internet radio."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import time

from aiohttp import ClientSession, ClientTimeout, DummyCookieJar, TCPConnector
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver

from .rules import MAX_TEXT, validate_monitor_url

# Permit a useful ICY interval while rejecting tiny intervals that can consume CPU.
MIN_INTERVAL = 128
MAX_INTERVAL = 131072
RECONNECT_DELAYS = (3, 7, 15, 30)
TITLE_PATTERN = re.compile(rb"StreamTitle=(['\"])(.*?)\1", re.DOTALL)


class PublicOnlyResolver(AbstractResolver):
    """Reject private, link-local, loopback and reserved DNS answers at connect time."""

    def __init__(self) -> None:
        """Create the underlying resolver."""
        self._delegate = DefaultResolver()

    async def resolve(self, host: str, port: int = 0, family: int = 0) -> list[dict]:
        """Resolve a hostname and require all candidate addresses to be globally routed."""
        results = await self._delegate.resolve(host, port, family)
        if not results or any(
            not ipaddress.ip_address(entry["host"]).is_global for entry in results
        ):
            raise OSError("Blocked non-public radio monitor DNS result")
        return results

    async def close(self) -> None:
        """Release DNS resolver resources."""
        await self._delegate.close()


class IcyMonitor:
    """Independent stream connection. Reads metadata and discards audio, never plays it."""

    def __init__(self, url: str, logger) -> None:
        """Validate the URL and initialize a monitor with bounded resources."""
        self.url = validate_monitor_url(url)
        if not self.url:
            raise ValueError("A public monitor URL is required")
        self.logger = logger
        self.title = ""
        self.updated_at = 0.0
        self.revision = 0
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Begin monitoring in an isolated, non-proxied HTTP session."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Terminate the task and close its HTTP connection."""
        if self._task is None:
            return
        task, self._task = self._task, None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        """Read bounded ICY blocks with DNS protection, no redirects and finite retries."""
        timeout = ClientTimeout(total=None, connect=10, sock_connect=10, sock_read=30)
        connector = TCPConnector(
            resolver=PublicOnlyResolver(), use_dns_cache=False, limit=1, limit_per_host=1
        )
        async with ClientSession(
            connector=connector, timeout=timeout, trust_env=False,
            cookie_jar=DummyCookieJar(), headers={"Icy-MetaData": "1"},
        ) as session:
            for attempt in range(len(RECONNECT_DELAYS) + 1):
                try:
                    async with session.get(self.url, allow_redirects=False) as response:
                        if 300 <= response.status < 400:
                            self.logger.warning(
                                "Radio Filter: ICY monitor rejects HTTP redirects; use a direct stream URL"
                            )
                            return
                        response.raise_for_status()
                        try:
                            interval = int(response.headers.get("icy-metaint", "0"))
                        except ValueError:
                            interval = 0
                        if not MIN_INTERVAL <= interval <= MAX_INTERVAL:
                            self.logger.warning(
                                "Radio Filter: no valid ICY metadata interval; monitor disabled"
                            )
                            return
                        while True:
                            # readexactly consumes the audio between metadata blocks.
                            await response.content.readexactly(interval)
                            payload_size = (await response.content.readexactly(1))[0] * 16
                            if not payload_size:
                                continue
                            payload = await response.content.readexactly(payload_size)
                            title_match = TITLE_PATTERN.search(payload)
                            if not title_match:
                                continue
                            title = (
                                title_match.group(2)
                                .decode("utf-8", errors="replace")
                                .strip("\x00\r\n\t ")
                            )[:MAX_TEXT]
                            if title and title != self.title:
                                self.title = title
                                self.updated_at = time.monotonic()
                                self.revision += 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # Never log URLs or response bodies; signed stream URLs can contain tokens.
                    self.logger.debug(
                        "Radio Filter: ICY metadata monitor disconnected (%s)",
                        type(exc).__name__,
                    )
                if attempt < len(RECONNECT_DELAYS):
                    await asyncio.sleep(RECONNECT_DELAYS[attempt])
            self.logger.warning("Radio Filter: ICY monitor stopped after repeated failures")
