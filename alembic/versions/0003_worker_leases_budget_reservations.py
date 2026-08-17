"""Add worker leases and budget reservations.

Revision ID: 0003_worker_leases_budget_reservations
Revises: 0002_external_call_recovery
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_worker_leases_budget_reservations"
down_revision: str | None = "0002_external_call_recovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMING_CONVENTION = {
    "uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s",
}


def upgrade() -> None:
    with op.batch_alter_table(
        "tasks", recreate="always", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.add_column(sa.Column("lease_token", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3")
        )
        batch_op.create_unique_constraint("uq_tasks_lease_token", ["lease_token"])
        batch_op.create_check_constraint("ck_tasks_attempt_non_negative", "attempt >= 0")
        batch_op.create_check_constraint("ck_tasks_max_attempts_positive", "max_attempts > 0")
        batch_op.create_check_constraint(
            "ck_tasks_attempt_within_max", "attempt <= max_attempts"
        )
    op.create_index(
        "ix_tasks_claimable",
        "tasks",
        ["run_id", "state", "intent_type", "task_id"],
    )
    op.create_index(
        "ix_tasks_lease_expiry",
        "tasks",
        ["run_id", "state", "lease_expires_at"],
    )

    with op.batch_alter_table(
        "cost_entries", recreate="always", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.create_unique_constraint(
            "uq_cost_entries_run_id_external_call_id",
            ["run_id", "external_call_id"],
        )

    op.create_table(
        "budget_reservations",
        sa.Column("reservation_id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("external_call_id", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="reserved"),
        sa.Column("estimated_model_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.String(), nullable=False, server_default="0"),
        sa.Column("estimated_hypotheses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_matches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actual_model_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actual_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actual_output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actual_cost_usd", sa.String(), nullable=False, server_default="0"),
        sa.Column("actual_hypotheses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actual_matches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], name="fk_budget_reservations_run"),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.task_id"], name="fk_budget_reservations_task"
        ),
        sa.UniqueConstraint(
            "run_id", "idempotency_key", name="uq_budget_reservations_run_id_idempotency_key"
        ),
        sa.UniqueConstraint(
            "run_id", "task_id", name="uq_budget_reservations_run_id_task_id"
        ),
        sa.UniqueConstraint(
            "run_id",
            "external_call_id",
            name="uq_budget_reservations_run_id_external_call_id",
        ),
        sa.CheckConstraint(
            "state IN ('reserved', 'settled', 'released')",
            name="ck_budget_reservations_state",
        ),
        sa.CheckConstraint(
            "estimated_model_calls >= 0 AND estimated_input_tokens >= 0 "
            "AND estimated_output_tokens >= 0 "
            "AND CAST(estimated_cost_usd AS NUMERIC) >= 0 "
            "AND estimated_hypotheses >= 0 AND estimated_matches >= 0",
            name="ck_budget_reservations_estimates_non_negative",
        ),
        sa.CheckConstraint(
            "actual_model_calls >= 0 AND actual_input_tokens >= 0 "
            "AND actual_output_tokens >= 0 AND CAST(actual_cost_usd AS NUMERIC) >= 0 "
            "AND actual_hypotheses >= 0 AND actual_matches >= 0",
            name="ck_budget_reservations_actuals_non_negative",
        ),
        sa.CheckConstraint("version > 0", name="ck_budget_reservations_version_positive"),
        sa.CheckConstraint(
            "state = 'settled' OR (actual_model_calls = 0 AND actual_input_tokens = 0 "
            "AND actual_output_tokens = 0 AND CAST(actual_cost_usd AS NUMERIC) = 0 "
            "AND actual_hypotheses = 0 AND actual_matches = 0)",
            name="ck_budget_reservations_state_consistency",
        ),
    )
    op.create_index(
        "ix_budget_reservations_run_state",
        "budget_reservations",
        ["run_id", "state"],
    )
    op.create_index(
        "ix_budget_reservations_task", "budget_reservations", ["task_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_budget_reservations_task", table_name="budget_reservations")
    op.drop_index("ix_budget_reservations_run_state", table_name="budget_reservations")
    op.drop_table("budget_reservations")
    with op.batch_alter_table(
        "cost_entries", recreate="always", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            "uq_cost_entries_run_id_external_call_id", type_="unique"
        )
    op.drop_index("ix_tasks_lease_expiry", table_name="tasks")
    op.drop_index("ix_tasks_claimable", table_name="tasks")
    with op.batch_alter_table(
        "tasks", recreate="always", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint("ck_tasks_attempt_within_max", type_="check")
        batch_op.drop_constraint("ck_tasks_max_attempts_positive", type_="check")
        batch_op.drop_constraint("ck_tasks_attempt_non_negative", type_="check")
        batch_op.drop_constraint("uq_tasks_lease_token", type_="unique")
        batch_op.drop_column("max_attempts")
        batch_op.drop_column("heartbeat_at")
        batch_op.drop_column("lease_token")
