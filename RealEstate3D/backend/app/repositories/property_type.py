from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.property_type import PropertyType


class PropertyTypeRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_all(self) -> list[PropertyType]:
        query = select(PropertyType)
        return list(self.db.scalars(query).all())

    def get_by_slug(self, slug: str) -> PropertyType | None:
        query = select(PropertyType).where(PropertyType.slug == slug)
        return self.db.scalar(query)