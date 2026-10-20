from enum import StrEnum


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    UNSPECIFIED = "unspecified"


class ActivityLevel(StrEnum):
    SEDENTARY = "sedentary"
    LIGHT = "light"
    MODERATE = "moderate"
    ACTIVE = "active"
    VERY_ACTIVE = "very_active"


class GoalType(StrEnum):
    LOSE_WEIGHT = "lose_weight"
    MAINTAIN = "maintain"
    GAIN_WEIGHT = "gain_weight"
    GAIN_MUSCLE = "gain_muscle"


class UnitSystem(StrEnum):
    METRIC = "metric"
    IMPERIAL = "imperial"


class MealKey(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACKS = "snacks"


def values(enum: type[StrEnum]) -> list[str]:
    return [member.value for member in enum]


def sql_check(column: str, enum: type[StrEnum]) -> str:
    allowed = ", ".join(f"'{value}'" for value in values(enum))

    return f"{column} IN ({allowed})"
