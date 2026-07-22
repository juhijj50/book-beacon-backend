"""drop garden_plants

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_garden_plants_user_id", table_name="garden_plants")
    op.drop_table("garden_plants")


def downgrade() -> None:
    op.create_table(
        "garden_plants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shelf_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plant_type", sa.String(32), nullable=False, server_default="sakura"),
        sa.Column("planted_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shelf_entry_id"], ["shelf_entries.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_garden_plants_user_id", "garden_plants", ["user_id"])
