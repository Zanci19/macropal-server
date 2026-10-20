"""OpenFoodFacts importer: download, stream, normalize, COPY, merge.

    python -m importers.openfoodfacts download
    python -m importers.openfoodfacts load --limit 5000
    python -m importers.openfoodfacts load
    python -m importers.openfoodfacts indexes --drop | --create

The dump is a gzipped JSONL export, one product per line, ~13 GB compressed.
Nothing is ever read into memory whole: the file is streamed line by line, and
products are mapped and flushed in batches.

Why JSONL and not the CSV export: the CSV flattens nutriments to a fixed set of
columns, and micronutrients beyond that set are simply gone. `food_nutrients`
exists precisely to hold those, so the importer reads the JSONL, where
`nutriments` is a dict containing everything the product has.

Re-running is safe. Identity is `(source, source_id)` = `('openfoodfacts', code)`,
the merge is `ON CONFLICT ... DO UPDATE`, and a checkpoint file lets an
interrupted run continue at the line it reached.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator

from psycopg.types.json import Jsonb

from importers import staging
from importers.download import download, human, sha256_file

log = logging.getLogger("importers.openfoodfacts")

SOURCE = "openfoodfacts"

DUMP_URL = "https://static.openfoodfacts.org/data/openfoodfacts-products.jsonl.gz"
PRODUCT_URL_BASE = "https://world.openfoodfacts.org/product"
IMAGE_URL_BASE = "https://images.openfoodfacts.org/images/products"

# Repo-root/data, gitignored. Override with --data-dir or OFF_DATA_DIR.
DEFAULT_DATA_DIR = Path(os.environ.get("OFF_DATA_DIR") or (Path(__file__).resolve().parent.parent / "data"))

DEFAULT_BATCH_SIZE = 5_000

# Nutriment bases that already have their own `foods` column, so they must not
# be duplicated into `food_nutrients`.
COLUMN_NUTRIENTS = frozenset(
    {
        "energy",
        "energy-kcal",
        "energy-kj",
        "energy-from-fat",
        "proteins",
        "carbohydrates",
        "fat",
        "saturated-fat",
        "trans-fat",
        "sugars",
        "fiber",
        "salt",
        "sodium",
        "cholesterol",
    }
)

# OFF's own scoring scratch space, not nutrition. Keeping these out of
# `food_nutrients` is what stops the table filling up with derived noise.
INTERNAL_NUTRIENTS = frozenset(
    {
        "nova-group",
        "nutrition-score-fr",
        "nutrition-score-uk",
        "carbon-footprint",
        "carbon-footprint-from-meat-or-fish",
        "fruits-vegetables-nuts",
        "fruits-vegetables-nuts-dried",
        "fruits-vegetables-legumes",
        "collagen-meat-protein-ratio",
    }
)

# OFF reports `<nutrient>_100g` normalized to grams whatever `_unit` says
# (`vitamin-a_unit` is often "µg" while `vitamin-a_100g` is in g). Storing the
# display unit next to a gram value would misstate the number, so a mass unit
# is recorded as the gram value it actually is.
MASS_UNITS = frozenset({"g", "mg", "µg", "μg", "mcg", "ug", "kg"})

KJ_PER_KCAL = Decimal("4.184")

VALID_NUTRISCORE = frozenset("abcde")

# Placeholders contributors and import scripts leave behind. They are real
# strings in the dump — `categories_tags: ["en:null"]` is common — and storing
# them would put "null" in front of users as a category.
JUNK_LABELS = frozenset({"null", "none", "nan", "n/a", "na", "unknown", "-", "--", "?"})


# --------------------------------------------------------------------------
# small coercions
# --------------------------------------------------------------------------


def num(value: Any) -> Decimal | None:
    """Anything OFF might put in a numeric field -> Decimal, or None.

    The dump is crowd-sourced: the same field arrives as 350, 350.0, "350" or
    "" depending on who typed it and when.
    """
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, Decimal):
        return value if value.is_finite() else None

    if isinstance(value, (int, float)):
        try:
            result = Decimal(str(value))
        except InvalidOperation:
            return None
        return result if result.is_finite() else None

    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not text:
            return None
        try:
            result = Decimal(text)
        except InvalidOperation:
            return None
        return result if result.is_finite() else None

    return None


def non_negative(value: Decimal | None) -> Decimal | None:
    """A negative mass per 100 g is a data-entry error, not a measurement."""
    return None if value is None or value < 0 else value


def text(value: Any, limit: int | None = None) -> str | None:
    if not isinstance(value, str):
        return None

    cleaned = " ".join(value.split())
    if not cleaned:
        return None

    return cleaned[:limit] if limit else cleaned


def label(value: str | None) -> str | None:
    """A human-facing label, or None if it is one of OFF's placeholders."""
    if value is None:
        return None

    return None if value.strip().lower() in JUNK_LABELS else value


