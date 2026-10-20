from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas, services
from app.auth import CurrentUser
from app.database import get_db
from app.models import Favorite

router = APIRouter(prefix="/v1/me/favorites", tags=["favorites"])


@router.get("", response_model=list[schemas.FavoriteOut], summary="List favorites")
def list_favorites(
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> list[schemas.FavoriteOut]:
    favorites = db.execute(
        select(Favorite)
        .where(Favorite.user_id == user.id)
        .order_by(Favorite.created_at.desc())
    ).unique().scalars().all()

    return [services.to_favorite(favorite) for favorite in favorites]


@router.post(
    "",
    response_model=schemas.FavoriteOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a favorite",
)
def create_favorite(
    payload: schemas.FavoriteCreate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> schemas.FavoriteOut:
    food, custom_food = services.resolve_food_ref(db, user, payload)

    favorite = Favorite(
        user_id=user.id,
        food_id=food.id if food else None,
        custom_food_id=custom_food.id if custom_food else None,
    )

    db.add(favorite)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()

        existing = db.execute(
            select(Favorite).where(
                Favorite.user_id == user.id,
                Favorite.food_id == favorite.food_id,
                Favorite.custom_food_id == favorite.custom_food_id,
            )
        ).unique().scalar_one_or_none()

        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Could not add that favorite",
            ) from None

        return services.to_favorite(existing)

    db.refresh(favorite)

    return services.to_favorite(favorite)


@router.delete(
    "/{favorite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a favorite",
)
def delete_favorite(
    favorite_id: int,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Response:
    favorite = db.get(Favorite, favorite_id)

    if favorite is None or favorite.user_id != user.id:
        raise HTTPException(status_code=404, detail="Favorite not found")

    db.delete(favorite)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
