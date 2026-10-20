"""Refresh `tests/data/off_sample.jsonl.gz` from the live OpenFoodFacts dump.

    python -m scripts.fetch_off_sample --count 12

The importer's tests run against real dump records, not hand-written ones:
OFF's quirks (a `serving_quantity` that is a string, a `nutriscore_grade` of
`not-applicable`, an `images.selected` tree that moved between schema
versions) are exactly the things invented fixtures get wrong.

Only the first few megabytes of the 13 GB file are fetched, with an HTTP
`Range` request — gzip decompresses from the start, so the leading chunk is
readable on its own.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
from pathlib import Path

import httpx

from importers.openfoodfacts import DUMP_URL

DEST = Path(__file__).resolve().parent.parent / "tests" / "data" / "off_sample.jsonl.gz"

# The records are trimmed to these keys. A full OFF product is ~60 KB of
# ingredient hierarchies, per-editor history and environmental-score workings;
# none of it is read by the importer, and 12 untrimmed products would put
# several megabytes of noise in the repository.
KEEP = {
    "_id",
    "code",
    "product_type",
    "lang",
    "lc",
    "product_name",
    "product_name_en",
    "product_name_fr",
    "generic_name",
    "generic_name_en",
    "abbreviated_product_name",
    "brands",
    "brands_tags",
    "brand_owner",
    "owner",
    "categories",
    "categories_tags",
    "food_groups",
    "food_groups_tags",
    "countries_tags",
    "quantity",
    "product_quantity",
    "product_quantity_unit",
    "serving_size",
    "serving_quantity",
    "serving_quantity_unit",
    "ingredients_text",
    "ingredients_text_en",
    "ingredients_text_fr",
    "allergens",
    "allergens_tags",
    "traces",
    "traces_tags",
    "nutriscore_grade",
    "nutrition_grades",
    "nutriscore_score",
    "nova_group",
    "additives_n",
    "images",
    "obsolete",
    "created_t",
    "last_modified_t",
    "nutriments",
    "schema_version",
}


def trim(product: dict) -> dict:
    trimmed = {k: v for k, v in product.items() if k in KEEP}

    # `images.uploaded` is one entry per photo ever uploaded and dwarfs the
    # rest; only `selected` drives the image URLs.
    images = trimmed.get("images")
    if isinstance(images, dict) and "selected" in images:
        trimmed["images"] = {"selected": images["selected"]}

    return trimmed


def fetch(count: int, byte_range: int, url: str) -> list[dict]:
    headers = {"Range": f"bytes=0-{byte_range}"}

    with httpx.Client(follow_redirects=True, timeout=120.0) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()

    products: list[dict] = []
    stream = gzip.GzipFile(fileobj=io.BytesIO(response.content))

    try:
        for line in stream:
            products.append(json.loads(line))
            if len(products) >= count:
                break
    except (EOFError, OSError) as exc:
        # Expected: the range stops mid-member, so the last block is truncated.
        if not products:
            raise RuntimeError(f"no complete records in the first {byte_range} bytes") from exc

    return products


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--bytes", type=int, default=4_000_000, help="how much of the dump to pull")
    parser.add_argument("--url", default=DUMP_URL)
    parser.add_argument("--dest", default=str(DEST))
    parser.add_argument("--full", action="store_true", help="do not trim the records")
    args = parser.parse_args()

    products = fetch(args.count, args.bytes, args.url)
    dest = Path(args.dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    with gzip.open(dest, "wt", encoding="utf-8") as handle:
        for product in products:
            handle.write(json.dumps(product if args.full else trim(product), ensure_ascii=False))
            handle.write("\n")

    print(f"wrote {len(products)} products to {dest} ({dest.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