def deslug(tag: str) -> str:
    """`en:cocoa-and-hazelnuts-spreads` -> `cocoa and hazelnuts spreads`."""
    _, _, rest = tag.partition(":")
    return (rest or tag).replace("-", " ").strip().lower()


def timestamp(value: Any) -> datetime | None:
    """OFF's unix seconds -> an aware UTC datetime.

    The value arrives as an int or as a string of digits depending on the row's
    age. Zero and far-future values litter old rows, so both ends are bounded.
    """
    parsed = num(value)
    if parsed is None:
        return None

    seconds = int(parsed)
    if not 0 < seconds < 4_102_444_800:  # 1970 .. 2100
        return None

    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def first_text(product: dict, *keys: str) -> str | None:
    for key in keys:
        value = label(text(product.get(key)))
        if value:
            return value
    return None


# --------------------------------------------------------------------------
# field mapping
# --------------------------------------------------------------------------


def pick_name(product: dict) -> str | None:
    """The product's name in the most useful language available.

    `product_name` is whatever the contributor typed in the product's own
    language; the `_xx` variants are the translations. English first when the
    base field is empty, then the product's own language, then anything.
    """
    language = text(product.get("lang")) or text(product.get("lc"))
    candidates = ["product_name", "product_name_en"]

    if language:
        candidates.append(f"product_name_{language}")

    candidates.append("abbreviated_product_name")

    name = first_text(product, *candidates)
    if name:
        return name

    for key, value in product.items():
        if key.startswith("product_name_"):
            found = label(text(value))
            if found:
                return found

    return None


def localized(product: dict, base: str) -> str | None:
    language = text(product.get("lang")) or text(product.get("lc"))
    keys = [base, f"{base}_en"]

    if language:
        keys.insert(1, f"{base}_{language}")

    return first_text(product, *keys)


def tag_text(product: dict, plain: str, tags: str) -> str | None:
    """`allergens` if the contributor wrote one, else the taxonomy tags."""
    value = text(product.get(plain))
    if value:
        return value

    entries = product.get(tags)
    if isinstance(entries, list) and entries:
        return ", ".join(deslug(t) for t in entries if isinstance(t, str)) or None

    return None


def countries(product: dict) -> list[str] | None:
    """`countries_tags` -> lowercase English names, no `en:` prefix.

    `['en:france', 'en:united-states']` -> `['france', 'united states']`,
    which is what `GET /v1/foods/search?country=` matches against.
    """
    tags = product.get("countries_tags")
    if not isinstance(tags, list):
        return None

    names: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        name = deslug(tag)
        if name and name not in names:
            names.append(name)

    return names or None


def category(product: dict) -> str | None:
    """The most specific English category OFF assigned.

    `categories_tags` is ordered general -> specific, so the last `en:` entry
    is the useful one. The free-text `categories` field is the fallback: it is
    often empty, and when it is not it is a comma-separated list in the
    contributor's language.
    """
    tags = product.get("categories_tags")

    if isinstance(tags, list):
        english = [t for t in tags if isinstance(t, str) and t.startswith("en:")]
        for tag in reversed(english or [t for t in tags if isinstance(t, str)]):
            name = label(deslug(tag))
            if name:
                return name[:500]

    raw = text(product.get("categories"))
    if raw:
        return label(raw.split(",")[0].strip()[:500])

    return None


