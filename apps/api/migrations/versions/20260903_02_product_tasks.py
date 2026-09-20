"""Add durable GEO product task records for the P2 vertical slice.

Expand-only: no SQLite import, dual write, or runtime switch is performed.
"""
from __future__ import annotations

from alembic import op

from app.product.persistence.models import product_tasks


revision = "20260903_02"
down_revision = "20260903_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    product_tasks.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Production failures after a switch are repaired forward.  This is only
    # available for an unaccepted pre-switch test database.
    product_tasks.drop(bind=op.get_bind(), checkfirst=True)
