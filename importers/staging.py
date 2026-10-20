"""UNLOGGED staging tables, the `COPY` loader and the merge into `foods`.

Shape of one batch:

    TRUNCATE staging  ->  COPY rows in  ->  validate in SQL  ->
    INSERT ... ON CONFLICT (source, source_id) DO UPDATE  ->  commit

Staging is UNLOGGED and carries no indexes: it is written once and read once
per batch, so an index would cost more to maintain than the sequential scan it
saves. The merge relies on indexes that already exist on `foods`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import psycopg
from psycopg import sql

log = logging.getLogger(__name__)

STAGING_FOODS = "staging_off_foods"
STAGING_NUTRIENTS = "staging_off_food_nutrients"

# Every `foods` column an importer writes, in COPY order. `id`, `created_at`
# and the generated `search_vector` are deliberately absent: Postgres owns
# them. `updated_at` is set by the merge, not copied.
FOOD_COLUMNS: tuple[str, ...] = (
    "barcode",
    "name",
    "generic_name",
    "brand",
    "brand_owner",
    "category",
    "food_group",
    "language",
    "countries",
    "quantity_text",
    "product_quantity",
    "product_quantity_unit",
    "serving_size_text",
    "serving_quantity",
    "serving_unit",
    "energy_kcal_100g",
    "energy_kj_100g",
    "protein_100g",
    "carbs_100g",
    "fat_100g",
    "saturated_fat_100g",
    "trans_fat_100g",
    "sugars_100g",
    "fiber_100g",
    "salt_100g",
    "sodium_100g",
    "cholesterol_100g",
    "ingredients_text",
    "allergens_text",
    "traces_text",
    "nutriscore_grade",
    "nutriscore_score",
    "nova_group",
    "additives_count",
    "image_url",
    "image_front_url",
    "image_nutrition_url",
    "image_ingredients_url",
    "source",
    "source_id",
    "source_url",
    "verified",
    "obsolete",
    "source_created_at",
    "source_updated_at",
    "raw_data",
)

# Set on conflict. `source`/`source_id` are the conflict target; `created_at`
# records when *we* first saw the product; `verified` is a human judgement the
# importer must not undo. `updated_at` is set explicitly because SQLAlchemy's
# onupdate never fires for a COPY-based load.
_NEVER_UPDATED = {"source", "source_id", "verified"}
UPDATE_COLUMNS: tuple[str, ...] = tuple(c for c in FOOD_COLUMNS if c not in _NEVER_UPDATED)

NUTRIENT_COLUMNS: tuple[str, ...] = (
    "source_id",
    "nutrient_code",
    "nutrient_name",
    "amount_100g",
    "amount_serving",
    "unit",
)

# Indexes worth dropping before a from-scratch bulk load and rebuilding after:
# maintaining a GIN index row by row across millions of inserts costs far more
# than one build over the finished table. Keyed by index name.
HEAVY_INDEXES: dict[str, str] = {
    "ix_foods_search_vector": (
        "CREATE INDEX ix_foods_search_vector ON foods USING gin (search_vector)"
    ),
    "ix_foods_name_trgm": (
        "CREATE INDEX ix_foods_name_trgm ON foods USING gin (lower(name) gin_trgm_ops)"
    ),
    "ix_foods_countries": (
        "CREATE INDEX ix_foods_countries ON foods USING gin (countries)"
    ),
}


@dataclass(slots=True)
class MergeCounts:
    staged: int = 0
    rejected: int = 0
    inserted: int = 0
    updated: int = 0
    nutrients_upserted: int = 0
    nutrients_removed: int = 0

    def add(self, other: "MergeCounts") -> None:
        self.staged += other.staged
        self.rejected += other.rejected
        self.inserted += other.inserted
        self.updated += other.updated
        self.nutrients_upserted += other.nutrients_upserted
        self.nutrients_removed += other.nutrients_removed


def _columns(names: tuple[str, ...]) -> sql.Composed:
    return sql.SQL(", ").join(sql.Identifier(n) for n in names)


def truncate(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("TRUNCATE {}, {}").format(
                sql.Identifier(STAGING_FOODS), sql.Identifier(STAGING_NUTRIENTS)
            )
        )


def scrub(value: object) -> object:
    if isinstance(value, str):
        return value.replace("\x00", "") if "\x00" in value else value

    if isinstance(value, list):
        return [scrub(item) for item in value]

    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items()}

    return value


def scrub_row(row: tuple) -> tuple:
    return tuple(scrub(value) for value in row)


def copy_foods(conn: psycopg.Connection, rows: list[tuple]) -> int:
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(STAGING_FOODS), _columns(FOOD_COLUMNS)
    )

    with conn.cursor() as cur, cur.copy(statement) as copy:
        for row in rows:
            copy.write_row(scrub_row(row))

    return len(rows)


def copy_nutrients(conn: psycopg.Connection, rows: list[tuple]) -> int:
    if not rows:
        return 0

    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(STAGING_NUTRIENTS), _columns(NUTRIENT_COLUMNS)
    )

    with conn.cursor() as cur, cur.copy(statement) as copy:
        for row in rows:
            copy.write_row(scrub_row(row))

    return len(rows)


def validate(conn: psycopg.Connection) -> int:
    """Drop staged rows that could never become a usable food.

    Mapping already filters these, but the staging table is also the place a
    future importer (or a hand-loaded CSV) lands, so the guard lives in SQL
    where it covers every path into `foods`. Returns the number removed.
    """
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "DELETE FROM {} WHERE name IS NULL OR btrim(name) = '' "
                "OR source_id IS NULL OR btrim(source_id) = ''"
            ).format(sql.Identifier(STAGING_FOODS))
        )
        rejected = cur.rowcount

        # Nutrients whose product just got rejected have nothing to hang off.
        cur.execute(
            sql.SQL(
                "DELETE FROM {n} WHERE source_id NOT IN (SELECT source_id FROM {f})"
            ).format(n=sql.Identifier(STAGING_NUTRIENTS), f=sql.Identifier(STAGING_FOODS))
        )

    return rejected


def merge_foods(conn: psycopg.Connection) -> tuple[int, int]:
    """Merge staging into `foods`. Returns `(inserted, updated)`.

    `DISTINCT ON` is not optional: a single batch can carry the same
    `source_id` twice (the dump is append-ordered, not deduplicated), and
    `ON CONFLICT` raises if one statement touches a row twice. Later wins,
    which `ctid DESC` gives us since COPY appends in batch order.
    """
    statement = sql.SQL(
        """
        WITH deduped AS (
            SELECT DISTINCT ON (source_id) {cols}
            FROM {staging}
            ORDER BY source_id, ctid DESC
        ), merged AS (
            INSERT INTO foods ({cols}, updated_at)
            SELECT {cols}, now() FROM deduped
            ON CONFLICT (source, source_id) DO UPDATE SET
                {assignments},
                updated_at = now()
            RETURNING (xmax = 0) AS inserted
        )
        SELECT count(*) FILTER (WHERE inserted),
               count(*) FILTER (WHERE NOT inserted)
        FROM merged
        """
    ).format(
        cols=_columns(FOOD_COLUMNS),
        staging=sql.Identifier(STAGING_FOODS),
        assignments=sql.SQL(", ").join(
            sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c))
            for c in UPDATE_COLUMNS
        ),
    )

    with conn.cursor() as cur:
        cur.execute(statement)
        inserted, updated = cur.fetchone()

    return inserted, updated


def merge_nutrients(conn: psycopg.Connection, source: str) -> tuple[int, int]:
    """Merge staged micronutrients. Returns `(upserted, removed)`.

    Removal matters for idempotency: if OFF drops a nutrient from a product,
    re-importing must drop our row too, or the food keeps a value its source no
    longer claims. Only products present in this batch are touched.
    """
    upsert = sql.SQL(
        """
        INSERT INTO food_nutrients
            (food_id, nutrient_code, nutrient_name, amount_100g, amount_serving, unit)
        SELECT f.id, d.nutrient_code, d.nutrient_name, d.amount_100g, d.amount_serving, d.unit
        FROM (
            SELECT DISTINCT ON (source_id, nutrient_code) *
            FROM {n} ORDER BY source_id, nutrient_code, ctid DESC
        ) AS d
        JOIN foods f ON f.source = %s AND f.source_id = d.source_id
        ON CONFLICT (food_id, nutrient_code) DO UPDATE SET
            nutrient_name = EXCLUDED.nutrient_name,
            amount_100g = EXCLUDED.amount_100g,
            amount_serving = EXCLUDED.amount_serving,
            unit = EXCLUDED.unit
        """
    ).format(n=sql.Identifier(STAGING_NUTRIENTS))

    prune = sql.SQL(
        """
        DELETE FROM food_nutrients fn
        USING foods f
        WHERE fn.food_id = f.id
          AND f.source = %s
          AND f.source_id IN (SELECT source_id FROM {f})
          AND NOT EXISTS (
              SELECT 1 FROM {n} s
              WHERE s.source_id = f.source_id AND s.nutrient_code = fn.nutrient_code
          )
        """
    ).format(f=sql.Identifier(STAGING_FOODS), n=sql.Identifier(STAGING_NUTRIENTS))

    with conn.cursor() as cur:
        cur.execute(upsert, (source,))
        upserted = cur.rowcount
        cur.execute(prune, (source,))
        removed = cur.rowcount

    return upserted, removed


def merge_batch(
    conn: psycopg.Connection,
    source: str,
    food_rows: list[tuple],
    nutrient_rows: list[tuple],
) -> MergeCounts:
    """One batch, one transaction. A crash loses the batch, never half of it."""
    counts = MergeCounts()

    truncate(conn)
    counts.staged = copy_foods(conn, food_rows)
    copy_nutrients(conn, nutrient_rows)
    counts.rejected = validate(conn)
    counts.inserted, counts.updated = merge_foods(conn)
    counts.nutrients_upserted, counts.nutrients_removed = merge_nutrients(conn, source)

    conn.commit()
    return counts


def drop_heavy_indexes(conn: psycopg.Connection) -> list[str]:
    dropped = []

    with conn.cursor() as cur:
        for name in HEAVY_INDEXES:
            cur.execute(sql.SQL("DROP INDEX IF EXISTS {}").format(sql.Identifier(name)))
            dropped.append(name)

    conn.commit()
    return dropped


def create_heavy_indexes(conn: psycopg.Connection, *, concurrently: bool = False) -> list[str]:
    """Rebuild the indexes `drop_heavy_indexes` removed.

    `concurrently` lets the API keep serving while they build, at the cost of a
    slower build; it cannot run inside a transaction, hence the autocommit.
    """
    created: list[str] = []
    previous = conn.autocommit

    if concurrently:
        conn.commit()
        conn.autocommit = True

    try:
        with conn.cursor() as cur:
            for name, ddl in HEAVY_INDEXES.items():
                cur.execute("SELECT to_regclass(%s)", (name,))
                if cur.fetchone()[0] is not None:
                    log.info("index %s already exists", name)
                    continue

                if concurrently:
                    ddl = ddl.replace("CREATE INDEX ", "CREATE INDEX CONCURRENTLY ", 1)

                log.info("creating %s ...", name)
                cur.execute(ddl)
                created.append(name)

        if not concurrently:
            conn.commit()
    finally:
        conn.autocommit = previous

    return created