def food_group(product: dict) -> str | None:
    value = product.get("food_groups")

    if isinstance(value, str) and value.strip():
        return label(deslug(value)[:200])

    tags = product.get("food_groups_tags")
    if isinstance(tags, list) and tags and isinstance(tags[-1], str):
        return label(deslug(tags[-1])[:200])

    return None


def brand(product: dict) -> str | None:
    """The first brand. `brands` is a comma-separated list more often than not."""
    raw = text(product.get("brands"))
    if raw:
        return label(raw.split(",")[0].strip())

    tags = product.get("brands_tags")
    if isinstance(tags, list) and tags and isinstance(tags[0], str):
        return label(deslug(tags[0]))

    return None


def code_path(code: str) -> str:
    """OFF's on-disk image directory for a barcode.

    Codes of nine characters or more are split 3/3/3/rest — `0000101209159`
    becomes `000/010/120/9159`. Shorter codes are used as-is. This mirrors
    OFF's own splitter exactly, including the empty fourth group a nine-digit
    code produces, because the paths already exist on their server.
    """
    if len(code) >= 9:
        return f"{code[0:3]}/{code[3:6]}/{code[6:9]}/{code[9:]}"

    return code


def _selected_images(product: dict) -> dict[str, dict]:
    """`{'front': {...}, 'nutrition': {...}, 'ingredients': {...}}` per language.

    Two layouts are in the wild: the current `images.selected.front.fr` and the
    older flat `images.front_fr`. Both appear in dumps of different ages.
    """
    images = product.get("images")
    if not isinstance(images, dict):
        return {}

    selected = images.get("selected")
    if isinstance(selected, dict):
        return {k: v for k, v in selected.items() if isinstance(v, dict)}

    flat: dict[str, dict] = {}
    for key, value in images.items():
        if not isinstance(value, dict):
            continue
        kind, _, language = key.partition("_")
        if language and kind in ("front", "nutrition", "ingredients", "packaging"):
            flat.setdefault(kind, {})[language] = value

    return flat


def image_urls(product: dict, code: str) -> dict[str, str | None]:
    selected = _selected_images(product)
    language = text(product.get("lang")) or text(product.get("lc")) or "en"
    path = code_path(code)
    urls: dict[str, str | None] = {}

    for kind in ("front", "nutrition", "ingredients"):
        by_language = selected.get(kind) or {}
        entry = None
        chosen = None

        for candidate in (language, "en", *by_language.keys()):
            value = by_language.get(candidate)
            if isinstance(value, dict) and value.get("rev"):
                entry, chosen = value, candidate
                break

        if entry is None:
            urls[kind] = None
            continue

        urls[kind] = f"{IMAGE_URL_BASE}/{path}/{kind}_{chosen}.{entry['rev']}.400.jpg"

    return urls


def energy(nutriments: dict) -> tuple[Decimal | None, Decimal | None]:
    """`(kcal per 100 g, kJ per 100 g)`.

    OFF's plain `energy_100g` is always kJ regardless of what `energy_unit`
    says — that field records the unit the contributor typed in, not the unit
    of the stored value. Whichever of the two is missing is derived from the
    other, because the app shows kcal and plenty of European products only
    carry kJ.
    """
    kcal = non_negative(num(nutriments.get("energy-kcal_100g")))
    kj = non_negative(num(nutriments.get("energy-kj_100g")))

    if kj is None:
        kj = non_negative(num(nutriments.get("energy_100g")))

    if kcal is None and kj is not None:
        kcal = (kj / KJ_PER_KCAL).quantize(Decimal("0.01"))
    elif kj is None and kcal is not None:
        kj = (kcal * KJ_PER_KCAL).quantize(Decimal("0.01"))

    return kcal, kj


