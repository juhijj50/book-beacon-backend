from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..deps import get_current_user
from ..models import Book, User, VaultEntry, VaultEntryType
from ..schemas import AddVaultEntryRequest, UpdateVaultEntryRequest, VaultEntryOut

router = APIRouter(prefix="/vault", tags=["vault"])


@router.post("", response_model=VaultEntryOut, status_code=201)
async def add_vault_entry(
    payload: AddVaultEntryRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Save a word, quote, or note against a book already in the catalog."""
    book = await session.get(Book, payload.book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found.")

    entry = VaultEntry(
        user_id=user.id,
        book_id=book.id,
        entry_type=payload.entry_type,
        content=payload.content,
        page_number=payload.page_number,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


@router.get("", response_model=list[VaultEntryOut])
async def list_vault_entries(
    book_id: str | None = None,
    entry_type: VaultEntryType | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """List the user's saved words/quotes/notes, optionally filtered by book or type."""
    stmt = select(VaultEntry).where(VaultEntry.user_id == user.id)
    if book_id:
        stmt = stmt.where(VaultEntry.book_id == book_id)
    if entry_type:
        stmt = stmt.where(VaultEntry.entry_type == entry_type)
    stmt = stmt.order_by(VaultEntry.created_at.desc())
    result = await session.execute(stmt)
    return result.scalars().all()


@router.patch("/{entry_id}", response_model=VaultEntryOut)
async def update_vault_entry(
    entry_id: str,
    payload: UpdateVaultEntryRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    entry = await session.get(VaultEntry, entry_id)
    if entry is None or entry.user_id != user.id:
        raise HTTPException(status_code=404, detail="Vault entry not found.")

    if payload.content is not None:
        entry.content = payload.content
    if payload.page_number is not None:
        entry.page_number = payload.page_number

    await session.commit()
    await session.refresh(entry)
    return entry


@router.delete("/{entry_id}", status_code=204)
async def remove_vault_entry(
    entry_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    entry = await session.get(VaultEntry, entry_id)
    if entry is None or entry.user_id != user.id:
        raise HTTPException(status_code=404, detail="Vault entry not found.")
    await session.delete(entry)
    await session.commit()
