"""Read live ICY StreamTitle metadata while Music Assistant plays a replacement."""

from __future__ import annotations

import asyncio
import re
import time

from aiohttp import ClientTimeout


class IcyMonitor:
    """Second connection to a station, independent of the MA player queue."""

    def __init__(self, session, url: str, logger) -> None:
        """Initialize the ICY monitor."""
        self.session = session
        self.url = url
        self.logger = logger
        self.title = ""
        self.updated_at = 0.0
        self.revision = 0
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Begin monitoring."""
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Shut down and release the stream connection."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        """Reconnect after interruptions, only if the stream supports ICY."""
        while True:
            try:
                timeout = ClientTimeout(total=None, connect=10, sock_read=30)
                async with self.session.get(
                    self.url, headers={"Icy-MetaData": "1"},
                    timeout=timeout, allow_redirects=True,
                ) as response:
                    response.raise_for_status()
                    interval = int(response.headers.get("icy-metaint", "0"))
                    if not 1 <= interval <= 1024 * 1024:
                        self.logger.warning("Radio Filter: station provides no ICY metadata")
                        return
                    while True:
                        await response.content.readexactly(interval)
                        length = (await response.content.readexactly(1))[0] * 16
                        if length == 0:
                            continue
                        raw = await response.content.readexactly(length)
                        match = re.search(rb"StreamTitle='([^']*)'", raw)
                        if not match:
                            continue
                        title = match.group(1).decode("utf-8", errors="replace").strip()
                        if title and title != self.title:
                            self.title = title
                            self.updated_at = time.monotonic()
                            self.revision += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.debug("Radio Filter: monitor reconnecting: %s", exc)
                await asyncio.sleep(5)
