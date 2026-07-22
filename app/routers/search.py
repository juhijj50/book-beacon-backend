import uuid

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from ..schemas import ManualBookRequest, SearchResult
from ..services import embeddings, google_books

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=list[SearchResult])
async def search(q: str = Query(..., min_length=1), limit: int = 5):
    """Type-to-search the catalog. Powers the autocomplete in the search bar."""
    return await google_books.search_books(q, max_results=limit)


@router.post("/manual", response_model=SearchResult, status_code=201)
async def manual_entry(payload: ManualBookRequest):
    """Create a search result from manually entered book details.
    The returned google_id (prefixed manual:) can be passed to POST /shelf.
    """
    return SearchResult(
        google_id=f"manual:{uuid.uuid4().hex[:12]}",
        title=payload.title,
        authors=payload.authors,
        description=payload.description,
        thumbnail=payload.thumbnail,
        published_date=payload.published_date,
        page_count=payload.page_count,
        categories=payload.categories,
    )


@router.post("/identify", response_model=list[SearchResult])
async def identify(file: UploadFile = File(...)):
    """Upload a cover photo; Gemini reads the title, then we search for it.

    Returns 503 if no Gemini key is configured (core API stays key-free).
    """
    if not embeddings.ai_enabled():
        raise HTTPException(
            status_code=503,
            detail="Image search needs GEMINI_API_KEY. Set it to enable this.",
        )
    image_bytes = await file.read()
    guess = await embeddings.identify_book_from_image(
        image_bytes, file.content_type or "image/jpeg"
    )
    if not guess:
        raise HTTPException(
            status_code=422,
            detail="Could not read the cover — Gemini may be busy, please try again in a moment.",
        )
    return await google_books.search_books(guess, max_results=5)
