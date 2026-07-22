from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import decode_token
from .database import get_session
from .models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

_credentials_error = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    user_id = decode_token(token)
    if user_id is None:
        raise _credentials_error
    user = await session.get(User, user_id)
    if user is None:
        raise _credentials_error
    return user


async def get_user_from_token(token: str, session: AsyncSession) -> User | None:
    """Token resolver for the WebSocket clerk (passed as a query param)."""
    user_id = decode_token(token)
    if user_id is None:
        return None
    return await session.get(User, user_id)
