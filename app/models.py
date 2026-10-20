from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import ActivityLevel, GoalType, MealKey, Sex, UnitSystem, sql_check

SEARCH_VECTOR_SQL = (
    "to_tsvector('simple', "
    "coalesce(name, '') || ' ' || "
    "coalesce(generic_name, '') || ' ' || "
    "coalesce(brand, '') || ' ' || "
    "coalesce(category, ''))"
)

Nutrient = Numeric(asdecimal=False)

ONE_FOOD_REFERENCE = "(food_id IS NOT NULL) <> (custom_food_id IS NOT NULL)"


class Food(Base):
    __tablename__ = "foods"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    barcode: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    generic_name: Mapped[str | None] = mapped_column(Text)

    brand: Mapped[str | None] = mapped_column(Text)
    brand_owner: Mapped[str | None] = mapped_column(Text)

    category: Mapped[str | None] = mapped_column(Text)
    food_group: Mapped[str | None] = mapped_column(Text)

    language: Mapped[str | None] = mapped_column(String(10))
    countries: Mapped[list[str] | None] = mapped_column(ARRAY(Text))

    quantity_text: Mapped[str | None] = mapped_column(Text)
    product_quantity: Mapped[float | None] = mapped_column(Nutrient)
    product_quantity_unit: Mapped[str | None] = mapped_column(String(20))

    serving_size_text: Mapped[str | None] = mapped_column(Text)
    serving_quantity: Mapped[float | None] = mapped_column(Nutrient)
    serving_unit: Mapped[str | None] = mapped_column(String(20))

    energy_kcal_100g: Mapped[float | None] = mapped_column(Nutrient)
    energy_kj_100g: Mapped[float | None] = mapped_column(Nutrient)

    protein_100g: Mapped[float | None] = mapped_column(Nutrient)
    carbs_100g: Mapped[float | None] = mapped_column(Nutrient)
    fat_100g: Mapped[float | None] = mapped_column(Nutrient)

    saturated_fat_100g: Mapped[float | None] = mapped_column(Nutrient)
    trans_fat_100g: Mapped[float | None] = mapped_column(Nutrient)
    sugars_100g: Mapped[float | None] = mapped_column(Nutrient)
    fiber_100g: Mapped[float | None] = mapped_column(Nutrient)

    salt_100g: Mapped[float | None] = mapped_column(Nutrient)
    sodium_100g: Mapped[float | None] = mapped_column(Nutrient)
    cholesterol_100g: Mapped[float | None] = mapped_column(Nutrient)

    ingredients_text: Mapped[str | None] = mapped_column(Text)
    allergens_text: Mapped[str | None] = mapped_column(Text)
    traces_text: Mapped[str | None] = mapped_column(Text)

    nutriscore_grade: Mapped[str | None] = mapped_column(String(5))
    nutriscore_score: Mapped[int | None] = mapped_column(Integer)
    nova_group: Mapped[int | None] = mapped_column(SmallInteger)

    additives_count: Mapped[int | None] = mapped_column(Integer)

    image_url: Mapped[str | None] = mapped_column(Text)
    image_front_url: Mapped[str | None] = mapped_column(Text)
    image_nutrition_url: Mapped[str | None] = mapped_column(Text)
    image_ingredients_url: Mapped[str | None] = mapped_column(Text)

    source: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)

    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    obsolete: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    source_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    raw_data: Mapped[dict | None] = mapped_column(JSONB, deferred=True)

    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(SEARCH_VECTOR_SQL, persisted=True),
        deferred=True,
    )

    nutrients: Mapped[list["FoodNutrient"]] = relationship(
        back_populates="food",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_foods_source_source_id"),
        Index("ix_foods_barcode", "barcode"),
        Index("ix_foods_source", "source"),
        Index("ix_foods_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_foods_countries", "countries", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        return f"<Food id={self.id} name={self.name!r} source={self.source}>"


class FoodNutrient(Base):
    __tablename__ = "food_nutrients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    food_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("foods.id", ondelete="CASCADE"),
        nullable=False,
    )

    nutrient_code: Mapped[str] = mapped_column(String(100), nullable=False)
    nutrient_name: Mapped[str | None] = mapped_column(String(150))

    amount_100g: Mapped[float | None] = mapped_column(Nutrient)
    amount_serving: Mapped[float | None] = mapped_column(Nutrient)

    unit: Mapped[str | None] = mapped_column(String(20))

    food: Mapped[Food] = relationship(back_populates="nutrients")

    __table_args__ = (
        UniqueConstraint("food_id", "nutrient_code", name="uq_food_nutrients_food_code"),
        Index("ix_food_nutrients_code", "nutrient_code"),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    firebase_uid: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    username: Mapped[str | None] = mapped_column(String(50), unique=True)
    email: Mapped[str | None] = mapped_column(Text)

    display_name: Mapped[str | None] = mapped_column(Text)

    birth_date: Mapped[date | None] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(String(20))

    height_cm: Mapped[float | None] = mapped_column(Numeric(5, 2, asdecimal=False))

    activity_level: Mapped[str | None] = mapped_column(String(30))
    goal: Mapped[str | None] = mapped_column(String(30))

    calorie_target: Mapped[int | None] = mapped_column(Integer)
    protein_target: Mapped[float | None] = mapped_column(Nutrient)
    carbs_target: Mapped[float | None] = mapped_column(Nutrient)
    fat_target: Mapped[float | None] = mapped_column(Nutrient)

    unit_system: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default=UnitSystem.METRIC.value,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            f"sex IS NULL OR {sql_check('sex', Sex)}",
            name="ck_users_sex",
        ),
        CheckConstraint(
            f"activity_level IS NULL OR {sql_check('activity_level', ActivityLevel)}",
            name="ck_users_activity_level",
        ),
        CheckConstraint(
            f"goal IS NULL OR {sql_check('goal', GoalType)}",
            name="ck_users_goal",
        ),
        CheckConstraint(sql_check("unit_system", UnitSystem), name="ck_users_unit_system"),
        CheckConstraint(
            "height_cm IS NULL OR (height_cm > 0 AND height_cm < 300)",
            name="ck_users_height_cm",
        ),
        CheckConstraint(
            "calorie_target IS NULL OR calorie_target > 0",
            name="ck_users_calorie_target",
        ),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} firebase_uid={self.firebase_uid!r}>"


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)

    goal: Mapped[str | None] = mapped_column(String(30))

    calorie_target: Mapped[int | None] = mapped_column(Integer)
    protein_target: Mapped[float | None] = mapped_column(Nutrient)
    carbs_target: Mapped[float | None] = mapped_column(Nutrient)
    fat_target: Mapped[float | None] = mapped_column(Nutrient)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "effective_from", name="uq_goals_user_effective_from"),
        CheckConstraint(
            f"goal IS NULL OR {sql_check('goal', GoalType)}",
            name="ck_goals_goal",
        ),
        Index("ix_goals_user_effective_from", "user_id", "effective_from"),
    )


