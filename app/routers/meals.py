from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas, services
from app.auth import CurrentUser
from app.database import get_db
from app.models import Meal, MealItem, User

router = APIRouter(prefix="/v1/me/meals", tags=["meals"])


def owned(db: Session, meal_id: int, user_id: int) -> Meal:
    meal = db.get(Meal, meal_id)

    if meal is None or meal.user_id != user_id:
        raise HTTPException(status_code=404, detail="Meal not found")

    return meal


def build_items(db: Session, user: User, items: list[schemas.MealItemIn]) -> list[MealItem]:
    built: list[MealItem] = []

    for position, item in enumerate(items):
        food, custom_food = services.resolve_food_ref(db, user, item)
        built.append(
            MealItem(
                food_id=food.id if food else None,
                custom_food_id=custom_food.id if custom_food else None,
                quantity_g=item.quantity_g,
                position=item.position or position,
            )
        )

    return built


@router.get("", response_model=list[schemas.MealOut], summary="List saved meals")
def list_meals(
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> list[schemas.MealOut]:
    meals = db.execute(
        select(Meal).where(Meal.user_id == user.id).order_by(Meal.name.asc())
    ).unique().scalars().all()

    return [services.to_meal(meal) for meal in meals]


@router.post(
    "",
    response_model=schemas.MealOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a saved meal",
)
def create_meal(
    payload: schemas.MealCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> schemas.MealOut:
    meal = Meal(
        user_id=user.id,
        name=payload.name,
        notes=payload.notes,
        items=build_items(db, user, payload.items),
    )

    db.add(meal)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a meal with that name",
        ) from None

    db.refresh(meal)

    return services.to_meal(meal)


@router.get("/{meal_id}", response_model=schemas.MealOut, summary="Get one meal")
def get_meal(
    meal_id: int,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> schemas.MealOut:
    return services.to_meal(owned(db, meal_id, user.id))


@router.patch("/{meal_id}", response_model=schemas.MealOut, summary="Update a meal")
def update_meal(
    meal_id: int,
    payload: schemas.MealUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> schemas.MealOut:
    meal = owned(db, meal_id, user.id)

    if payload.name is not None:
        meal.name = payload.name

    if payload.notes is not None:
        meal.notes = payload.notes

    if payload.items is not None:
        meal.items = build_items(db, user, payload.items)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a meal with that name",
        ) from None

    db.refresh(meal)

    return services.to_meal(meal)


@router.delete(
    "/{meal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a meal",
)
def delete_meal(
    meal_id: int,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Response:
    db.delete(owned(db, meal_id, user.id))
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
