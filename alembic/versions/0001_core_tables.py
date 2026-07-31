"""Create core persistence tables.

Revision ID: 0001_core_tables
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_core_tables"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("current_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("manifest_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "events",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("causation_id", sa.String(), nullable=True),
        sa.Column("correlation_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("run_id", "sequence"),
    )
    op.create_table(
        "tasks",
        sa.Column("task_id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("intent_type", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("lease_owner", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("run_id", "idempotency_key"),
    )
    op.create_table(
        "external_calls",
        sa.Column("external_call_id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model_or_tool", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("raw_artifact_ref_json", sa.Text(), nullable=True),
        sa.Column("validated_artifact_ref_json", sa.Text(), nullable=True),
        sa.Column("agent_result_id", sa.String(), nullable=True),
        sa.Column("applied_domain_sequence", sa.Integer(), nullable=True),
        sa.Column("parent_call_id", sa.String(), nullable=True),
        sa.Column("provider_response_id", sa.String(), nullable=True),
        sa.Column("usage_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("execution_context_json", sa.Text(), nullable=False),
        sa.Column("agent_result_json", sa.Text(), nullable=True),
    )
    op.create_table(
        "cost_entries",
        sa.Column("cost_entry_id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("external_call_id", sa.String(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.String(), nullable=False, server_default="0"),
        sa.Column("pricing_version", sa.String(), nullable=False),
    )
    op.create_table(
        "idempotency_commits",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("batch_fingerprint", sa.String(), nullable=False),
        sa.Column("first_sequence", sa.Integer(), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "idempotency_key"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_commits")
    op.drop_table("cost_entries")
    op.drop_table("external_calls")
    op.drop_table("tasks")
    op.drop_table("events")
    op.drop_table("runs")
