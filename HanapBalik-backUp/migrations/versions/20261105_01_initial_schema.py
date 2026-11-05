"""Create HanapBalik accounts, reports and claims.

Revision ID: 20261105_01
Revises:
"""

from alembic import op
import sqlalchemy as sa

revision = "20261105_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column("contact_number", sa.String(length=30), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("id_type", sa.String(length=50), nullable=False),
        sa.Column("id_number", sa.String(length=512), nullable=False),
        sa.Column("id_file_path", sa.String(length=255), nullable=False),
        sa.Column("id_file_type", sa.String(length=10), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_user_email", "user", ["email"], unique=True)

    op.create_table(
        "item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("report_type", sa.String(length=10), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("identifying_details", sa.Text(), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("photo_path", sa.String(length=255)),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Open"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "report_type IN ('Lost', 'Found')", name="ck_item_report_type"
        ),
        sa.CheckConstraint(
            "status IN ('Open', 'Matched', 'Returned')", name="ck_item_status"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
    )
    op.create_index("ix_item_user_id", "item", ["user_id"], unique=False)

    op.create_table(
        "claim",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("evidence_file_path", sa.String(length=255)),
        sa.Column("evidence_file_type", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Pending"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("claimant_id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('Pending', 'Approved', 'Rejected', 'Returned')",
            name="ck_claim_status",
        ),
        sa.ForeignKeyConstraint(["item_id"], ["item.id"]),
        sa.ForeignKeyConstraint(["claimant_id"], ["user.id"]),
        sa.UniqueConstraint("item_id", "claimant_id", name="uq_claim_item_claimant"),
    )
    op.create_index("ix_claim_item_id", "claim", ["item_id"], unique=False)
    op.create_index("ix_claim_claimant_id", "claim", ["claimant_id"], unique=False)


def downgrade():
    op.drop_index("ix_claim_claimant_id", table_name="claim")
    op.drop_index("ix_claim_item_id", table_name="claim")
    op.drop_table("claim")
    op.drop_index("ix_item_user_id", table_name="item")
    op.drop_table("item")
    op.drop_index("ix_user_email", table_name="user")
    op.drop_table("user")