def nutriscore(product: dict) -> tuple[str | None, int | None]:
    """Only a real a-e grade. OFF also emits `unknown` and `not-applicable`,
    which are 7 and 14 characters against a `VARCHAR(5)` column."""
    grade = text(product.get("nutriscore_grade")) or text(product.get("nutrition_grades"))
    grade = grade.lower() if grade else None

    if grade not in VALID_NUTRISCORE:
        grade = None

    score = num(product.get("nutriscore_score"))
    if score is None:
        score = num((product.get("nutriments") or {}).get("nutrition-score-fr_100g"))

    return grade, (int(score) if score is not None else None)


def micronutrients(nutriments: dict) -> list[dict]:
    """Nutriments with no `foods` column of their own, for `food_nutrients`.

    Driven off the `_100g` keys: those are the ones comparable across products.
    `_prepared` variants (as-reconstituted values for powders and concentrates)
    are skipped — mixing them with as-sold values in one column would be
    meaningless.
    """
    rows: list[dict] = []

    for key, value in nutriments.items():
        if not key.endswith("_100g"):
            continue

        base = key[: -len("_100g")]

        if (
            base in COLUMN_NUTRIENTS
            or base in INTERNAL_NUTRIENTS
            or "_prepared" in base
            or base.endswith("-estimate-from-ingredients")
            or len(base) > 100
        ):
            continue

        amount = non_negative(num(value))
        if amount is None:
            continue

        unit = text(nutriments.get(f"{base}_unit"), 20)
        if unit is None or unit.lower() in MASS_UNITS:
            unit = "g"

        rows.append(
            {
                "nutrient_code": base,
                "nutrient_name": deslug(base)[:150],
                "amount_100g": amount,
                "amount_serving": non_negative(num(nutriments.get(f"{base}_serving"))),
                "unit": unit,
            }
        )

    return rows


@dataclass(slots=True)
class MappedProduct:
    food: dict
    nutrients: list[dict]


def map_product(product: dict, *, keep_raw: bool = False) -> MappedProduct | None:
    """One OFF product -> one `foods` row plus its `food_nutrients` rows.

    Returns None for anything that could not become a usable food: no barcode,
    no name in any language, or a non-food product type (the world export
    occasionally carries beauty and pet-food rows).
    """
    code = text(product.get("code")) or text(product.get("_id"))
    if not code:
        return None

    product_type = text(product.get("product_type"))
    if product_type and product_type != "food":
        return None

    name = pick_name(product)
    if not name:
        return None

    nutriments = product.get("nutriments")
    if not isinstance(nutriments, dict):
        nutriments = {}

    kcal, kj = energy(nutriments)
    grade, score = nutriscore(product)
    images = image_urls(product, code)
    nova = num(product.get("nova_group"))
    additives = num(product.get("additives_n"))

    def per_100g(key: str) -> Decimal | None:
        return non_negative(num(nutriments.get(f"{key}_100g")))

    food = {
        "barcode": code[:32],
        "name": name,
        "generic_name": localized(product, "generic_name"),
        "brand": brand(product),
        "brand_owner": first_text(product, "brand_owner", "owner"),
        "category": category(product),
        "food_group": food_group(product),
        "language": text(product.get("lang"), 10) or text(product.get("lc"), 10),
        "countries": countries(product),
        "quantity_text": text(product.get("quantity")),
        "product_quantity": non_negative(num(product.get("product_quantity"))),
        "product_quantity_unit": text(product.get("product_quantity_unit"), 20),
        "serving_size_text": text(product.get("serving_size")),
        "serving_quantity": non_negative(num(product.get("serving_quantity"))),
        "serving_unit": text(product.get("serving_quantity_unit"), 20),
        "energy_kcal_100g": kcal,
        "energy_kj_100g": kj,
        "protein_100g": per_100g("proteins"),
        "carbs_100g": per_100g("carbohydrates"),
        "fat_100g": per_100g("fat"),
        "saturated_fat_100g": per_100g("saturated-fat"),
        "trans_fat_100g": per_100g("trans-fat"),
        "sugars_100g": per_100g("sugars"),
        "fiber_100g": per_100g("fiber"),
        "salt_100g": per_100g("salt"),
        "sodium_100g": per_100g("sodium"),
        "cholesterol_100g": per_100g("cholesterol"),
        "ingredients_text": localized(product, "ingredients_text"),
        "allergens_text": tag_text(product, "allergens", "allergens_tags"),
        "traces_text": tag_text(product, "traces", "traces_tags"),
        "nutriscore_grade": grade,
        "nutriscore_score": score,
        "nova_group": int(nova) if nova is not None and 1 <= nova <= 4 else None,
        "additives_count": int(additives) if additives is not None and additives >= 0 else None,
        "image_url": images["front"],
        "image_front_url": images["front"],
        "image_nutrition_url": images["nutrition"],
        "image_ingredients_url": images["ingredients"],
        "source": SOURCE,
        "source_id": code,
        "source_url": f"{PRODUCT_URL_BASE}/{code}",
        # OFF is crowd-sourced; nothing here has been checked by us.
        "verified": False,
        "obsolete": bool(product.get("obsolete")),
        "source_created_at": timestamp(product.get("created_t")),
        "source_updated_at": timestamp(product.get("last_modified_t")),
        "raw_data": product if keep_raw else None,
    }

    return MappedProduct(food=food, nutrients=micronutrients(nutriments))


