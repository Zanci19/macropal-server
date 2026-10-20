from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.models import Food, FoodNutrient

SAMPLES = [
    {
        "barcode": "123456789",
        "name": "Test Chocolate",
        "brand": "MacroPal Test",
        "category": "Chocolate bars",
        "language": "en",
        "countries": ["slovenia"],
        "serving_size_text": "25 g",
        "serving_quantity": 25,
        "serving_unit": "g",
        "energy_kcal_100g": 550,
        "energy_kj_100g": 2301,
        "protein_100g": 7,
        "carbs_100g": 55,
        "fat_100g": 35,
        "saturated_fat_100g": 21,
        "sugars_100g": 50,
        "fiber_100g": 3.5,
        "salt_100g": 0.12,
        "sodium_100g": 0.048,
        "nutriscore_grade": "e",
        "nutriscore_score": 24,
        "nova_group": 4,
        "additives_count": 2,
        "ingredients_text": "Sugar, cocoa butter, cocoa mass, milk powder, emulsifier.",
        "allergens_text": "milk, soy",
        "source": "macropal",
        "source_id": "test-chocolate",
        "verified": True,
    },
    {
        "name": "Chicken breast, raw",
        "category": "Poultry",
        "food_group": "Meat",
        "language": "en",
        "energy_kcal_100g": 120,
        "energy_kj_100g": 502,
        "protein_100g": 22.5,
        "carbs_100g": 0,
        "fat_100g": 2.6,
        "saturated_fat_100g": 0.7,
        "sugars_100g": 0,
        "salt_100g": 0.17,
        "sodium_100g": 0.068,
        "cholesterol_100g": 0.073,
        "source": "macropal",
        "source_id": "chicken-breast-raw",
        "verified": True,
    },
]

MICRONUTRIENTS = {
    "chicken-breast-raw": [
        {"nutrient_code": "potassium", "nutrient_name": "Potassium", "amount_100g": 0.334, "unit": "g"},
        {"nutrient_code": "iron", "nutrient_name": "Iron", "amount_100g": 0.0004, "unit": "g"},
        {"nutrient_code": "vitamin-b6", "nutrient_name": "Vitamin B6", "amount_100g": 0.0006, "unit": "g"},
    ],
}


def main() -> None:
    with SessionLocal() as db:
        for row in SAMPLES:
            statement = (
                insert(Food)
                .values(**row)
                .on_conflict_do_update(
                    constraint="uq_foods_source_source_id",
                    set_={key: value for key, value in row.items() if key != "source"},
                )
                .returning(Food.id, Food.source_id)
            )
            food_id, source_id = db.execute(statement).one()

            for nutrient in MICRONUTRIENTS.get(source_id, []):
                db.execute(
                    insert(FoodNutrient)
                    .values(food_id=food_id, **nutrient)
                    .on_conflict_do_update(
                        constraint="uq_food_nutrients_food_code",
                        set_=nutrient,
                    )
                )

            print(f"upserted food id={food_id} source_id={source_id}")

        db.commit()


if __name__ == "__main__":
    main()
