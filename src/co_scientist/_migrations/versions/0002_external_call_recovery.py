"""Add external-call recovery envelopes.

Revision ID: 0002_external_call_recovery
Revises: 0001_core_tables
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_external_call_recovery"
down_revision: str | None = "0001_core_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "external_calls",
        sa.Column("execution_context_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "external_calls",
        sa.Column("agent_result_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("external_calls", "agent_result_json")
    op.drop_column("external_calls", "execution_context_json")
