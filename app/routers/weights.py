from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.auth import CurrentUser
from app.database import get_db
from app.models import Weight

router = APIRouter(prefix="/v1/me/weights", tags=["weights"])


@router.get("", response_model=list[schemas.WeightOut], summary="Weight history")
def list_weights(
    user: CurrentUser,
    start: date | None = Query(None),
    end: date | None = Query(None),
    limit: int = Query(365, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> list[schemas.WeightOut]:
    statement = select(Weight).where(Weight.user_id == user.id)

    if start:
        statement = statement.where(Weight.entry_date >= start)

    if end:
        statement = statement.where(Weight.entry_date <= end)

    weights = db.execute(
        statement.order_by(Weight.entry_date.desc()).limit(limit)
    ).scalars().all()

    return [schemas.WeightOut.model_validate(weight) for weight in weights]


@router.put(
    "/{entry_date}",
    response_model=schemas.WeightOut,
    summary="Record or replace one day's weight",
)
def put_weight(
    entry_date: date,
    payload: schemas.WeightIn,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> schemas.WeightOut:
    weight = db.execute(
        select(Weight).where(Weight.user_id == user.id, Weight.entry_date == entry_date)
    ).scalar_one_or_none()

    if weight is None:
        weight = Weight(
            user_id=user.id,
            entry_date=entry_date,
            weight_kg=payload.weight_kg,
        )
        db.add(weight)
    else:
        weight.weight_kg = payload.weight_kg

    db.commit()
    db.refresh(weight)

    return schemas.WeightOut.model_validate(weight)


@router.delete(
    "/{entry_date}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one day's weight",
)
def delete_weight(
    entry_date: date,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Response:
    weight = db.execute(
        select(Weight).where(Weight.user_id == user.id, Weight.entry_date == entry_date)
    ).scalar_one_or_none()

    if weight is None:
        raise HTTPException(status_code=404, detail="No weight recorded for that date")

    db.delete(weight)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
