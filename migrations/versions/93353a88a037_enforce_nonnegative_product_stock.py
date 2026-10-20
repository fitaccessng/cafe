"""enforce nonnegative product stock

Revision ID: 93353a88a037
Revises: f36639c534b6
Create Date: 2026-10-16 06:41:29.522829

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '93353a88a037'
down_revision = 'f36639c534b6'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    constraints = inspector.get_check_constraints('product')
    if not any(item.get('name') == 'ck_product_stock_nonnegative' for item in constraints):
        with op.batch_alter_table('product', schema=None) as batch_op:
            batch_op.create_check_constraint(
                'ck_product_stock_nonnegative',
                'stock_quantity IS NULL OR stock_quantity >= 0',
            )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    constraints = inspector.get_check_constraints('product')
    if any(item.get('name') == 'ck_product_stock_nonnegative' for item in constraints):
        with op.batch_alter_table('product', schema=None) as batch_op:
            batch_op.drop_constraint('ck_product_stock_nonnegative', type_='check')
