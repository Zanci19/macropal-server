from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import ActivityLevel, GoalType, MealKey, Sex, UnitSystem


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class NutrientOut(ORMModel):
    nutrient_code: str
    nutrient_name: str | None = None
    amount_100g: float | None = None
    amount_serving: float | None = None
    unit: str | None = None


class FoodSummary(ORMModel):
    id: int
    barcode: str | None = None
    name: str
    brand: str | None = None
    category: str | None = None

    serving_size_text: str | None = None
    serving_quantity: float | None = None
    serving_unit: str | None = None

    energy_kcal_100g: float | None = None
    protein_100g: float | None = None
    carbs_100g: float | None = None
    fat_100g: float | None = None

    nutriscore_grade: str | None = None
    nova_group: int | None = None

    image_front_url: str | None = None

    source: str
    verified: bool
    obsolete: bool


class FoodDetail(FoodSummary):
    generic_name: str | None = None
    brand_owner: str | None = None
    food_group: str | None = None

    language: str | None = None
    countries: list[str] | None = None

    quantity_text: str | None = None
    product_quantity: float | None = None
    product_quantity_unit: str | None = None

    energy_kj_100g: float | None = None

    saturated_fat_100g: float | None = None
    trans_fat_100g: float | None = None
    sugars_100g: float | None = None
    fiber_100g: float | None = None

    salt_100g: float | None = None
    sodium_100g: float | None = None
    cholesterol_100g: float | None = None

    ingredients_text: str | None = None
    allergens_text: str | None = None
    traces_text: str | None = None

    nutriscore_score: int | None = None
    additives_count: int | None = None

    image_url: str | None = None
    image_nutrition_url: str | None = None
    image_ingredients_url: str | None = None

    source_id: str | None = None
    source_url: str | None = None

    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    nutrients: list[NutrientOut] = []


class SearchResponse(BaseModel):
    query: str
    page: int
    page_size: int
    has_more: bool
    strategy: str
    items: list[FoodSummary]


class Macros(BaseModel):
    calories: float = 0
    protein: float = 0
    carbs: float = 0
    fat: float = 0


class UserOut(ORMModel):
    id: int
    firebase_uid: str

    username: str | None = None
    email: str | None = None
    display_name: str | None = None

    birth_date: date | None = None
    sex: Sex | None = None

    height_cm: float | None = None

    activity_level: ActivityLevel | None = None
    goal: GoalType | None = None

    calorie_target: int | None = None
    protein_target: float | None = None
    carbs_target: float | None = None
    fat_target: float | None = None

    unit_system: UnitSystem

    created_at: datetime
    updated_at: datetime


class UserUpdate(BaseModel):
    username: str | None = Field(None, min_length=3, max_length=50)
    display_name: str | None = Field(None, max_length=200)

    birth_date: date | None = None
    sex: Sex | None = None

    height_cm: float | None = Field(None, gt=0, lt=300)

    activity_level: ActivityLevel | None = None
    goal: GoalType | None = None

    calorie_target: int | None = Field(None, gt=0, lt=20000)
    protein_target: float | None = Field(None, ge=0, lt=2000)
    carbs_target: float | None = Field(None, ge=0, lt=2000)
    fat_target: float | None = Field(None, ge=0, lt=2000)

    unit_system: UnitSystem | None = None


class GoalOut(ORMModel):
    id: int
    effective_from: date
    goal: GoalType | None = None
    calorie_target: int | None = None
    protein_target: float | None = None
    carbs_target: float | None = None
    fat_target: float | None = None
    created_at: datetime


class GoalCreate(BaseModel):
    effective_from: date | None = None
    goal: GoalType | None = None
    calorie_target: int | None = Field(None, gt=0, lt=20000)
    protein_target: float | None = Field(None, ge=0, lt=2000)
    carbs_target: float | None = Field(None, ge=0, lt=2000)
    fat_target: float | None = Field(None, ge=0, lt=2000)


class CustomFoodBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=300)
    brand: str | None = Field(None, max_length=200)
    barcode: str | None = Field(None, max_length=32)

    serving_size_text: str | None = Field(None, max_length=100)
    serving_quantity: float | None = Field(None, gt=0)
    serving_unit: str | None = Field(None, max_length=20)

    energy_kcal_100g: float | None = Field(None, ge=0, le=1000)
    protein_100g: float | None = Field(None, ge=0, le=100)
    carbs_100g: float | None = Field(None, ge=0, le=100)
    fat_100g: float | None = Field(None, ge=0, le=100)

    saturated_fat_100g: float | None = Field(None, ge=0, le=100)
    sugars_100g: float | None = Field(None, ge=0, le=100)
    fiber_100g: float | None = Field(None, ge=0, le=100)
    salt_100g: float | None = Field(None, ge=0, le=100)


class CustomFoodCreate(CustomFoodBase):
    pass


class CustomFoodUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=300)
    brand: str | None = Field(None, max_length=200)
    barcode: str | None = Field(None, max_length=32)

    serving_size_text: str | None = Field(None, max_length=100)
    serving_quantity: float | None = Field(None, gt=0)
    serving_unit: str | None = Field(None, max_length=20)

    energy_kcal_100g: float | None = Field(None, ge=0, le=1000)
    protein_100g: float | None = Field(None, ge=0, le=100)
    carbs_100g: float | None = Field(None, ge=0, le=100)
    fat_100g: float | None = Field(None, ge=0, le=100)

    saturated_fat_100g: float | None = Field(None, ge=0, le=100)
    sugars_100g: float | None = Field(None, ge=0, le=100)
    fiber_100g: float | None = Field(None, ge=0, le=100)
    salt_100g: float | None = Field(None, ge=0, le=100)


class CustomFoodOut(CustomFoodBase, ORMModel):
    id: int
    created_at: datetime
    updated_at: datetime


class FoodRef(BaseModel):
    food_id: int | None = None
    custom_food_id: int | None = None


class DiaryEntryCreate(FoodRef):
    entry_date: date
    meal: MealKey
    quantity_g: float = Field(..., gt=0, le=20000)


class DiaryEntryUpdate(BaseModel):
    entry_date: date | None = None
    meal: MealKey | None = None
    quantity_g: float | None = Field(None, gt=0, le=20000)


class DiaryEntryOut(ORMModel):
    id: int
    entry_date: date
    meal: MealKey
    quantity_g: float

    food_id: int | None = None
    custom_food_id: int | None = None

    name: str
    brand: str | None = None

    total: Macros

    created_at: datetime
    updated_at: datetime


class MealSection(BaseModel):
    meal: MealKey
    entries: list[DiaryEntryOut]
    total: Macros


class DiaryDay(BaseModel):
    entry_date: date
    meals: list[MealSection]
    total: Macros
    targets: Macros


class MealItemIn(FoodRef):
    quantity_g: float = Field(..., gt=0, le=20000)
    position: int = Field(0, ge=0)


class MealItemOut(ORMModel):
    id: int
    food_id: int | None = None
    custom_food_id: int | None = None
    quantity_g: float
    position: int

    name: str
    brand: str | None = None
    total: Macros


class MealCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    notes: str | None = Field(None, max_length=2000)
    items: list[MealItemIn] = []


class MealUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    notes: str | None = Field(None, max_length=2000)
    items: list[MealItemIn] | None = None


class MealOut(ORMModel):
    id: int
    name: str
    notes: str | None = None
    items: list[MealItemOut]
    total: Macros
    created_at: datetime
    updated_at: datetime


class LogMealRequest(BaseModel):
    meal_id: int
    entry_date: date
    meal: MealKey


class WeightIn(BaseModel):
    weight_kg: float = Field(..., gt=0, lt=1000)


class WeightOut(ORMModel):
    id: int
    entry_date: date
    weight_kg: float
    created_at: datetime


class FavoriteCreate(FoodRef):
    pass


class FavoriteOut(ORMModel):
    id: int
    food_id: int | None = None
    custom_food_id: int | None = None
    name: str
    brand: str | None = None
    energy_kcal_100g: float | None = None
    created_at: datetime
