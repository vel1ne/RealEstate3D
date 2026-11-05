from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import PropertyType


PROPERTY_TYPES = [
    {
        "name": "Торговое помещение",
        "slug": "retail",
        "description": "Помещения для розничной торговли.",
    },
    {
        "name": "Офис",
        "slug": "office",
        "description": "Помещения для офисной деятельности.",
    },
    {
        "name": "Склад",
        "slug": "warehouse",
        "description": "Помещения для хранения товаров.",
    },
    {
        "name": "Общественное питание",
        "slug": "food-service",
        "description": "Помещения для кафе и ресторанов.",
    },
    {
        "name": "Производственное помещение",
        "slug": "industrial",
        "description": "Помещения для производственной деятельности.",
    },
    {
        "name": "Помещение свободного назначения",
        "slug": "free-purpose",
        "description": "Помещения для различных видов коммерческой деятельности.",
    },
]


def seed_property_types() -> None:
    with SessionLocal.begin() as db:
        for property_type_data in PROPERTY_TYPES:
            statement = select(PropertyType).where(
                PropertyType.slug == property_type_data["slug"]
            )

            existing_type = db.scalar(statement)

            if existing_type is None:
                db.add(PropertyType(**property_type_data))

    print("Property types seeded successfully!")


if __name__ == "__main__":
    seed_property_types()