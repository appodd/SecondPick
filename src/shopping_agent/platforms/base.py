from __future__ import annotations

from abc import ABC, abstractmethod

from shopping_agent.models import ListingDetail, SearchQuery, SearchResult


class PlatformCollector(ABC):
    platform: str

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[SearchResult]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_detail(self, result: SearchResult) -> ListingDetail:
        raise NotImplementedError
