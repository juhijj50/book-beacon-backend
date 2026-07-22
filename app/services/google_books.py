import httpx
from fastapi import HTTPException

from ..config import settings
from ..schemas import SearchResult

_BASE = "https://www.googleapis.com/books/v1"


def _parse_volume(item: dict) -> SearchResult:
    info = item.get("volumeInfo", {})
    images = info.get("imageLinks", {})
    thumbnail = images.get("thumbnail") or images.get("smallThumbnail")
    # Use https so mixed-content errors don't bite browser clients
    if thumbnail:
        thumbnail = thumbnail.replace("http://", "https://")
    return SearchResult(
        google_id=item.get("id", ""),
        title=info.get("title", "Untitled"),
        authors=info.get("authors", []),
        description=info.get("description"),
        thumbnail=thumbnail,
        published_date=info.get("publishedDate"),
        page_count=info.get("pageCount"),
        categories=info.get("categories", [])[:5],
    )


async def search_books(query: str, max_results: int = 5) -> list[SearchResult]:
    params: dict = {
        "q": query,
        "maxResults": min(max_results, 40),
        "printType": "books",
    }
    if settings.google_books_api_key:
        params["key"] = settings.google_books_api_key
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{_BASE}/volumes", params=params)
        if resp.status_code == 429:
            raise HTTPException(status_code=429, detail="Search rate limit hit. Try again in a moment.")
        resp.raise_for_status()
        data = resp.json()
    return [_parse_volume(item) for item in data.get("items", [])]


async def get_volume(google_id: str) -> SearchResult | None:
    params: dict = {}
    if settings.google_books_api_key:
        params["key"] = settings.google_books_api_key
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{_BASE}/volumes/{google_id}", params=params)
        if resp.status_code == 404:
            return None
        if resp.status_code == 429:
            raise HTTPException(status_code=429, detail="Search rate limit hit. Try again in a moment.")
        resp.raise_for_status()
        item = resp.json()
    return _parse_volume(item)
