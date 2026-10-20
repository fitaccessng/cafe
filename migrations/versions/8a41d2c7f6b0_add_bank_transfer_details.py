"""add bank transfer details to business settings

Revision ID: 8a41d2c7f6b0
Revises: 649f83ee4aea
Create Date: 2026-10-20

"""
from alembic import op
import sqlalchemy as sa


revision = "8a41d2c7f6b0"
down_revision = "649f83ee4aea"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("business_settings") as batch_op:
        batch_op.add_column(sa.Column("bank_name", sa.String(length=120), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("bank_account_name", sa.String(length=120), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("bank_account_number", sa.String(length=40), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("bank_branch_code", sa.String(length=20), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("bank_account_type", sa.String(length=40), nullable=False, server_default=""))


def downgrade():
    with op.batch_alter_table("business_settings") as batch_op:
        batch_op.drop_column("bank_account_type")
        batch_op.drop_column("bank_branch_code")
        batch_op.drop_column("bank_account_number")
        batch_op.drop_column("bank_account_name")
        batch_op.drop_column("bank_name")
