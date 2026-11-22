"""initial schema

Cookit's full schema. The CURRENT_TIMESTAMP server defaults are deliberate:
that spelling is valid on both Postgres (deployed) and SQLite (local dev), which
`now()` is not.

Revision ID: 0001
Revises: 
Create Date: 2026-08-31 18:24:55.012479

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_uuid', sa.String(length=36), nullable=True),
    sa.Column('username', sa.String(length=100), nullable=False),
    sa.Column('display_name', sa.Text(), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_index(op.f('ix_users_user_uuid'), 'users', ['user_uuid'], unique=True)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_table('dishes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dish_uuid', sa.String(length=36), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('name_key', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('cuisine', sa.String(length=80), nullable=True),
    sa.Column('prep_minutes', sa.Integer(), nullable=True),
    sa.Column('cook_minutes', sa.Integer(), nullable=True),
    sa.Column('servings', sa.Integer(), nullable=True),
    sa.Column('difficulty', sa.String(length=20), nullable=False),
    sa.Column('source_url', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_favorite', sa.Boolean(), nullable=False),
    sa.Column('times_cooked', sa.Integer(), nullable=False),
    sa.Column('last_cooked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'name_key', name='uq_dish_per_user')
    )
    op.create_index(op.f('ix_dishes_dish_uuid'), 'dishes', ['dish_uuid'], unique=True)
    op.create_index(op.f('ix_dishes_id'), 'dishes', ['id'], unique=False)
    op.create_index('ix_dishes_user_favorite', 'dishes', ['user_id', 'is_favorite'], unique=False)
    op.create_index(op.f('ix_dishes_user_id'), 'dishes', ['user_id'], unique=False)
    op.create_table('external_identities',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=False),
    sa.Column('subject', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'subject', name='uq_external_identity_provider_subject'),
    sa.UniqueConstraint('provider', 'user_id', name='uq_external_identity_provider_user')
    )
    op.create_table('ingredients',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ingredient_uuid', sa.String(length=36), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('name_key', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=False),
    sa.Column('default_unit', sa.String(length=30), nullable=True),
    sa.Column('emoji', sa.String(length=16), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_staple', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'name_key', name='uq_ingredient_per_user')
    )
    op.create_index(op.f('ix_ingredients_id'), 'ingredients', ['id'], unique=False)
    op.create_index(op.f('ix_ingredients_ingredient_uuid'), 'ingredients', ['ingredient_uuid'], unique=True)
    op.create_index('ix_ingredients_user_category', 'ingredients', ['user_id', 'category'], unique=False)
    op.create_index(op.f('ix_ingredients_user_id'), 'ingredients', ['user_id'], unique=False)
    op.create_table('refresh_tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('token', sa.String(length=500), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_refresh_tokens_id'), 'refresh_tokens', ['id'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_token'), 'refresh_tokens', ['token'], unique=True)
    op.create_table('user_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=True),
    sa.Column('default_servings', sa.Integer(), nullable=True),
    sa.Column('avoid_recent_days', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_index(op.f('ix_user_settings_id'), 'user_settings', ['id'], unique=False)
    op.create_table('cook_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dish_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('cooked_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('meal_type', sa.String(length=20), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['dish_id'], ['dishes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cook_events_dish_id'), 'cook_events', ['dish_id'], unique=False)
    op.create_index(op.f('ix_cook_events_id'), 'cook_events', ['id'], unique=False)
    op.create_index(op.f('ix_cook_events_user_id'), 'cook_events', ['user_id'], unique=False)
    op.create_index('ix_cook_events_user_time', 'cook_events', ['user_id', 'cooked_at'], unique=False)
    op.create_table('dish_images',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('image_uuid', sa.String(length=36), nullable=True),
    sa.Column('dish_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('image_name', sa.Text(), nullable=True),
    sa.Column('mime_type', sa.String(length=100), nullable=True),
    sa.Column('file_size', sa.Integer(), nullable=True),
    sa.Column('file_format', sa.String(length=10), nullable=True),
    sa.Column('caption', sa.Text(), nullable=True),
    sa.Column('minio_object_key', sa.String(length=500), nullable=False),
    sa.Column('minio_bucket', sa.String(length=100), nullable=True),
    sa.Column('is_cover', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['dish_id'], ['dishes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_dish_images_dish_id'), 'dish_images', ['dish_id'], unique=False)
    op.create_index(op.f('ix_dish_images_id'), 'dish_images', ['id'], unique=False)
    op.create_index(op.f('ix_dish_images_image_uuid'), 'dish_images', ['image_uuid'], unique=True)
    op.create_index(op.f('ix_dish_images_user_id'), 'dish_images', ['user_id'], unique=False)
    op.create_table('dish_ingredients',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dish_id', sa.Integer(), nullable=False),
    sa.Column('ingredient_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=True),
    sa.Column('unit', sa.String(length=30), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('is_optional', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['dish_id'], ['dishes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dish_id', 'ingredient_id', name='uq_dish_ingredient')
    )
    op.create_index(op.f('ix_dish_ingredients_dish_id'), 'dish_ingredients', ['dish_id'], unique=False)
    op.create_index('ix_dish_ingredients_ingredient', 'dish_ingredients', ['ingredient_id'], unique=False)
    op.create_table('dish_meal_types',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dish_id', sa.Integer(), nullable=False),
    sa.Column('meal_type', sa.String(length=20), nullable=False),
    sa.ForeignKeyConstraint(['dish_id'], ['dishes.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dish_id', 'meal_type', name='uq_dish_meal_type')
    )
    op.create_index(op.f('ix_dish_meal_types_dish_id'), 'dish_meal_types', ['dish_id'], unique=False)
    op.create_index('ix_dish_meal_types_meal', 'dish_meal_types', ['meal_type'], unique=False)
    op.create_table('dish_pairings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dish_a_id', sa.Integer(), nullable=False),
    sa.Column('dish_b_id', sa.Integer(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.CheckConstraint('dish_a_id < dish_b_id', name='ck_dish_pairing_ordered'),
    sa.ForeignKeyConstraint(['dish_a_id'], ['dishes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['dish_b_id'], ['dishes.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dish_a_id', 'dish_b_id', name='uq_dish_pairing')
    )
    op.create_index('ix_dish_pairings_b', 'dish_pairings', ['dish_b_id'], unique=False)
    op.create_index(op.f('ix_dish_pairings_dish_a_id'), 'dish_pairings', ['dish_a_id'], unique=False)
    op.create_table('recipe_steps',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('step_uuid', sa.String(length=36), nullable=True),
    sa.Column('dish_id', sa.Integer(), nullable=False),
    sa.Column('step_index', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('minutes', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['dish_id'], ['dishes.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dish_id', 'step_index', name='uq_step_index_per_dish')
    )
    op.create_index(op.f('ix_recipe_steps_dish_id'), 'recipe_steps', ['dish_id'], unique=False)
    op.create_index(op.f('ix_recipe_steps_step_uuid'), 'recipe_steps', ['step_uuid'], unique=True)
    op.create_table('recipe_step_ingredients',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('step_id', sa.Integer(), nullable=False),
    sa.Column('ingredient_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['step_id'], ['recipe_steps.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('step_id', 'ingredient_id', name='uq_step_ingredient')
    )
    op.create_index(op.f('ix_recipe_step_ingredients_step_id'), 'recipe_step_ingredients', ['step_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_recipe_step_ingredients_step_id'), table_name='recipe_step_ingredients')
    op.drop_table('recipe_step_ingredients')
    op.drop_index(op.f('ix_recipe_steps_step_uuid'), table_name='recipe_steps')
    op.drop_index(op.f('ix_recipe_steps_dish_id'), table_name='recipe_steps')
    op.drop_table('recipe_steps')
    op.drop_index(op.f('ix_dish_pairings_dish_a_id'), table_name='dish_pairings')
    op.drop_index('ix_dish_pairings_b', table_name='dish_pairings')
    op.drop_table('dish_pairings')
    op.drop_index('ix_dish_meal_types_meal', table_name='dish_meal_types')
    op.drop_index(op.f('ix_dish_meal_types_dish_id'), table_name='dish_meal_types')
    op.drop_table('dish_meal_types')
    op.drop_index('ix_dish_ingredients_ingredient', table_name='dish_ingredients')
    op.drop_index(op.f('ix_dish_ingredients_dish_id'), table_name='dish_ingredients')
    op.drop_table('dish_ingredients')
    op.drop_index(op.f('ix_dish_images_user_id'), table_name='dish_images')
    op.drop_index(op.f('ix_dish_images_image_uuid'), table_name='dish_images')
    op.drop_index(op.f('ix_dish_images_id'), table_name='dish_images')
    op.drop_index(op.f('ix_dish_images_dish_id'), table_name='dish_images')
    op.drop_table('dish_images')
    op.drop_index('ix_cook_events_user_time', table_name='cook_events')
    op.drop_index(op.f('ix_cook_events_user_id'), table_name='cook_events')
    op.drop_index(op.f('ix_cook_events_id'), table_name='cook_events')
    op.drop_index(op.f('ix_cook_events_dish_id'), table_name='cook_events')
    op.drop_table('cook_events')
    op.drop_index(op.f('ix_user_settings_id'), table_name='user_settings')
    op.drop_table('user_settings')
    op.drop_index(op.f('ix_refresh_tokens_token'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_id'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index(op.f('ix_ingredients_user_id'), table_name='ingredients')
    op.drop_index('ix_ingredients_user_category', table_name='ingredients')
    op.drop_index(op.f('ix_ingredients_ingredient_uuid'), table_name='ingredients')
    op.drop_index(op.f('ix_ingredients_id'), table_name='ingredients')
    op.drop_table('ingredients')
    op.drop_table('external_identities')
    op.drop_index(op.f('ix_dishes_user_id'), table_name='dishes')
    op.drop_index('ix_dishes_user_favorite', table_name='dishes')
    op.drop_index(op.f('ix_dishes_id'), table_name='dishes')
    op.drop_index(op.f('ix_dishes_dish_uuid'), table_name='dishes')
    op.drop_table('dishes')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_index(op.f('ix_users_user_uuid'), table_name='users')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_table('users')
