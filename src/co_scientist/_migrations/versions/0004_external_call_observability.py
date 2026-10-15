"""Add versioned external-call diagnostic and transport milestones.

Revision ID: 0004_external_call_observability
Revises: 0003_worker_leases_budget_reservations
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_external_call_observability"
down_revision: str | None = "0003_worker_leases_budget_reservations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_call_milestones",
        sa.Column("observation_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("external_call_id", sa.String(), nullable=False),
        sa.Column("milestone_version", sa.Integer(), nullable=False),
        sa.Column("milestone", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["external_call_id"], ["external_calls.external_call_id"],
            name="fk_external_call_milestones_external_call",
        ),
        sa.PrimaryKeyConstraint("observation_id"),
        sa.UniqueConstraint(
            "external_call_id", "milestone_version", "milestone", "source",
            name="uq_external_call_milestone_identity",
        ),
    )
    op.create_table(
        "external_call_failure_diagnostics",
        sa.Column("diagnostic_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("external_call_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("capture_layer", sa.String(), nullable=False),
        sa.Column("schema_id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("diagnostic_json", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["external_call_id"], ["external_calls.external_call_id"],
            name="fk_external_call_failure_diagnostics_external_call",
        ),
        sa.PrimaryKeyConstraint("diagnostic_id"),
        sa.UniqueConstraint(
            "external_call_id", "capture_layer",
            name="uq_external_call_failure_diagnostic_layer",
        ),
    )
    op.create_index(
        "ix_external_call_milestones_call_order",
        "external_call_milestones",
        ["external_call_id", "observation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_external_call_milestones_call_order", table_name="external_call_milestones"
    )
    op.drop_table("external_call_failure_diagnostics")
    op.drop_table("external_call_milestones")
