from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import Food
from app.schemas import FoodDetail, FoodSummary, SearchResponse
from app.search import (
    barcode_statement,
    fulltext_statement,
    fuzzy_statement,
    looks_like_barcode,
    tokenize,
)

router = APIRouter(prefix="/v1/foods", tags=["foods"])


@router.get("/search", response_model=SearchResponse, summary="Search foods")
def search_foods(
    q: str = Query(..., min_length=1, max_length=200, description="Search text or barcode"),
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1),
    country: str | None = Query(None, description="Lowercase English country name, e.g. slovenia"),
    source: str | None = Query(None, description="openfoodfacts | usda | macropal | user"),
    brand: str | None = Query(None),
    include_obsolete: bool = Query(False),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SearchResponse:
    tokens = tokenize(q)

    if not tokens:
        raise HTTPException(
            status_code=422,
            detail="Query must contain at least one letter or digit",
        )

    page_size = min(page_size or settings.default_page_size, settings.max_page_size)
    offset = (page - 1) * page_size

    def run(statement) -> list[Food]:
        return list(
            db.execute(statement.limit(page_size + 1).offset(offset)).scalars().all()
        )

    filters = {
        "country": country,
        "source": source,
        "brand": brand,
        "include_obsolete": include_obsolete,
    }

    strategy = "fulltext"
    rows: list[Food] = []

    if looks_like_barcode(q):
        rows = run(barcode_statement(q, include_obsolete=include_obsolete))

        if rows:
            strategy = "barcode"

    if not rows:
        rows = run(fulltext_statement(tokens, **filters))

    if not rows:
        db.execute(
            select(
                func.set_config(
                    "pg_trgm.similarity_threshold",
                    str(settings.fuzzy_threshold),
                    True,
                )
            )
        )
        rows = run(fuzzy_statement(tokens, **filters))
        strategy = "fuzzy"

    return SearchResponse(
        query=q,
        page=page,
        page_size=page_size,
        has_more=len(rows) > page_size,
        strategy=strategy,
        items=[FoodSummary.model_validate(row) for row in rows[:page_size]],
    )


@router.get(
    "/barcode/{barcode}",
    response_model=FoodDetail,
    summary="Look up a food by barcode",
)
def get_food_by_barcode(
    barcode: str,
    include_obsolete: bool = Query(False),
    db: Session = Depends(get_db),
) -> Food:
    food = db.execute(
        barcode_statement(barcode, include_obsolete=include_obsolete).limit(1)
    ).scalar_one_or_none()

    if food is None:
        raise HTTPException(status_code=404, detail="Food not found")

    return food


@router.get("/{food_id}", response_model=FoodDetail, summary="Get one food by id")
def get_food(food_id: int, db: Session = Depends(get_db)) -> Food:
    food = db.get(Food, food_id)

    if food is None:
        raise HTTPException(status_code=404, detail="Food not found")

    return food
