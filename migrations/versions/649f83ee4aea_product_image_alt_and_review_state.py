"""product image alt and review state

Revision ID: 649f83ee4aea
Revises: edc4863b0c0b
Create Date: 2026-10-16 14:09:46.233027

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '649f83ee4aea'
down_revision = 'edc4863b0c0b'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())

    def columns():
        inspector.clear_cache()
        return {column['name']: column for column in inspector.get_columns('product')}

    current = columns()
    if 'image_alt' not in current:
        with op.batch_alter_table('product', schema=None) as batch_op:
            batch_op.add_column(sa.Column('image_alt', sa.String(length=180), nullable=True))
        current = columns()
    if 'image_review_required' not in current:
        with op.batch_alter_table('product', schema=None) as batch_op:
            batch_op.add_column(sa.Column('image_review_required', sa.Boolean(), nullable=True))

    op.execute("UPDATE product SET image_alt = '' WHERE image_alt IS NULL")
    op.execute("UPDATE product SET image_review_required = 0 WHERE image_review_required IS NULL")
    current = columns()
    with op.batch_alter_table('product', schema=None) as batch_op:
        if current['image_alt']['nullable']:
            batch_op.alter_column('image_alt', existing_type=sa.String(length=180), nullable=False, server_default='')
        if current['image_review_required']['nullable']:
            batch_op.alter_column('image_review_required', existing_type=sa.Boolean(), nullable=False, server_default=sa.false())


def downgrade():
    inspector = sa.inspect(op.get_bind())
    existing = {column['name'] for column in inspector.get_columns('product')}
    with op.batch_alter_table('product', schema=None) as batch_op:
        if 'image_review_required' in existing:
            batch_op.drop_column('image_review_required')
        if 'image_alt' in existing:
            batch_op.drop_column('image_alt')
