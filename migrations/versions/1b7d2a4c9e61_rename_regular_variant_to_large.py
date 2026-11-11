"""rename Regular product variants to Large

Revision ID: 1b7d2a4c9e61
Revises: 649f83ee4aea
Create Date: 2026-11-02

"""
from alembic import op
import sqlalchemy as sa


revision = "1b7d2a4c9e61"
down_revision = "8a41d2c7f6b0"
branch_labels = None
depends_on = None


def rename_variants(old_name, new_name):
    bind = op.get_bind()
    variants = sa.table(
        "product_variant",
        sa.column("id", sa.Integer),
        sa.column("product_id", sa.Integer),
        sa.column("name", sa.String),
    )
    order_items = sa.table("order_item", sa.column("variant_id", sa.Integer))
    rows = bind.execute(
        sa.select(variants.c.id, variants.c.product_id).where(variants.c.name == old_name)
    ).all()
    for variant_id, product_id in rows:
        existing_id = bind.execute(
            sa.select(variants.c.id).where(
                variants.c.product_id == product_id,
                variants.c.name == new_name,
            )
        ).scalar_one_or_none()
        if existing_id is not None:
            bind.execute(
                sa.update(order_items).where(order_items.c.variant_id == variant_id).values(variant_id=existing_id)
            )
            bind.execute(sa.delete(variants).where(variants.c.id == variant_id))
        else:
            bind.execute(
                sa.update(variants).where(variants.c.id == variant_id).values(name=new_name)
            )


def upgrade():
    rename_variants("Regular", "Large")


def downgrade():
    rename_variants("Large", "Regular")
