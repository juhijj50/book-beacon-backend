import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..database import SessionLocal
from ..deps import get_user_from_token
from ..models import ChatMessage, User
from ..services import clerk, embeddings
from ..services.clerk import ClerkRateLimitError

log = logging.getLogger(__name__)

router = APIRouter(tags=["clerk"])

_HISTORY_LIMIT = 20


async def _load_history(session, user: User) -> list[dict]:
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.user_id == user.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(_HISTORY_LIMIT)
    )
    messages = list(reversed(result.scalars().all()))
    return [
        {"role": "model" if m.role == "keeper" else "user", "parts": [{"text": m.content}]}
        for m in messages
    ]


@router.websocket("/ws/clerk")
async def clerk_ws(ws: WebSocket, token: str = Query(...)):
    await ws.accept()

    if not embeddings.ai_enabled():
        await ws.send_json({"role": "system", "content": "The keeper is off duty (set GEMINI_API_KEY)."})
        await ws.close()
        return

    async with SessionLocal() as session:
        user = await get_user_from_token(token, session)
        if user is None:
            await ws.send_json({"role": "system", "content": "Authentication failed."})
            await ws.close(code=1008)
            return

        history = await _load_history(session, user)
        await ws.send_json({"role": "system", "content": "The keeper looks up and smiles."})

        try:
            while True:
                text = await ws.receive_text()

                session.add(ChatMessage(user_id=user.id, role="user", content=text))
                await session.commit()
                history.append({"role": "user", "parts": [{"text": text}]})

                await ws.send_json({"role": "system", "content": "typing"})
                try:
                    reply = await clerk.run_clerk(history, session, user)
                except ClerkRateLimitError:
                    await ws.send_json({
                        "role": "system",
                        "content": "rate_limited",
                    })
                    continue
                except Exception as exc:
                    log.exception("clerk.run_clerk failed: %s", exc)
                    await ws.send_json(
                        {"role": "system", "content": "The keeper got distracted. Try again in a moment."}
                    )
                    continue

                if not reply:
                    await ws.send_json({"role": "system", "content": "The keeper got distracted. Try again in a moment."})
                    continue

                history.append({"role": "model", "parts": [{"text": reply}]})
                session.add(ChatMessage(user_id=user.id, role="keeper", content=reply))
                await session.commit()

                await ws.send_json({"role": "keeper", "content": reply})
        except WebSocketDisconnect:
            return
