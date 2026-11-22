"""step photos

Adds `dish_images.step_id` — the column that turns a dish photo into a photo of
one instruction. Nullable, so every existing row stays exactly what it was: a
gallery photo.

ON DELETE SET NULL rather than CASCADE. A deleted step hands its photos back to
the dish gallery instead of destroying them, which is the only version of this
that survives someone rewording a recipe.

`batch_alter_table` because a plain ADD CONSTRAINT is not something SQLite can
do, and local dev runs on SQLite. On Postgres it emits the ordinary DDL.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('dish_images', schema=None) as batch_op:
        batch_op.add_column(sa.Column('step_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_dish_images_step_id',
            'recipe_steps',
            ['step_id'],
            ['id'],
            ondelete='SET NULL',
        )
    op.create_index(
        op.f('ix_dish_images_step_id'), 'dish_images', ['step_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_dish_images_step_id'), table_name='dish_images')
    with op.batch_alter_table('dish_images', schema=None) as batch_op:
        batch_op.drop_constraint('fk_dish_images_step_id', type_='foreignkey')
        batch_op.drop_column('step_id')