class CustomFood(Base):
    __tablename__ = "custom_foods"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(Text)
    barcode: Mapped[str | None] = mapped_column(String(32))

    serving_size_text: Mapped[str | None] = mapped_column(Text)
    serving_quantity: Mapped[float | None] = mapped_column(Nutrient)
    serving_unit: Mapped[str | None] = mapped_column(String(20))

    energy_kcal_100g: Mapped[float | None] = mapped_column(Nutrient)
    protein_100g: Mapped[float | None] = mapped_column(Nutrient)
    carbs_100g: Mapped[float | None] = mapped_column(Nutrient)
    fat_100g: Mapped[float | None] = mapped_column(Nutrient)

    saturated_fat_100g: Mapped[float | None] = mapped_column(Nutrient)
    sugars_100g: Mapped[float | None] = mapped_column(Nutrient)
    fiber_100g: Mapped[float | None] = mapped_column(Nutrient)
    salt_100g: Mapped[float | None] = mapped_column(Nutrient)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_custom_foods_user_id", "user_id"),
        Index("ix_custom_foods_user_name", "user_id", "name"),
    )


class Meal(Base):
    __tablename__ = "meals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    items: Mapped[list["MealItem"]] = relationship(
        back_populates="meal",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="MealItem.position",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_meals_user_name"),
        Index("ix_meals_user_id", "user_id"),
    )


class MealItem(Base):
    __tablename__ = "meal_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    meal_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("meals.id", ondelete="CASCADE"),
        nullable=False,
    )

    food_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("foods.id", ondelete="RESTRICT"),
    )
    custom_food_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("custom_foods.id", ondelete="CASCADE"),
    )

    quantity_g: Mapped[float] = mapped_column(Nutrient, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    meal: Mapped[Meal] = relationship(back_populates="items")
    food: Mapped[Food | None] = relationship(lazy="joined")
    custom_food: Mapped[CustomFood | None] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint(ONE_FOOD_REFERENCE, name="ck_meal_items_one_food_reference"),
        CheckConstraint("quantity_g > 0", name="ck_meal_items_quantity_g"),
        Index("ix_meal_items_meal_id", "meal_id"),
    )


class DiaryEntry(Base):
    __tablename__ = "diary_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    food_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("foods.id", ondelete="RESTRICT"),
    )
    custom_food_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("custom_foods.id", ondelete="CASCADE"),
    )

    entry_date: Mapped[date] = mapped_column("date", Date, nullable=False)
    meal: Mapped[str] = mapped_column(String(20), nullable=False)

    quantity_g: Mapped[float] = mapped_column(Nutrient, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    food: Mapped[Food | None] = relationship(lazy="joined")
    custom_food: Mapped[CustomFood | None] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint(ONE_FOOD_REFERENCE, name="ck_diary_entries_one_food_reference"),
        CheckConstraint("quantity_g > 0", name="ck_diary_entries_quantity_g"),
        CheckConstraint(sql_check("meal", MealKey), name="ck_diary_entries_meal"),
        Index("ix_diary_entries_user_date", "user_id", "date"),
    )


class Weight(Base):
    __tablename__ = "weights"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    entry_date: Mapped[date] = mapped_column("date", Date, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Numeric(6, 2, asdecimal=False), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_weights_user_date"),
        CheckConstraint(
            "weight_kg > 0 AND weight_kg < 1000",
            name="ck_weights_weight_kg",
        ),
        Index("ix_weights_user_date", "user_id", "date"),
    )


class Favorite(Base):
    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    food_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("foods.id", ondelete="CASCADE"),
    )
    custom_food_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("custom_foods.id", ondelete="CASCADE"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    food: Mapped[Food | None] = relationship(lazy="joined")
    custom_food: Mapped[CustomFood | None] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint(ONE_FOOD_REFERENCE, name="ck_favorites_one_food_reference"),
        UniqueConstraint("user_id", "food_id", name="uq_favorites_user_food"),
        UniqueConstraint("user_id", "custom_food_id", name="uq_favorites_user_custom_food"),
        Index("ix_favorites_user_id", "user_id"),
    )
