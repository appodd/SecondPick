from __future__ import annotations

from shopping_agent.models import ListingDetail, SearchQuery, SearchResult
from shopping_agent.platforms.base import PlatformCollector


class XianyuCollector(PlatformCollector):
    platform = "xianyu"

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        raise NotImplementedError("Xianyu collection will be implemented after browser spike.")

    async def fetch_detail(self, result: SearchResult) -> ListingDetail:
        raise NotImplementedError("Xianyu detail extraction will be implemented after browser spike.")
