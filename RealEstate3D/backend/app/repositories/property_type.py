from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.property_type import PropertyType
from app.schemas.property_type import PropertyTypeCreate, PropertyTypeUpdate


class PropertyTypeRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_all(self) -> list[PropertyType]:
        statement = select(PropertyType)
        return list(self.db.scalars(statement).all())

    def get_by_id(self, property_type_id: str) -> PropertyType | None:
        return self.db.get(PropertyType, property_type_id)

    def get_by_slug(self, slug: str) -> PropertyType | None:
        statement = select(PropertyType).where(PropertyType.slug == slug)
        return self.db.scalar(statement)

    def get_by_name(self, name: str) -> PropertyType | None:
        statement = select(PropertyType).where(PropertyType.name == name)
        return self.db.scalar(statement)

    def create(self, data: PropertyTypeCreate) -> PropertyType:
        property_type = PropertyType(**data.model_dump())

        self.db.add(property_type)
        self.db.commit()
        self.db.refresh(property_type)

        return property_type

    def update(
        self,
        property_type: PropertyType,
        data: PropertyTypeUpdate,
    ) -> PropertyType:
        update_data = data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(property_type, field, value)

        self.db.commit()
        self.db.refresh(property_type)

        return property_type

    def delete(self, property_type: PropertyType) -> None:
        self.db.delete(property_type)
        self.db.commit()
