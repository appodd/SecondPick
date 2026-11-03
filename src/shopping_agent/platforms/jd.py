from __future__ import annotations

from shopping_agent.models import ListingDetail, SearchQuery, SearchResult
from shopping_agent.platforms.base import PlatformCollector


class JdCollector(PlatformCollector):
    platform = "jd"

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        raise NotImplementedError("JD price baseline collection is not implemented yet.")

    async def fetch_detail(self, result: SearchResult) -> ListingDetail:
        raise NotImplementedError("JD detail extraction is not implemented yet.")
