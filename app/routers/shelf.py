from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import SessionLocal, get_session
from ..deps import get_current_user
from ..models import Book, ShelfEntry, ShelfStatus, User
from ..schemas import AddBookRequest, ManualBookRequest, ShelfEntryOut, UpdateShelfEntryRequest
from ..services import embeddings, google_books

router = APIRouter(prefix="/shelf", tags=["shelf"])


async def _attach_rating_stats(session: AsyncSession, book: Book) -> None:
    """Compute the community average rating for a book and stash it on the
    (transient) ORM instance so BookOut.from_attributes picks it up."""
    result = await session.execute(
        select(func.avg(ShelfEntry.rating), func.count(ShelfEntry.rating)).where(
            ShelfEntry.book_id == book.id, ShelfEntry.rating.isnot(None)
        )
    )
    avg, count = result.one()
    book.average_rating = round(float(avg), 2) if avg is not None else None
    book.ratings_count = count or 0


async def _embed_book(book_id) -> None:
    """Background task: compute and store the description embedding."""
    async with SessionLocal() as session:
        book = await session.get(Book, book_id)
        if book is None:
            return
        parts = []
        if book.description:
            parts.append(book.description)
        if book.categories:
            parts.append("Genres: " + ", ".join(book.categories))
        if book.page_count:
            parts.append(f"Pages: {book.page_count}")
        if not parts:
            return
        vector = await embeddings.embed_text(" ".join(parts))
        if vector is not None:
            book.embedding = vector
            book.description = None  # free space — embedding replaces it for semantic search
            await session.commit()


async def _get_or_create_book(
    session: AsyncSession,
    google_id: str,
    manual: ManualBookRequest | None = None,
) -> Book:
    result = await session.execute(select(Book).where(Book.google_id == google_id))
    book = result.scalar_one_or_none()
    if book:
        return book

    if google_id.startswith("manual:"):
        if manual is None:
            raise HTTPException(
                status_code=422,
                detail="Provide book details in the `manual` field when adding a manual book.",
            )
        book = Book(
            google_id=google_id,
            title=manual.title,
            authors=manual.authors,
            description=manual.description,
            thumbnail=manual.thumbnail,
            published_date=manual.published_date,
            page_count=manual.page_count,
            categories=manual.categories,
        )
    else:
        volume = await google_books.get_volume(google_id)
        if volume is None:
            raise HTTPException(status_code=404, detail="Book not found.")
        book = Book(
            google_id=volume.google_id,
            title=volume.title,
            authors=volume.authors,
            description=volume.description,
            thumbnail=volume.thumbnail,
            published_date=volume.published_date,
            page_count=volume.page_count,
            categories=volume.categories,
        )

    session.add(book)
    await session.commit()
    await session.refresh(book)
    return book


@router.post("", response_model=ShelfEntryOut, status_code=201)
async def add_to_shelf(
    payload: AddBookRequest,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Add a book to the to-read pile. Caches the book and embeds it (if AI on)."""
    book = await _get_or_create_book(session, payload.google_id, payload.manual)

    existing = await session.execute(
        select(ShelfEntry).where(
            ShelfEntry.user_id == user.id, ShelfEntry.book_id == book.id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Already on your shelf.")

    entry = ShelfEntry(user_id=user.id, book_id=book.id, status=ShelfStatus.to_read)
    session.add(entry)
    await session.commit()
    await session.refresh(entry)

    if book.embedding is None:
        background.add_task(_embed_book, book.id)

    return entry


@router.get("", response_model=list[ShelfEntryOut])
async def list_shelf(
    status: ShelfStatus | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """List the user's pile, optionally filtered by status."""
    stmt = select(ShelfEntry).where(ShelfEntry.user_id == user.id)
    if status:
        stmt = stmt.where(ShelfEntry.status == status)
    stmt = stmt.order_by(ShelfEntry.added_at.desc())
    result = await session.execute(stmt)
    return result.scalars().all()


@router.get("/{entry_id}", response_model=ShelfEntryOut)
async def get_shelf_entry(
    entry_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Fetch a single shelf entry, with the book's community rating stats."""
    entry = await session.get(ShelfEntry, entry_id)
    if entry is None or entry.user_id != user.id:
        raise HTTPException(status_code=404, detail="Shelf entry not found.")
    await _attach_rating_stats(session, entry.book)
    return entry


@router.patch("/{entry_id}", response_model=ShelfEntryOut)
async def update_status(
    entry_id: str,
    payload: UpdateShelfEntryRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Change reading status and/or personal rating."""
    entry = await session.get(ShelfEntry, entry_id)
    if entry is None or entry.user_id != user.id:
        raise HTTPException(status_code=404, detail="Shelf entry not found.")

    if payload.status is not None:
        now = datetime.now(timezone.utc)
        if payload.status == ShelfStatus.reading and entry.started_at is None:
            entry.started_at = now
        if payload.status == ShelfStatus.finished and entry.finished_at is None:
            entry.finished_at = now
        entry.status = payload.status

    if payload.rating is not None:
        entry.rating = payload.rating

    await session.commit()
    await session.refresh(entry)
    await _attach_rating_stats(session, entry.book)
    return entry


@router.delete("/{entry_id}", status_code=204)
async def remove_from_shelf(
    entry_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    entry = await session.get(ShelfEntry, entry_id)
    if entry is None or entry.user_id != user.id:
        raise HTTPException(status_code=404, detail="Shelf entry not found.")
    await session.delete(entry)
    await session.commit()
