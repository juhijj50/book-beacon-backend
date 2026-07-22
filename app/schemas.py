import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import ShelfStatus, VaultEntryType


# --- Auth ---
class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: EmailStr
    name: str


# --- Google Books search results (not yet persisted) ---
class SearchResult(BaseModel):
    google_id: str
    title: str
    authors: list[str] = []
    description: str | None = None
    thumbnail: str | None = None
    published_date: str | None = None
    page_count: int | None = None
    categories: list[str] = []


# --- Book as stored in our catalog ---
class BookOut(SearchResult):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    average_rating: float | None = None
    ratings_count: int = 0


# --- Requests ---
class AddBookRequest(BaseModel):
    google_id: str
    manual: "ManualBookRequest | None" = None


class ManualBookRequest(BaseModel):
    title: str
    authors: list[str] = []
    description: str | None = None
    thumbnail: str | None = None
    published_date: str | None = None
    page_count: int | None = None
    categories: list[str] = []


class UpdateShelfEntryRequest(BaseModel):
    status: ShelfStatus | None = None
    rating: int | None = Field(None, ge=1, le=5)


# --- Responses ---
class ShelfEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: ShelfStatus
    rating: int | None
    added_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    book: BookOut


# --- Vault (per-book words, quotes, notes) ---
class AddVaultEntryRequest(BaseModel):
    book_id: uuid.UUID
    entry_type: VaultEntryType
    content: str
    page_number: int | None = None


class UpdateVaultEntryRequest(BaseModel):
    content: str | None = None
    page_number: int | None = None


class VaultEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entry_type: VaultEntryType
    content: str
    page_number: int | None
    created_at: datetime
    book: BookOut


