"""Optional AI helpers powered by Google Gemini (free tier).

Everything here is a no-op / graceful failure when GEMINI_API_KEY is unset,
so the core API runs with zero external keys. Add a key from
https://aistudio.google.com to switch these on.
"""
import asyncio
import base64

import httpx

from ..config import settings

_VISION_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]


async def _gemini_post_with_retry(client: httpx.AsyncClient, url_template: str, body: dict) -> httpx.Response:
    """POST to Gemini with exponential backoff on 429/503, trying fallback models."""
    for model in _VISION_MODELS:
        url = url_template.format(model=model)
        for attempt in range(4):
            resp = await client.post(url, params={"key": settings.gemini_api_key}, json=body)
            if resp.status_code in (429, 503) and attempt < 3:
                await asyncio.sleep(2 ** attempt)
                continue
            break
        if resp.status_code not in (429, 503):
            return resp
    return resp  # return last response so caller can handle it


def ai_enabled() -> bool:
    return bool(settings.gemini_api_key)


async def embed_text(text: str) -> list[float] | None:
    """Return a description embedding, or None if AI is disabled / fails."""
    if not ai_enabled() or not text:
        return None
    url = f"{settings.gemini_base_url}/models/{settings.embedding_model}:embedContent"
    body = {
        "model": f"models/{settings.embedding_model}",
        "content": {"parts": [{"text": text[:8000]}]},
        "outputDimensionality": settings.embedding_dim,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url, params={"key": settings.gemini_api_key}, json=body
            )
            resp.raise_for_status()
            return resp.json()["embedding"]["values"]
    except Exception:
        # Embeddings are best-effort; never block adding a book on them.
        return None


async def identify_book_from_image(image_bytes: bytes, mime: str) -> str | None:
    """Use Gemini vision to read a cover and return a 'title author' guess.

    Returns None on any failure (rate limit, bad response, etc.) so the
    caller can surface a clean 422 rather than a 500.
    """
    if not ai_enabled():
        return None
    url_template = f"{settings.gemini_base_url}/models/{{model}}:generateContent"
    body = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "This is a photo of a book cover. Reply with ONLY the "
                            "book title and author, nothing else. If unsure, give "
                            "your best guess."
                        )
                    },
                    {
                        "inline_data": {
                            "mime_type": mime,
                            "data": base64.b64encode(image_bytes).decode(),
                        }
                    },
                ]
            }
        ]
    }
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            resp = await _gemini_post_with_retry(client, url_template, body)
            if resp.status_code not in (200,):
                return None
            data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return None
