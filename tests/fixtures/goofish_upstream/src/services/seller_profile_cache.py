# Upstream offline fixture, commit 77f8d75869acd65f9dba72731b95c7c49ea67bdf.
# MIT License
#
# Copyright (c) 2025 dingyufei615
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""
卖家资料缓存服务
"""
import asyncio
import copy
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional


SellerProfileLoader = Callable[[str], Awaitable[dict]]


@dataclass(frozen=True)
class _CacheEntry:
    value: dict
    expires_at: float


class SellerProfileCache:
    """带 TTL 和并发合并的卖家资料缓存。"""

    def __init__(
        self,
        ttl_seconds: int = 1800,
        time_source: Optional[Callable[[], float]] = None,
    ) -> None:
        self._ttl_seconds = max(0, ttl_seconds)
        self._time_source = time_source or time.monotonic
        self._entries: dict[str, _CacheEntry] = {}
        self._inflight: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    def _now(self) -> float:
        return float(self._time_source())

    def _clone(self, value: dict) -> dict:
        return copy.deepcopy(value)

    def _get_entry_value(self, user_id: str) -> Optional[dict]:
        entry = self._entries.get(user_id)
        if entry is None:
            return None
        if entry.expires_at < self._now():
            self._entries.pop(user_id, None)
            return None
        return self._clone(entry.value)

    async def get_or_load(self, user_id: str, loader: SellerProfileLoader) -> dict:
        async with self._lock:
            cached_value = self._get_entry_value(user_id)
            if cached_value is not None:
                return cached_value
            task = self._inflight.get(user_id)
            if task is None:
                task = asyncio.create_task(self._load_and_store(user_id, loader))
                self._inflight[user_id] = task
        return self._clone(await task)

    async def _load_and_store(self, user_id: str, loader: SellerProfileLoader) -> dict:
        try:
            value = self._clone(await loader(user_id))
            expires_at = self._now() + self._ttl_seconds
            async with self._lock:
                self._entries[user_id] = _CacheEntry(value=value, expires_at=expires_at)
            return value
        finally:
            async with self._lock:
                self._inflight.pop(user_id, None)
