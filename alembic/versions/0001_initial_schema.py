"""initial schema: foods + food_nutrients

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-20

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEARCH_VECTOR_SQL = (
    "to_tsvector('simple', "
    "coalesce(name, '') || ' ' || "
    "coalesce(generic_name, '') || ' ' || "
    "coalesce(brand, '') || ' ' || "
    "coalesce(category, ''))"
)

NUMERIC = sa.Numeric()


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "foods",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("barcode", sa.String(length=32), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("generic_name", sa.Text(), nullable=True),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("brand_owner", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("food_group", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=10), nullable=True),
        sa.Column("countries", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("quantity_text", sa.Text(), nullable=True),
        sa.Column("product_quantity", NUMERIC, nullable=True),
        sa.Column("product_quantity_unit", sa.String(length=20), nullable=True),
        sa.Column("serving_size_text", sa.Text(), nullable=True),
        sa.Column("serving_quantity", NUMERIC, nullable=True),
        sa.Column("serving_unit", sa.String(length=20), nullable=True),
        sa.Column("energy_kcal_100g", NUMERIC, nullable=True),
        sa.Column("energy_kj_100g", NUMERIC, nullable=True),
        sa.Column("protein_100g", NUMERIC, nullable=True),
        sa.Column("carbs_100g", NUMERIC, nullable=True),
        sa.Column("fat_100g", NUMERIC, nullable=True),
        sa.Column("saturated_fat_100g", NUMERIC, nullable=True),
        sa.Column("trans_fat_100g", NUMERIC, nullable=True),
        sa.Column("sugars_100g", NUMERIC, nullable=True),
        sa.Column("fiber_100g", NUMERIC, nullable=True),
        sa.Column("salt_100g", NUMERIC, nullable=True),
        sa.Column("sodium_100g", NUMERIC, nullable=True),
        sa.Column("cholesterol_100g", NUMERIC, nullable=True),
        sa.Column("ingredients_text", sa.Text(), nullable=True),
        sa.Column("allergens_text", sa.Text(), nullable=True),
        sa.Column("traces_text", sa.Text(), nullable=True),
        sa.Column("nutriscore_grade", sa.String(length=5), nullable=True),
        sa.Column("nutriscore_score", sa.Integer(), nullable=True),
        sa.Column("nova_group", sa.SmallInteger(), nullable=True),
        sa.Column("additives_count", sa.Integer(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("image_front_url", sa.Text(), nullable=True),
        sa.Column("image_nutrition_url", sa.Text(), nullable=True),
        sa.Column("image_ingredients_url", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("obsolete", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("raw_data", postgresql.JSONB(), nullable=True),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR_SQL, persisted=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_foods"),
        sa.UniqueConstraint("source", "source_id", name="uq_foods_source_source_id"),
    )

    op.create_index("ix_foods_barcode", "foods", ["barcode"])
    op.create_index("ix_foods_source", "foods", ["source"])
    op.create_index(
        "ix_foods_search_vector", "foods", ["search_vector"], postgresql_using="gin"
    )
    op.create_index(
        "ix_foods_countries", "foods", ["countries"], postgresql_using="gin"
    )
    op.execute(
        "CREATE INDEX ix_foods_name_trgm ON foods "
        "USING gin (lower(name) gin_trgm_ops)"
    )

    op.create_table(
        "food_nutrients",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("food_id", sa.BigInteger(), nullable=False),
        sa.Column("nutrient_code", sa.String(length=100), nullable=False),
        sa.Column("nutrient_name", sa.String(length=150), nullable=True),
        sa.Column("amount_100g", NUMERIC, nullable=True),
        sa.Column("amount_serving", NUMERIC, nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_food_nutrients"),
        sa.ForeignKeyConstraint(
            ["food_id"],
            ["foods.id"],
            name="fk_food_nutrients_food_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "food_id", "nutrient_code", name="uq_food_nutrients_food_code"
        ),
    )

    op.create_index("ix_food_nutrients_code", "food_nutrients", ["nutrient_code"])
    op.create_index("ix_food_nutrients_food_id", "food_nutrients", ["food_id"])


def downgrade() -> None:
    op.drop_table("food_nutrients")
    op.execute("DROP INDEX IF EXISTS ix_foods_name_trgm")
    op.drop_table("foods")