# --------------------------------------------------------------------------
# COPY row construction
# --------------------------------------------------------------------------


def food_row(food: dict) -> tuple:
    """A mapped food as a tuple in `staging.FOOD_COLUMNS` order.

    Everything else adapts straight through: Decimal -> numeric, aware
    datetime -> timestamptz, list[str] -> text[].
    """
    return tuple(
        Jsonb(food[column])
        if column == "raw_data" and food[column] is not None
        else food[column]
        for column in staging.FOOD_COLUMNS
    )


def nutrient_rows(source_id: str, nutrients: list[dict]) -> list[tuple]:
    return [
        (
            source_id,
            n["nutrient_code"],
            n["nutrient_name"],
            n["amount_100g"],
            n["amount_serving"],
            n["unit"],
        )
        for n in nutrients
    ]


# --------------------------------------------------------------------------
# streaming
# --------------------------------------------------------------------------


@dataclass
class Stats:
    lines: int = 0
    mapped: int = 0
    skipped_no_name: int = 0
    skipped_no_code: int = 0
    skipped_not_food: int = 0
    bad_json: int = 0
    merge: staging.MergeCounts = field(default_factory=staging.MergeCounts)

    def summary(self) -> str:
        m = self.merge
        return (
            f"lines={self.lines:,} mapped={self.mapped:,} "
            f"inserted={m.inserted:,} updated={m.updated:,} "
            f"rejected_in_sql={m.rejected:,} "
            f"nutrients={m.nutrients_upserted:,} (pruned {m.nutrients_removed:,}) "
            f"skipped: no_name={self.skipped_no_name:,} "
            f"no_code={self.skipped_no_code:,} not_food={self.skipped_not_food:,} "
            f"bad_json={self.bad_json:,}"
        )


def open_dump(path: Path):
    """Line iterator over a `.jsonl.gz` or plain `.jsonl` dump.

    Nothing is buffered beyond one line: the 13 GB file never has to fit in
    memory, and neither does any part of it.
    """
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")

    return path.open("rt", encoding="utf-8", errors="replace")


def iter_products(path: Path, *, skip: int = 0, stats: Stats) -> Iterator[dict]:
    """Yield parsed products, counting what could not be parsed.

    `parse_float=Decimal` keeps the exact decimal the dump wrote: the target
    columns are NUMERIC, and routing 0.1 through a binary float first would
    store 0.1000000000000000055 for no reason.
    """
    with open_dump(path) as handle:
        for index, line in enumerate(handle):
            if index < skip:
                continue

            stats.lines += 1
            line = line.strip()

            if not line:
                continue

            try:
                yield json.loads(line, parse_float=Decimal)
            except json.JSONDecodeError:
                stats.bad_json += 1


# --------------------------------------------------------------------------
# checkpointing
# --------------------------------------------------------------------------


