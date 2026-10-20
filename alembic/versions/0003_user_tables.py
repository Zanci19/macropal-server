"""users, goals, custom_foods, meals, diary_entries, weights, favorites

Revision ID: 0003_user_tables
Revises: 0002_off_staging_tables
Create Date: 2026-10-20

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_user_tables"
down_revision: str | None = "0002_off_staging_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NUMERIC = sa.Numeric()

SEX = "sex IN ('male', 'female', 'other', 'unspecified')"
ACTIVITY = (
    "activity_level IN ('sedentary', 'light', 'moderate', 'active', 'very_active')"
)
GOAL = "goal IN ('lose_weight', 'maintain', 'gain_weight', 'gain_muscle')"
UNIT_SYSTEM = "unit_system IN ('metric', 'imperial')"
MEAL = "meal IN ('breakfast', 'lunch', 'dinner', 'snacks')"
ONE_FOOD_REFERENCE = "(food_id IS NOT NULL) <> (custom_food_id IS NOT NULL)"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("firebase_uid", sa.String(length=128), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("sex", sa.String(length=20), nullable=True),
        sa.Column("height_cm", sa.Numeric(5, 2), nullable=True),
        sa.Column("activity_level", sa.String(length=30), nullable=True),
        sa.Column("goal", sa.String(length=30), nullable=True),
        sa.Column("calorie_target", sa.Integer(), nullable=True),
        sa.Column("protein_target", NUMERIC, nullable=True),
        sa.Column("carbs_target", NUMERIC, nullable=True),
        sa.Column("fat_target", NUMERIC, nullable=True),
        sa.Column(
            "unit_system",
            sa.String(length=10),
            server_default="metric",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("firebase_uid", name="uq_users_firebase_uid"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.CheckConstraint(f"sex IS NULL OR {SEX}", name="ck_users_sex"),
        sa.CheckConstraint(
            f"activity_level IS NULL OR {ACTIVITY}", name="ck_users_activity_level"
        ),
        sa.CheckConstraint(f"goal IS NULL OR {GOAL}", name="ck_users_goal"),
        sa.CheckConstraint(UNIT_SYSTEM, name="ck_users_unit_system"),
        sa.CheckConstraint(
            "height_cm IS NULL OR (height_cm > 0 AND height_cm < 300)",
            name="ck_users_height_cm",
        ),
        sa.CheckConstraint(
            "calorie_target IS NULL OR calorie_target > 0",
            name="ck_users_calorie_target",
        ),
    )

    op.create_table(
        "goals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("goal", sa.String(length=30), nullable=True),
        sa.Column("calorie_target", sa.Integer(), nullable=True),
        sa.Column("protein_target", NUMERIC, nullable=True),
        sa.Column("carbs_target", NUMERIC, nullable=True),
        sa.Column("fat_target", NUMERIC, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_goals"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_goals_user_id", ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "user_id", "effective_from", name="uq_goals_user_effective_from"
        ),
        sa.CheckConstraint(f"goal IS NULL OR {GOAL}", name="ck_goals_goal"),
    )
    op.create_index("ix_goals_user_effective_from", "goals", ["user_id", "effective_from"])

    op.create_table(
        "custom_foods",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("barcode", sa.String(length=32), nullable=True),
        sa.Column("serving_size_text", sa.Text(), nullable=True),
        sa.Column("serving_quantity", NUMERIC, nullable=True),
        sa.Column("serving_unit", sa.String(length=20), nullable=True),
        sa.Column("energy_kcal_100g", NUMERIC, nullable=True),
        sa.Column("protein_100g", NUMERIC, nullable=True),
        sa.Column("carbs_100g", NUMERIC, nullable=True),
        sa.Column("fat_100g", NUMERIC, nullable=True),
        sa.Column("saturated_fat_100g", NUMERIC, nullable=True),
        sa.Column("sugars_100g", NUMERIC, nullable=True),
        sa.Column("fiber_100g", NUMERIC, nullable=True),
        sa.Column("salt_100g", NUMERIC, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_custom_foods"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_custom_foods_user_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_custom_foods_user_id", "custom_foods", ["user_id"])
    op.create_index("ix_custom_foods_user_name", "custom_foods", ["user_id", "name"])

    op.create_table(
        "meals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_meals"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_meals_user_id", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("user_id", "name", name="uq_meals_user_name"),
    )
    op.create_index("ix_meals_user_id", "meals", ["user_id"])

    op.create_table(
        "meal_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("meal_id", sa.BigInteger(), nullable=False),
        sa.Column("food_id", sa.BigInteger(), nullable=True),
        sa.Column("custom_food_id", sa.BigInteger(), nullable=True),
        sa.Column("quantity_g", NUMERIC, nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_meal_items"),
        sa.ForeignKeyConstraint(
            ["meal_id"], ["meals.id"], name="fk_meal_items_meal_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["food_id"], ["foods.id"], name="fk_meal_items_food_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["custom_food_id"],
            ["custom_foods.id"],
            name="fk_meal_items_custom_food_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(ONE_FOOD_REFERENCE, name="ck_meal_items_one_food_reference"),
        sa.CheckConstraint("quantity_g > 0", name="ck_meal_items_quantity_g"),
    )
    op.create_index("ix_meal_items_meal_id", "meal_items", ["meal_id"])

    op.create_table(
        "diary_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("food_id", sa.BigInteger(), nullable=True),
        sa.Column("custom_food_id", sa.BigInteger(), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("meal", sa.String(length=20), nullable=False),
        sa.Column("quantity_g", NUMERIC, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_diary_entries"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_diary_entries_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["food_id"],
            ["foods.id"],
            name="fk_diary_entries_food_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["custom_food_id"],
            ["custom_foods.id"],
            name="fk_diary_entries_custom_food_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            ONE_FOOD_REFERENCE, name="ck_diary_entries_one_food_reference"
        ),
        sa.CheckConstraint("quantity_g > 0", name="ck_diary_entries_quantity_g"),
        sa.CheckConstraint(MEAL, name="ck_diary_entries_meal"),
    )
    op.create_index("ix_diary_entries_user_date", "diary_entries", ["user_id", "date"])

    op.create_table(
        "weights",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("weight_kg", sa.Numeric(6, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_weights"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_weights_user_id", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("user_id", "date", name="uq_weights_user_date"),
        sa.CheckConstraint(
            "weight_kg > 0 AND weight_kg < 1000", name="ck_weights_weight_kg"
        ),
    )
    op.create_index("ix_weights_user_date", "weights", ["user_id", "date"])

    op.create_table(
        "favorites",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("food_id", sa.BigInteger(), nullable=True),
        sa.Column("custom_food_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_favorites"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_favorites_user_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["food_id"], ["foods.id"], name="fk_favorites_food_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["custom_food_id"],
            ["custom_foods.id"],
            name="fk_favorites_custom_food_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(ONE_FOOD_REFERENCE, name="ck_favorites_one_food_reference"),
        sa.UniqueConstraint("user_id", "food_id", name="uq_favorites_user_food"),
        sa.UniqueConstraint(
            "user_id", "custom_food_id", name="uq_favorites_user_custom_food"
        ),
    )
    op.create_index("ix_favorites_user_id", "favorites", ["user_id"])


def downgrade() -> None:
    op.drop_table("favorites")
    op.drop_table("weights")
    op.drop_table("diary_entries")
    op.drop_table("meal_items")
    op.drop_table("meals")
    op.drop_table("custom_foods")
    op.drop_table("goals")
    op.drop_table("users")
