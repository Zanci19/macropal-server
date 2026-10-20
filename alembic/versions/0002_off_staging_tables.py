"""UNLOGGED staging tables for the bulk importers

Revision ID: 0002_off_staging_tables
Revises: 0001_initial_schema
Create Date: 2026-10-20

UNLOGGED means these tables are not written to the WAL. They are truncated at
the start of every batch and their contents are worthless after the merge, so
paying for crash safety on them would be paying for nothing — and the WAL
traffic is most of the cost of a COPY.

No indexes on purpose: each batch writes the table once and reads it once, so
any index would cost more to build than the sequential scan it replaces. The
merge joins against `uq_foods_source_source_id`, which already exists.

Columns mirror `foods`, with one deliberate difference: nothing is NOT NULL.
Staging is where bad rows land so they can be counted and deleted
(`importers.staging.validate`) instead of aborting a 5,000-row COPY.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_off_staging_tables"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STAGING_FOODS = """
CREATE UNLOGGED TABLE staging_off_foods (
    barcode                 VARCHAR(32),
    name                    TEXT,
    generic_name            TEXT,
    brand                   TEXT,
    brand_owner             TEXT,
    category                TEXT,
    food_group              TEXT,
    language                VARCHAR(10),
    countries               TEXT[],
    quantity_text           TEXT,
    product_quantity        NUMERIC,
    product_quantity_unit   VARCHAR(20),
    serving_size_text       TEXT,
    serving_quantity        NUMERIC,
    serving_unit            VARCHAR(20),
    energy_kcal_100g        NUMERIC,
    energy_kj_100g          NUMERIC,
    protein_100g            NUMERIC,
    carbs_100g              NUMERIC,
    fat_100g                NUMERIC,
    saturated_fat_100g      NUMERIC,
    trans_fat_100g          NUMERIC,
    sugars_100g             NUMERIC,
    fiber_100g              NUMERIC,
    salt_100g               NUMERIC,
    sodium_100g             NUMERIC,
    cholesterol_100g        NUMERIC,
    ingredients_text        TEXT,
    allergens_text          TEXT,
    traces_text             TEXT,
    nutriscore_grade        VARCHAR(5),
    nutriscore_score        INTEGER,
    nova_group              SMALLINT,
    additives_count         INTEGER,
    image_url               TEXT,
    image_front_url         TEXT,
    image_nutrition_url     TEXT,
    image_ingredients_url   TEXT,
    source                  VARCHAR(30),
    source_id               TEXT,
    source_url              TEXT,
    verified                BOOLEAN,
    obsolete                BOOLEAN,
    source_created_at       TIMESTAMPTZ,
    source_updated_at       TIMESTAMPTZ,
    raw_data                JSONB
)
"""

STAGING_NUTRIENTS = """
CREATE UNLOGGED TABLE staging_off_food_nutrients (
    source_id       TEXT,
    nutrient_code   VARCHAR(100),
    nutrient_name   VARCHAR(150),
    amount_100g     NUMERIC,
    amount_serving  NUMERIC,
    unit            VARCHAR(20)
)
"""


def upgrade() -> None:
    op.execute(STAGING_FOODS)
    op.execute(STAGING_NUTRIENTS)

    # autovacuum will never see useful statistics on a table that is truncated
    # every few seconds, and the planner only ever has one choice for a
    # 5,000-row seq scan anyway.
    op.execute("ALTER TABLE staging_off_foods SET (autovacuum_enabled = false)")
    op.execute("ALTER TABLE staging_off_food_nutrients SET (autovacuum_enabled = false)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS staging_off_food_nutrients")
    op.execute("DROP TABLE IF EXISTS staging_off_foods")
