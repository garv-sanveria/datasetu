"""Change Data Capture (CDC) worker for DataSetu.

What this module does:
1. Continuously polls upstream dataset sources (HTTP URLs or local files) for changes.
2. For HTTP(S) URLs:
   - Issues async HEAD requests with `If-None-Match` and `If-Modified-Since` headers.
   - Detects upstream updates via HTTP 200 response headers (bumping ETag or Last-Modified)
     while receiving 304 Not Modified when unchanged (zero wasted bandwidth).
3. For Local Files:
   - Monitors filesystem modification timestamps (`mtime`) and SHA-256 content hashes.
4. When a mutation is detected:
   - Invokes the `on_change` callback, allowing DataSetu to re-run the compiler pipeline
     and execute an atomic zero-downtime transactional swap (`store.swap()`).

Why it exists:
Government portals frequently revise scheme figures, post budget amendments, and update
allocations. CDC ensures that downstream APIs stay synchronized with source data automatically.

How it connects to other modules:
- Monitored by the CLI worker (`datasetu serve --cdc`).
- Invokes `sniffer.sniff()` -> `normalizer.normalize()` -> `store.swap()`.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from pathlib import Path
from typing import Any, Callable, Optional, Union

import httpx


class CDCWorker:
    """Asynchronous worker that monitors source datasets and triggers pipeline re-compilation."""

    def __init__(
        self,
        source: Union[str, Path],
        interval_s: float = 2.0,
        on_change: Optional[Callable[[Union[str, Path]], Any]] = None,
    ):
        self.source = source
        self.interval_s = max(0.1, interval_s)
        self.on_change = on_change

        self.source_str = str(source)
        self.is_url = self.source_str.startswith("http://") or self.source_str.startswith("https://")

        # HTTP state
        self.last_etag: Optional[str] = None
        self.last_modified: Optional[str] = None

        # Local file state
        self.last_mtime: Optional[float] = None
        self.last_hash: Optional[str] = None

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._initialize_baseline()

    def _initialize_baseline(self) -> None:
        """Establish the initial baseline state so initial startup does not trigger a change."""
        if not self.is_url:
            p = Path(self.source)
            if p.exists():
                self.last_mtime = p.stat().st_mtime
                self.last_hash = hashlib.sha256(p.read_bytes()).hexdigest()

    async def _notify_change(self) -> None:
        """Execute the on_change callback safely whether synchronous or asynchronous."""
        if self.on_change is None:
            return

        try:
            if inspect.iscoroutinefunction(self.on_change):
                await self.on_change(self.source)
            else:
                self.on_change(self.source)
        except Exception as err:
            # Prevent callback errors from terminating the CDC loop
            print(f"[DataSetu CDC] Error in on_change callback: {err}")

    async def check_once(self) -> bool:
        """Perform a single check against the source. Returns True if a mutation was detected."""
        if self.is_url:
            return await self._check_url()
        else:
            return await self._check_local_file()

    async def _check_url(self) -> bool:
        """Check remote URL using HTTP HEAD with conditional headers."""
        headers: dict[str, str] = {}
        if self.last_etag:
            headers["If-None-Match"] = self.last_etag
        if self.last_modified:
            headers["If-Modified-Since"] = self.last_modified

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            try:
                resp = await client.head(self.source_str, headers=headers)
            except Exception as err:
                print(f"[DataSetu CDC] Network check failed for {self.source_str}: {err}")
                return False

            if resp.status_code == 304:
                # Upstream not modified
                return False

            if resp.status_code == 200:
                new_etag = resp.headers.get("etag")
                new_lm = resp.headers.get("last-modified")

                # If ETag / Last-Modified headers are present, compare them
                if new_etag or new_lm:
                    has_changed = (
                        (new_etag and new_etag != self.last_etag)
                        or (new_lm and new_lm != self.last_modified)
                    )
                    if has_changed:
                        self.last_etag = new_etag
                        self.last_modified = new_lm
                        await self._notify_change()
                        return True
                    return False

                # Fallback: fetch content and compare SHA-256 hash if server provides no headers
                get_resp = await client.get(self.source_str)
                new_hash = hashlib.sha256(get_resp.content).hexdigest()
                if self.last_hash is None:
                    self.last_hash = new_hash
                    return False

                if new_hash != self.last_hash:
                    self.last_hash = new_hash
                    await self._notify_change()
                    return True

        return False

    async def _check_local_file(self) -> bool:
        """Check local filesystem modification time and content hash."""
        p = Path(self.source)
        if not p.exists():
            return False

        current_mtime = p.stat().st_mtime
        if self.last_mtime is None:
            self.last_mtime = current_mtime
            self.last_hash = hashlib.sha256(p.read_bytes()).hexdigest()
            return False

        # Only check content hash if mtime has changed
        if current_mtime != self.last_mtime:
            new_hash = hashlib.sha256(p.read_bytes()).hexdigest()
            if new_hash != self.last_hash:
                self.last_mtime = current_mtime
                self.last_hash = new_hash
                await self._notify_change()
                return True
            else:
                # mtime touched without content modification
                self.last_mtime = current_mtime

        return False

    async def _poll_loop(self) -> None:
        """Background polling loop."""
        while self._running:
            try:
                await self.check_once()
            except Exception as err:
                print(f"[DataSetu CDC] Exception in polling worker: {err}")

            await asyncio.sleep(self.interval_s)

    def start(self) -> asyncio.Task:
        """Start the async polling loop task."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._poll_loop())
        return self._task

    def stop(self) -> None:
        """Stop the background polling worker."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
