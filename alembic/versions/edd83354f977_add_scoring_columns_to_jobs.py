"""Add scoring columns to jobs.

Revision ID: edd83354f977
Revises: c91e7a4d2b6f
Create Date: 2026-09-24 23:38:12.905995

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "edd83354f977"
down_revision: str | Sequence[str] | None = "c91e7a4d2b6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add optional archetype scoring data to jobs."""
    with op.batch_alter_table("jobsql", schema=None) as batch_op:
        batch_op.add_column(sa.Column("archetype_score", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column("best_archetype", sa.String(), nullable=True),
        )
        batch_op.add_column(sa.Column("fit_reasons", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("gaps", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove optional archetype scoring data from jobs."""
    with op.batch_alter_table("jobsql", schema=None) as batch_op:
        batch_op.drop_column("gaps")
        batch_op.drop_column("fit_reasons")
        batch_op.drop_column("best_archetype")
        batch_op.drop_column("archetype_score")
