from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.auth import CurrentUser
from app.database import get_db
from app.models import CustomFood

router = APIRouter(prefix="/v1/me/custom-foods", tags=["custom foods"])


def owned(db: Session, food_id: int, user_id: int) -> CustomFood:
    food = db.get(CustomFood, food_id)

    if food is None or food.user_id != user_id:
        raise HTTPException(status_code=404, detail="Custom food not found")

    return food


@router.get("", response_model=list[schemas.CustomFoodOut], summary="List own foods")
def list_custom_foods(
    user: CurrentUser,
    q: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
) -> list[schemas.CustomFoodOut]:
    statement = select(CustomFood).where(CustomFood.user_id == user.id)

    if q:
        statement = statement.where(CustomFood.name.ilike(f"%{q}%"))

    foods = db.execute(statement.order_by(CustomFood.name.asc())).scalars().all()

    return [schemas.CustomFoodOut.model_validate(food) for food in foods]


@router.post(
    "",
    response_model=schemas.CustomFoodOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a food",
)
def create_custom_food(
    payload: schemas.CustomFoodCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> schemas.CustomFoodOut:
    food = CustomFood(user_id=user.id, **payload.model_dump())

    db.add(food)
    db.commit()
    db.refresh(food)

    return schemas.CustomFoodOut.model_validate(food)


@router.get("/{food_id}", response_model=schemas.CustomFoodOut, summary="Get one")
def get_custom_food(
    food_id: int,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> schemas.CustomFoodOut:
    return schemas.CustomFoodOut.model_validate(owned(db, food_id, user.id))


@router.patch("/{food_id}", response_model=schemas.CustomFoodOut, summary="Update one")
def update_custom_food(
    food_id: int,
    payload: schemas.CustomFoodUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> schemas.CustomFoodOut:
    food = owned(db, food_id, user.id)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(food, field, value)

    db.commit()
    db.refresh(food)

    return schemas.CustomFoodOut.model_validate(food)


@router.delete(
    "/{food_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one",
)
def delete_custom_food(
    food_id: int,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Response:
    db.delete(owned(db, food_id, user.id))
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
