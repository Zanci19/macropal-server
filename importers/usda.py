from __future__ import annotations

import argparse
import csv
import io
import logging
import os
import re
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator

from importers import db, staging
from importers.download import download, human

log = logging.getLogger("usda")

BASE_URL = "https://fdc.nal.usda.gov/fdc-datasets/"

DATASETS: dict[str, tuple[str, str]] = {
    "foundation": ("FoodData_Central_foundation_food_csv_2026-04-30.zip", "foundation_food"),
    "sr_legacy": ("FoodData_Central_sr_legacy_food_csv_2018-04.zip", "sr_legacy_food"),
}

DEFAULT_DATA_DIR = Path(os.environ.get("USDA_DATA_DIR") or (Path(__file__).resolve().parent.parent / "data" / "usda"))
DEFAULT_BATCH_SIZE = 2_000
SOURCE = "usda"

ENERGY_KCAL_IDS = ("1008", "2048", "2047")
ENERGY_KJ_IDS = ("1062",)

COLUMN_NUTRIENTS: dict[str, str] = {
    "1003": "protein_100g",
    "1004": "fat_100g",
    "1005": "carbs_100g",
    "1258": "saturated_fat_100g",
    "1257": "trans_fat_100g",
    "2000": "sugars_100g",
    "1063": "sugars_100g",
    "1079": "fiber_100g",
    "1093": "sodium_100g",
    "1253": "cholesterol_100g",
}

MASS_UNITS: dict[str, Decimal] = {
    "G": Decimal(1),
    "MG": Decimal("0.001"),
    "UG": Decimal("0.000001"),
}

SODIUM_TO_SALT = Decimal("2.5")
KCAL_TO_KJ = Decimal("4.184")


@dataclass(slots=True)
class Stats:
    foods_seen: int = 0
    mapped: int = 0
    skipped_no_name: int = 0
    skipped_wrong_type: int = 0
    nutrients: int = 0
    merge: staging.MergeCounts = field(default_factory=staging.MergeCounts)

    def line(self) -> str:
        m = self.merge
        return (
            f"foods={self.foods_seen:,} mapped={self.mapped:,} "
            f"inserted={m.inserted:,} updated={m.updated:,} rejected={m.rejected:,} "
            f"nutrients={m.nutrients_upserted:,} (pruned {m.nutrients_removed:,}) "
            f"skipped: wrong_type={self.skipped_wrong_type:,} no_name={self.skipped_no_name:,}"
        )


