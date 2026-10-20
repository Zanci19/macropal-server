from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import nutrition, schemas, services
from app.auth import CurrentUser
from app.database import get_db
from app.enums import MealKey
from app.models import DiaryEntry, Meal

router = APIRouter(prefix="/v1/diary", tags=["diary"])

MAX_RANGE_DAYS = 366


def owned_entry(db: Session, entry_id: int, user_id: int) -> DiaryEntry:
    entry = db.get(DiaryEntry, entry_id)

    if entry is None or entry.user_id != user_id:
        raise HTTPException(status_code=404, detail="Diary entry not found")

    return entry


@router.get("/day/{entry_date}", response_model=schemas.DiaryDay, summary="One day")
def get_day(
    entry_date: date,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> schemas.DiaryDay:
    entries = db.execute(
        select(DiaryEntry)
        .where(DiaryEntry.user_id == user.id, DiaryEntry.entry_date == entry_date)
        .order_by(DiaryEntry.created_at.asc(), DiaryEntry.id.asc())
    ).unique().scalars().all()

    sections: list[schemas.MealSection] = []

    for meal in MealKey:
        in_meal = [entry for entry in entries if entry.meal == meal.value]
        sections.append(
            schemas.MealSection(
                meal=meal,
                entries=[services.to_diary_entry(entry) for entry in in_meal],
                total=services.to_macros(
                    nutrition.total([services.macros_of(entry) for entry in in_meal])
                ),
            )
        )

    return schemas.DiaryDay(
        entry_date=entry_date,
        meals=sections,
        total=services.to_macros(
            nutrition.total([services.macros_of(entry) for entry in entries])
        ),
        targets=services.user_targets(user),
    )


@router.get("/summary", summary="Daily totals over a date range")
def get_summary(
    user: CurrentUser,
    start: date = Query(...),
    end: date = Query(...),
    db: Session = Depends(get_db),
) -> list[dict]:
    if end < start:
        raise HTTPException(status_code=422, detail="end must not be before start")

    if (end - start).days > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"Range must not exceed {MAX_RANGE_DAYS} days",
        )

    entries = db.execute(
        select(DiaryEntry)
        .where(
            DiaryEntry.user_id == user.id,
            DiaryEntry.entry_date >= start,
            DiaryEntry.entry_date <= end,
        )
        .order_by(DiaryEntry.entry_date.asc())
    ).unique().scalars().all()

    totals: dict[date, nutrition.Macros] = {}

    for entry in entries:
        totals[entry.entry_date] = totals.get(entry.entry_date, nutrition.EMPTY) + (
            services.macros_of(entry)
        )

    return [
        {"entry_date": day, "total": services.to_macros(macros)}
        for day, macros in sorted(totals.items())
    ]


@router.post(
    "/entries",
    response_model=schemas.DiaryEntryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Log a food",
)
def create_entry(
    payload: schemas.DiaryEntryCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> schemas.DiaryEntryOut:
    food, custom_food = services.resolve_food_ref(db, user, payload)

    entry = DiaryEntry(
        user_id=user.id,
        food_id=food.id if food else None,
        custom_food_id=custom_food.id if custom_food else None,
        entry_date=payload.entry_date,
        meal=payload.meal.value,
        quantity_g=payload.quantity_g,
    )

    db.add(entry)
    db.commit()
    db.refresh(entry)

    return services.to_diary_entry(entry)


@router.patch(
    "/entries/{entry_id}",
    response_model=schemas.DiaryEntryOut,
    summary="Edit an entry",
)
def update_entry(
    entry_id: int,
    payload: schemas.DiaryEntryUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> schemas.DiaryEntryOut:
    entry = owned_entry(db, entry_id, user.id)
    values = payload.model_dump(exclude_unset=True)

    if "meal" in values and values["meal"] is not None:
        values["meal"] = MealKey(values["meal"]).value

    for field, value in values.items():
        if value is not None:
            setattr(entry, field, value)

    db.commit()
    db.refresh(entry)

    return services.to_diary_entry(entry)


@router.delete(
    "/entries/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an entry",
)
def delete_entry(
    entry_id: int,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Response:
    entry = owned_entry(db, entry_id, user.id)

    db.delete(entry)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/log-meal",
    response_model=list[schemas.DiaryEntryOut],
    status_code=status.HTTP_201_CREATED,
    summary="Log every item of a saved meal",
)
def log_meal(
    payload: schemas.LogMealRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> list[schemas.DiaryEntryOut]:
    meal = db.get(Meal, payload.meal_id)

    if meal is None or meal.user_id != user.id:
        raise HTTPException(status_code=404, detail="Meal not found")

    if not meal.items:
        raise HTTPException(status_code=422, detail="That meal has no items")

    entries = [
        DiaryEntry(
            user_id=user.id,
            food_id=item.food_id,
            custom_food_id=item.custom_food_id,
            entry_date=payload.entry_date,
            meal=payload.meal.value,
            quantity_g=item.quantity_g,
        )
        for item in meal.items
    ]

    db.add_all(entries)
    db.commit()

    for entry in entries:
        db.refresh(entry)

    return [services.to_diary_entry(entry) for entry in entries]
