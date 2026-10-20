from dataclasses import dataclass, replace

from app.models import CustomFood, Food


@dataclass(frozen=True, slots=True)
class Macros:
    calories: float = 0.0
    protein: float = 0.0
    carbs: float = 0.0
    fat: float = 0.0

    def __add__(self, other: "Macros") -> "Macros":
        return Macros(
            calories=self.calories + other.calories,
            protein=self.protein + other.protein,
            carbs=self.carbs + other.carbs,
            fat=self.fat + other.fat,
        )

    def rounded(self) -> "Macros":
        return replace(
            self,
            calories=round(self.calories),
            protein=round(self.protein, 1),
            carbs=round(self.carbs, 1),
            fat=round(self.fat, 1),
        )


EMPTY = Macros()


def scale(item: Food | CustomFood | None, quantity_g: float | None) -> Macros:
    if item is None or not quantity_g:
        return EMPTY

    factor = float(quantity_g) / 100.0

    return Macros(
        calories=(item.energy_kcal_100g or 0.0) * factor,
        protein=(item.protein_100g or 0.0) * factor,
        carbs=(item.carbs_100g or 0.0) * factor,
        fat=(item.fat_100g or 0.0) * factor,
    )


def total(macros: list[Macros]) -> Macros:
    return sum(macros, EMPTY)