def slug(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    text = re.sub(r"([a-z])-(\d)", r"\1\2", text)

    return text


def number(value: str | None) -> Decimal | None:
    if not value:
        return None

    try:
        result = Decimal(value)
    except InvalidOperation:
        return None

    return result if result.is_finite() else None


def dataset_url(name: str) -> str:
    return BASE_URL + DATASETS[name][0]


def dataset_path(data_dir: Path, name: str) -> Path:
    return data_dir / DATASETS[name][0]


def archive_root(archive: zipfile.ZipFile) -> str:
    for item in archive.namelist():
        head, _, _ = item.partition("/")
        if head:
            return head + "/"

    return ""


def read_csv(archive: zipfile.ZipFile, root: str, name: str) -> Iterator[dict[str, str]]:
    with archive.open(f"{root}{name}") as handle:
        yield from csv.DictReader(io.TextIOWrapper(handle, "utf-8-sig"))


def nutrient_lookup(archive: zipfile.ZipFile, root: str) -> dict[str, tuple[str, str]]:
    return {
        row["id"]: (row["name"], row["unit_name"].upper())
        for row in read_csv(archive, root, "nutrient.csv")
    }


def category_lookup(archive: zipfile.ZipFile, root: str) -> dict[str, str]:
    return {
        row["id"]: row["description"]
        for row in read_csv(archive, root, "food_category.csv")
    }


def portion_lookup(archive: zipfile.ZipFile, root: str, wanted: set[str]) -> dict[str, tuple[Decimal, str]]:
    units = {row["id"]: row["name"] for row in read_csv(archive, root, "measure_unit.csv")}
    portions: dict[str, tuple[Decimal, str]] = {}

    try:
        rows = read_csv(archive, root, "food_portion.csv")
    except KeyError:
        return portions

    for row in rows:
        fdc_id = row["fdc_id"]

        if fdc_id not in wanted or fdc_id in portions:
            continue

        grams = number(row.get("gram_weight"))

        if not grams or grams <= 0:
            continue

        label = (row.get("portion_description") or "").strip()

        if not label or label.lower() == "quantity not specified":
            unit = units.get(row.get("measure_unit_id", ""), "")
            amount = (row.get("amount") or "").strip()
            modifier = (row.get("modifier") or "").strip()
            label = " ".join(part for part in (amount, unit, modifier) if part and unit != "undetermined")

        portions[fdc_id] = (grams, label.strip())

    return portions


def nutrients_by_food(
    archive: zipfile.ZipFile, root: str, wanted: set[str]
) -> dict[str, list[tuple[str, Decimal]]]:
    grouped: dict[str, list[tuple[str, Decimal]]] = defaultdict(list)

    for row in read_csv(archive, root, "food_nutrient.csv"):
        fdc_id = row["fdc_id"]

        if fdc_id not in wanted:
            continue

        amount = number(row.get("amount"))

        if amount is None:
            continue

        grouped[fdc_id].append((row["nutrient_id"], amount))

    return grouped


def pick_energy(values: dict[str, Decimal], ids: tuple[str, ...]) -> Decimal | None:
    for nutrient_id in ids:
        if nutrient_id in values:
            return values[nutrient_id]

    return None


def map_food(
    row: dict[str, str],
    measurements: list[tuple[str, Decimal]],
    nutrients: dict[str, tuple[str, str]],
    categories: dict[str, str],
    portion: tuple[Decimal, str] | None,
) -> tuple[dict, list[dict]] | None:
    name = (row.get("description") or "").strip()

    if not name:
        return None

    fdc_id = row["fdc_id"]
    values = {nutrient_id: amount for nutrient_id, amount in measurements}

    food: dict[str, object] = {column: None for column in staging.FOOD_COLUMNS}

    food["name"] = name
    food["category"] = categories.get(row.get("food_category_id", ""))
    food["language"] = "en"
    food["countries"] = ["united states"]
    food["source"] = SOURCE
    food["source_id"] = fdc_id
    food["source_url"] = f"https://fdc.nal.usda.gov/food-details/{fdc_id}/nutrients"
    food["verified"] = True
    food["obsolete"] = False

    published = (row.get("publication_date") or "").strip()

    if published:
        try:
            food["source_updated_at"] = datetime.strptime(published, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            food["source_updated_at"] = None

    if portion:
        grams, label = portion
        food["serving_quantity"] = grams
        food["serving_unit"] = "g"
        food["serving_size_text"] = label or f"{grams} g"

    kcal = pick_energy(values, ENERGY_KCAL_IDS)
    kj = pick_energy(values, ENERGY_KJ_IDS)

    food["energy_kcal_100g"] = kcal
    food["energy_kj_100g"] = kj if kj is not None else (kcal * KCAL_TO_KJ if kcal else None)

    extra: list[dict] = []

    for nutrient_id, amount in measurements:
        meta = nutrients.get(nutrient_id)

        if meta is None:
            continue

        label, unit = meta
        column = COLUMN_NUTRIENTS.get(nutrient_id)
        factor = MASS_UNITS.get(unit)

        if column:
            if factor is None or amount < 0:
                continue

            if food.get(column) is None:
                food[column] = amount * factor

            continue

        if factor is None or amount < 0:
            continue

        extra.append(
            {
                "source_id": fdc_id,
                "nutrient_code": slug(label),
                "nutrient_name": label,
                "amount_100g": amount * factor,
                "amount_serving": None,
                "unit": "g",
            }
        )

    sodium = food.get("sodium_100g")

    if isinstance(sodium, Decimal) and food.get("salt_100g") is None:
        food["salt_100g"] = sodium * SODIUM_TO_SALT

    return food, extra


def food_row(food: dict) -> tuple:
    return tuple(food[column] for column in staging.FOOD_COLUMNS)


def nutrient_row(entry: dict) -> tuple:
    return tuple(entry[column] for column in staging.NUTRIENT_COLUMNS)


def iter_mapped(
    archive: zipfile.ZipFile, root: str, data_type: str, stats: Stats, limit: int | None
) -> Iterator[tuple[dict, list[dict]]]:
    nutrients = nutrient_lookup(archive, root)
    categories = category_lookup(archive, root)

    keep: list[dict[str, str]] = []

    for row in read_csv(archive, root, "food.csv"):
        stats.foods_seen += 1

        if row.get("data_type") != data_type:
            stats.skipped_wrong_type += 1
            continue

        keep.append(row)

        if limit and len(keep) >= limit:
            break

    wanted = {row["fdc_id"] for row in keep}
    log.info("%s: %s of %s rows are %s", root.rstrip("/"), f"{len(keep):,}", f"{stats.foods_seen:,}", data_type)

    measurements = nutrients_by_food(archive, root, wanted)
    portions = portion_lookup(archive, root, wanted)

    for row in keep:
        mapped = map_food(
            row,
            measurements.get(row["fdc_id"], []),
            nutrients,
            categories,
            portions.get(row["fdc_id"]),
        )

        if mapped is None:
            stats.skipped_no_name += 1
            continue

        stats.mapped += 1
        stats.nutrients += len(mapped[1])
        yield mapped


def load(path: Path, data_type: str, *, batch_size: int, limit: int | None, dry_run: bool) -> Stats:
    stats = Stats()

    with zipfile.ZipFile(path) as archive:
        root = archive_root(archive)
        foods: list[tuple] = []
        extras: list[tuple] = []

        connection = None if dry_run else db.connect()

        try:
            def flush() -> None:
                if not foods or connection is None:
                    foods.clear()
                    extras.clear()
                    return

                stats.merge.add(staging.merge_batch(connection, SOURCE, foods, extras))
                foods.clear()
                extras.clear()
                log.info(stats.line())

            for food, extra in iter_mapped(archive, root, data_type, stats, limit):
                foods.append(food_row(food))
                extras.extend(nutrient_row(entry) for entry in extra)

                if len(foods) >= batch_size:
                    flush()

            flush()
        finally:
            if connection is not None:
                connection.close()

    return stats


def cmd_download(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    for name in args.datasets:
        url = args.url or dataset_url(name)
        target = dataset_path(data_dir, name)
        result = download(url, target, restart=args.restart)
        log.info("%s -> %s (%s)", name, target, human(result.size) if hasattr(result, "size") else "done")

    return 0


def cmd_load(args: argparse.Namespace) -> int:
    for name in args.datasets:
        path = Path(args.file) if args.file else dataset_path(Path(args.data_dir), name)

        if not path.exists():
            log.error("%s not found. Run the download command first.", path)
            return 1

        stats = load(
            path,
            DATASETS[name][1],
            batch_size=args.batch_size,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        print(f"{name}: {stats.line()}")

    return 0


def cmd_sample(args: argparse.Namespace) -> int:
    import json

    name = args.datasets[0]
    path = Path(args.file) if args.file else dataset_path(Path(args.data_dir), name)
    stats = Stats()

    with zipfile.ZipFile(path) as archive:
        root = archive_root(archive)
        shown = 0

        for food, extra in iter_mapped(archive, root, DATASETS[name][1], stats, args.limit):
            print(json.dumps({"food": food, "nutrients": extra}, indent=2, default=str))
            shown += 1

            if shown >= args.limit:
                break

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m importers.usda",
        description="Import USDA FoodData Central into MacroPal.",
    )
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--file", help="explicit path to a dataset zip")
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=["foundation", "sr_legacy"],
        choices=sorted(DATASETS),
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    commands = parser.add_subparsers(dest="command", required=True)

    download_cmd = commands.add_parser("download", help="fetch the dataset zips")
    download_cmd.add_argument("--url", help="override the download URL")
    download_cmd.add_argument("--restart", action="store_true")
    download_cmd.set_defaults(func=cmd_download)

    load_cmd = commands.add_parser("load", help="map and merge into foods")
    load_cmd.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    load_cmd.add_argument("--limit", type=int, help="stop after N foods")
    load_cmd.add_argument("--dry-run", action="store_true", help="map only, touch no database")
    load_cmd.set_defaults(func=cmd_load)

    sample_cmd = commands.add_parser("sample", help="print mapped foods as JSON")
    sample_cmd.add_argument("--limit", type=int, default=2)
    sample_cmd.set_defaults(func=cmd_sample)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
