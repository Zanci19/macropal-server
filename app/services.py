from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import nutrition, schemas
from app.models import CustomFood, DiaryEntry, Favorite, Food, MealItem, User


def resolve_food_ref(
    db: Session,
    user: User,
    ref: schemas.FoodRef,
) -> tuple[Food | None, CustomFood | None]:
    if (ref.food_id is None) == (ref.custom_food_id is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide exactly one of food_id or custom_food_id",
        )

    if ref.food_id is not None:
        food = db.get(Food, ref.food_id)

        if food is None:
            raise HTTPException(status_code=404, detail="Food not found")

        return food, None

    custom_food = db.get(CustomFood, ref.custom_food_id)

    if custom_food is None or custom_food.user_id != user.id:
        raise HTTPException(status_code=404, detail="Custom food not found")

    return None, custom_food


def item_of(holder: DiaryEntry | MealItem | Favorite) -> Food | CustomFood | None:
    return holder.food or holder.custom_food


def label(holder: DiaryEntry | MealItem | Favorite) -> tuple[str, str | None]:
    item = item_of(holder)

    if item is None:
        return "Unknown food", None

    return item.name, item.brand


def macros_of(holder: DiaryEntry | MealItem) -> nutrition.Macros:
    return nutrition.scale(item_of(holder), holder.quantity_g)


def to_macros(macros: nutrition.Macros) -> schemas.Macros:
    rounded = macros.rounded()

    return schemas.Macros(
        calories=rounded.calories,
        protein=rounded.protein,
        carbs=rounded.carbs,
        fat=rounded.fat,
    )


def to_diary_entry(entry: DiaryEntry) -> schemas.DiaryEntryOut:
    name, brand = label(entry)

    return schemas.DiaryEntryOut(
        id=entry.id,
        entry_date=entry.entry_date,
        meal=entry.meal,
        quantity_g=entry.quantity_g,
        food_id=entry.food_id,
        custom_food_id=entry.custom_food_id,
        name=name,
        brand=brand,
        total=to_macros(macros_of(entry)),
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def to_meal_item(item: MealItem) -> schemas.MealItemOut:
    name, brand = label(item)

    return schemas.MealItemOut(
        id=item.id,
        food_id=item.food_id,
        custom_food_id=item.custom_food_id,
        quantity_g=item.quantity_g,
        position=item.position,
        name=name,
        brand=brand,
        total=to_macros(macros_of(item)),
    )


def to_favorite(favorite: Favorite) -> schemas.FavoriteOut:
    name, brand = label(favorite)
    item = item_of(favorite)

    return schemas.FavoriteOut(
        id=favorite.id,
        food_id=favorite.food_id,
        custom_food_id=favorite.custom_food_id,
        name=name,
        brand=brand,
        energy_kcal_100g=item.energy_kcal_100g if item else None,
        created_at=favorite.created_at,
    )


def to_meal(meal) -> schemas.MealOut:
    items = [to_meal_item(item) for item in meal.items]
    combined = nutrition.total([macros_of(item) for item in meal.items])

    return schemas.MealOut(
        id=meal.id,
        name=meal.name,
        notes=meal.notes,
        items=items,
        total=to_macros(combined),
        created_at=meal.created_at,
        updated_at=meal.updated_at,
    )


def user_targets(user: User) -> schemas.Macros:
    return schemas.Macros(
        calories=user.calorie_target or 0,
        protein=user.protein_target or 0,
        carbs=user.carbs_target or 0,
        fat=user.fat_target or 0,
    )
