"""The keeper — a Gemini agent with tools over the user's own pile.

The loop: send the conversation to Gemini with tool declarations; if it asks
to call a tool, run it, feed the result back, and repeat until it replies with
text. Requires GEMINI_API_KEY (the keeper is "off duty" without it).
"""
import asyncio
import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Book, ShelfEntry, ShelfStatus, User
from . import embeddings, google_books

SYSTEM_INSTRUCTION = (
    "You are the keeper of Book Beacon, a lighthouse-side haven for readers. "
    "You are warm, a little whimsical, and never pushy — every story finds its "
    "light here. Keep replies short and conversational. When the reader wants "
    "something to read next, prefer recommending from their own pile using the "
    "recommend_from_my_pile tool; use search_books only to discover new titles "
    "they don't own yet. Use get_my_stats when they ask how they're doing. "
    "Always speak in character as the keeper."
)

TOOLS = [
    {
        "function_declarations": [
            {
                "name": "search_books",
                "description": "Search the wider catalog for new books to discover.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Title, author, topic, or vibe."}
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "recommend_from_my_pile",
                "description": "Suggest unread books already on the reader's shelf that match a mood or topic.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The mood, theme, or kind of book wanted."}
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "get_my_stats",
                "description": "How many books the reader has finished, is reading, and has waiting in their pile.",
                "parameters": {"type": "object", "properties": {}},
            },
        ]
    }
]


async def _tool_search_books(args: dict, session: AsyncSession, user: User) -> dict:
    results = await google_books.search_books(args.get("query", ""), max_results=6)
    return {"books": [{"title": r.title, "authors": r.authors, "google_id": r.google_id} for r in results]}


async def _tool_recommend(args: dict, session: AsyncSession, user: User) -> dict:
    vector = await embeddings.embed_text(args.get("query", ""))
    if vector is None:
        return {"books": [], "note": "Recommendations are unavailable right now."}
    stmt = (
        select(Book)
        .join(ShelfEntry, ShelfEntry.book_id == Book.id)
        .where(
            ShelfEntry.user_id == user.id,
            ShelfEntry.status == ShelfStatus.to_read,
            Book.embedding.isnot(None),
        )
        .order_by(Book.embedding.cosine_distance(vector))
        .limit(5)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {"books": [{"title": b.title, "authors": b.authors, "google_id": b.google_id} for b in rows]}


async def _tool_stats(args: dict, session: AsyncSession, user: User) -> dict:
    async def count_status(status: ShelfStatus) -> int:
        return await session.scalar(
            select(func.count(ShelfEntry.id)).where(
                ShelfEntry.user_id == user.id, ShelfEntry.status == status
            )
        ) or 0

    return {
        "finished": await count_status(ShelfStatus.finished),
        "reading": await count_status(ShelfStatus.reading),
        "waiting_in_pile": await count_status(ShelfStatus.to_read),
    }


_TOOL_FNS = {
    "search_books": _tool_search_books,
    "recommend_from_my_pile": _tool_recommend,
    "get_my_stats": _tool_stats,
}


_FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]


class ClerkRateLimitError(Exception):
    """All models exhausted their retry budget due to 429/503."""


async def _post_with_retry(client: httpx.AsyncClient, base_url: str, api_key: str, payload: dict) -> httpx.Response:
    """Try each model in _FALLBACK_MODELS, retrying transient errors with backoff."""
    for model in _FALLBACK_MODELS:
        url = f"{base_url}/models/{model}:generateContent"
        for attempt in range(4):
            resp = await client.post(url, params={"key": api_key}, json=payload)
            if resp.status_code in (429, 503) and attempt < 3:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s
                continue
            break
        if resp.status_code not in (429, 503):
            return resp
    raise ClerkRateLimitError()


async def run_clerk(history: list[dict], session: AsyncSession, user: User) -> str:
    """Run one clerk turn. `history` is a list of {role, parts} Gemini contents."""
    contents = list(history)  # copy: tool turns shouldn't pollute persisted history
    base_url = settings.gemini_base_url
    base = {"system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]}, "tools": TOOLS}

    async with httpx.AsyncClient(timeout=40) as client:
        for _ in range(5):
            resp = await _post_with_retry(client, base_url, settings.gemini_api_key, {**base, "contents": contents})
            resp.raise_for_status()
            candidate = resp.json()["candidates"][0]["content"]
            parts = candidate.get("parts", [])

            calls = [p["functionCall"] for p in parts if "functionCall" in p]
            if not calls:
                # Skip thought-only parts (gemini-2.5 thinking mode returns
                # parts with "thoughtSignature" but empty or missing "text")
                text = "".join(
                    p["text"] for p in parts
                    if "text" in p and p["text"] and "functionCall" not in p
                ).strip()
                return text or "Sorry, I lost my train of thought. Ask me again?"

            contents.append(candidate)  # echo the model's tool-call turn back
            response_parts = []
            for call in calls:
                fn = _TOOL_FNS.get(call["name"])
                result = (
                    await fn(call.get("args", {}), session, user)
                    if fn
                    else {"error": "unknown tool"}
                )
                response_parts.append(
                    {"functionResponse": {"name": call["name"], "response": result}}
                )
            contents.append({"role": "user", "parts": response_parts})

    return "Sorry, I lost my train of thought behind the counter. Ask me again?"
