import re

from sqlalchemy import ColumnElement, Select, case, func, select

from app.models import Food

TOKEN_RE = re.compile(r"\w+", re.UNICODE)

MAX_TOKENS = 10


def tokenize(query: str) -> list[str]:
    return TOKEN_RE.findall(query.lower())[:MAX_TOKENS]


def looks_like_barcode(query: str) -> bool:
    stripped = query.strip()

    return stripped.isdigit() and 8 <= len(stripped) <= 14


def _boost(normalized_query: str) -> ColumnElement[float]:
    lower_name = func.lower(Food.name)

    return (
        case((lower_name == normalized_query, 4.0), else_=0.0)
        + case((lower_name.like(f"{normalized_query}%"), 2.0), else_=0.0)
        + case((Food.verified.is_(True), 0.5), else_=0.0)
        + case((Food.brand.is_(None), 0.3), else_=0.0)
        + case((Food.energy_kcal_100g.is_not(None), 0.3), else_=0.0)
    )


def _apply_filters(
    statement: Select,
    *,
    country: str | None,
    source: str | None,
    brand: str | None,
    include_obsolete: bool,
) -> Select:
    if not include_obsolete:
        statement = statement.where(Food.obsolete.is_(False))

    if country:
        statement = statement.where(Food.countries.contains([country.strip().lower()]))

    if source:
        statement = statement.where(Food.source == source.strip().lower())

    if brand:
        statement = statement.where(func.lower(Food.brand) == brand.strip().lower())

    return statement


def fulltext_statement(
    tokens: list[str],
    *,
    country: str | None = None,
    source: str | None = None,
    brand: str | None = None,
    include_obsolete: bool = False,
) -> Select:
    normalized_query = " ".join(tokens)
    tsquery = func.to_tsquery("simple", " & ".join(f"{token}:*" for token in tokens))

    score = func.ts_rank_cd(Food.search_vector, tsquery) + _boost(normalized_query)

    statement = select(Food).where(
        Food.search_vector.op("@@", is_comparison=True)(tsquery)
    )
    statement = _apply_filters(
        statement,
        country=country,
        source=source,
        brand=brand,
        include_obsolete=include_obsolete,
    )

    return statement.order_by(
        score.desc(),
        func.length(Food.name).asc(),
        Food.id.asc(),
    )


def fuzzy_statement(
    tokens: list[str],
    *,
    country: str | None = None,
    source: str | None = None,
    brand: str | None = None,
    include_obsolete: bool = False,
) -> Select:
    normalized_query = " ".join(tokens)
    lower_name = func.lower(Food.name)
    similarity = func.similarity(lower_name, normalized_query)

    statement = select(Food).where(lower_name.op("%", is_comparison=True)(normalized_query))
    statement = _apply_filters(
        statement,
        country=country,
        source=source,
        brand=brand,
        include_obsolete=include_obsolete,
    )

    return statement.order_by(
        similarity.desc(),
        func.length(Food.name).asc(),
        Food.id.asc(),
    )


def barcode_statement(barcode: str, *, include_obsolete: bool = False) -> Select:
    statement = select(Food).where(Food.barcode == barcode.strip())

    if not include_obsolete:
        statement = statement.where(Food.obsolete.is_(False))

    return statement.order_by(
        Food.verified.desc(),
        Food.energy_kcal_100g.is_(None).asc(),
        Food.source_updated_at.desc().nullslast(),
        Food.id.asc(),
    )
