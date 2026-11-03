from __future__ import annotations

from shopping_agent.models import ListingDetail, SearchQuery, SearchResult
from shopping_agent.platforms.base import PlatformCollector


class ZhuanzhuanCollector(PlatformCollector):
    platform = "zhuanzhuan"

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        raise NotImplementedError("Zhuanzhuan web collection is not implemented yet.")

    async def fetch_detail(self, result: SearchResult) -> ListingDetail:
        raise NotImplementedError("Zhuanzhuan detail extraction is not implemented yet.")