@dataclass
class Checkpoint:
    path: Path
    dump_size: int
    dump_mtime: int
    lines_done: int = 0

    @classmethod
    def for_dump(cls, dump: Path) -> "Checkpoint":
        info = dump.stat()
        return cls(
            path=dump.with_suffix(dump.suffix + ".import-state.json"),
            dump_size=info.st_size,
            dump_mtime=int(info.st_mtime),
        )

    def load(self) -> int:
        """Lines already imported from *this* dump file, else 0.

        A different size or mtime means the dump was re-downloaded, so the old
        line count points at a different product and must be discarded.
        """
        if not self.path.exists():
            return 0

        try:
            saved = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            log.warning("unreadable checkpoint %s, starting from the top", self.path)
            return 0

        if saved.get("dump_size") != self.dump_size or saved.get("dump_mtime") != self.dump_mtime:
            log.warning("checkpoint belongs to a different dump, starting from the top")
            return 0

        self.lines_done = int(saved.get("lines_done", 0))
        return self.lines_done

    def save(self, lines_done: int) -> None:
        """Written atomically: a kill -9 mid-write must not leave a torn file
        that sends the next run back to line zero."""
        self.lines_done = lines_done
        payload = {
            "dump_size": self.dump_size,
            "dump_mtime": self.dump_mtime,
            "lines_done": lines_done,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self.path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# the load
# --------------------------------------------------------------------------


def load(
    dump: Path,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: int | None = None,
    resume: bool = True,
    keep_raw: bool = False,
    dry_run: bool = False,
    progress_every: int = 50_000,
) -> Stats:
    stats = Stats()
    checkpoint = Checkpoint.for_dump(dump)
    skip = checkpoint.load() if resume else 0

    if skip:
        # gzip has no index, so the skipped lines still have to be
        # decompressed — but they are never JSON-parsed, which is the
        # expensive half.
        log.info("resuming after line %d of %s", skip, dump.name)

    conn = None
    if not dry_run:
        from importers import db

        conn = db.connect()

    food_batch: list[tuple] = []
    nutrient_batch: list[tuple] = []
    began = time.monotonic()
    last_report = began

    def flush() -> None:
        nonlocal food_batch, nutrient_batch

        if not food_batch:
            return

        if conn is not None:
            stats.merge.add(staging.merge_batch(conn, SOURCE, food_batch, nutrient_batch))
            checkpoint.save(skip + stats.lines)

        food_batch = []
        nutrient_batch = []

    try:
        for product in iter_products(dump, skip=skip, stats=stats):
            mapped = map_product(product, keep_raw=keep_raw)

            if mapped is None:
                if not text(product.get("code")) and not text(product.get("_id")):
                    stats.skipped_no_code += 1
                elif (text(product.get("product_type")) or "food") != "food":
                    stats.skipped_not_food += 1
                else:
                    stats.skipped_no_name += 1
            else:
                stats.mapped += 1
                food_batch.append(food_row(mapped.food))
                nutrient_batch.extend(
                    nutrient_rows(mapped.food["source_id"], mapped.nutrients)
                )

                if len(food_batch) >= batch_size:
                    flush()

            now = time.monotonic()
            if stats.lines % progress_every == 0 or now - last_report >= 30:
                rate = stats.lines / max(now - began, 1e-9)
                log.info("%s | %.0f lines/s", stats.summary(), rate)
                last_report = now

            if limit is not None and stats.mapped >= limit:
                log.info("--limit %d reached", limit)
                break

        flush()
    finally:
        if conn is not None:
            conn.close()

    elapsed = time.monotonic() - began
    log.info("done in %.1fs | %s", elapsed, stats.summary())
    return stats


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _dump_path(args: argparse.Namespace) -> Path:
    if args.file:
        return Path(args.file)

    return Path(args.data_dir) / DUMP_URL.rsplit("/", 1)[-1]


def cmd_download(args: argparse.Namespace) -> int:
    result = download(
        args.url,
        _dump_path(args),
        resume=not args.restart,
        checksum=args.checksum,
    )

    print(f"file    {result.path}")
    print(f"size    {result.size:,} bytes ({human(result.size)})")
    print(f"sha256  {result.sha256 or '(not computed; pass --checksum)'}")
    print(f"remote  last modified {result.remote_last_modified}")

    if result.already_complete:
        print("already complete, nothing downloaded")
    else:
        print(f"fetched {human(result.downloaded)} (resumed from {human(result.resumed_from)})")

    return 0


def cmd_checksum(args: argparse.Namespace) -> int:
    path = _dump_path(args)
    size = path.stat().st_size
    print(f"file    {path}")
    print(f"size    {size:,} bytes ({human(size)})")
    print(f"sha256  {sha256_file(path)}")
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    dump = _dump_path(args)

    if not dump.exists():
        log.error("no dump at %s — run `download` first", dump)
        return 1

    stats = load(
        dump,
        batch_size=args.batch_size,
        limit=args.limit,
        resume=not args.restart,
        keep_raw=args.raw_data,
        dry_run=args.dry_run,
    )

    print(stats.summary())
    return 0


def cmd_sample(args: argparse.Namespace) -> int:
    """Map the first N products and print them as JSON — no database needed."""
    dump = _dump_path(args)
    stats = Stats()
    shown = 0

    for product in iter_products(dump, stats=stats):
        mapped = map_product(product)
        if mapped is None:
            continue

        print(
            json.dumps(
                {"food": mapped.food, "nutrients": mapped.nutrients},
                indent=2,
                default=str,
                ensure_ascii=False,
            )
        )
        shown += 1

        if shown >= (args.limit or 3):
            break

    return 0


def cmd_indexes(args: argparse.Namespace) -> int:
    from importers import db

    with db.connect() as conn:
        if args.drop:
            for name in staging.drop_heavy_indexes(conn):
                print(f"dropped {name}")
        else:
            created = staging.create_heavy_indexes(conn, concurrently=args.concurrently)
            for name in created:
                print(f"created {name}")
            if not created:
                print("nothing to create; all indexes already exist")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m importers.openfoodfacts",
        description="Import the OpenFoodFacts dump into the MacroPal `foods` table.",
    )
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="where the dump lives")
    parser.add_argument("--file", help="explicit path to a dump file (overrides --data-dir)")
    parser.add_argument("-v", "--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)

    download_cmd = sub.add_parser("download", help="download or resume the dump")
    download_cmd.add_argument("--url", default=DUMP_URL)
    download_cmd.add_argument("--restart", action="store_true", help="ignore a partial file")
    download_cmd.add_argument(
        "--checksum", action="store_true", help="compute sha256 (reads ~13 GB)"
    )
    download_cmd.set_defaults(func=cmd_download)

    checksum_cmd = sub.add_parser("checksum", help="size and sha256 of the local dump")
    checksum_cmd.set_defaults(func=cmd_checksum)

    load_cmd = sub.add_parser("load", help="parse, COPY into staging, merge into foods")
    load_cmd.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    load_cmd.add_argument("--limit", type=int, help="stop after N mapped products")
    load_cmd.add_argument("--restart", action="store_true", help="ignore the checkpoint")
    load_cmd.add_argument(
        "--raw-data",
        action="store_true",
        help="store the full product blob in foods.raw_data (very large)",
    )
    load_cmd.add_argument(
        "--dry-run", action="store_true", help="parse and map only, touch no database"
    )
    load_cmd.set_defaults(func=cmd_load)

    sample_cmd = sub.add_parser("sample", help="print mapped products as JSON (no database)")
    sample_cmd.add_argument("--limit", type=int, default=3)
    sample_cmd.set_defaults(func=cmd_sample)

    indexes_cmd = sub.add_parser("indexes", help="drop or rebuild the heavy GIN indexes")
    group = indexes_cmd.add_mutually_exclusive_group(required=True)
    group.add_argument("--drop", action="store_true")
    group.add_argument("--create", action="store_true")
    indexes_cmd.add_argument("--concurrently", action="store_true", help="build without locking")
    indexes_cmd.set_defaults(func=cmd_indexes)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # The dump is multilingual and Windows consoles default to cp1252;
    # without this, printing a mapped product dies on the first accent.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
