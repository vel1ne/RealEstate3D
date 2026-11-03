from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.property import Property
from app.schemas.property import PropertyCreate, PropertyUpdate


class PropertyRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_all(self) -> list[Property]:
        statement = select(Property).order_by(Property.created_at.desc())
        return list(self.db.scalars(statement).all())

    def get_by_id(self, property_id: str) -> Property | None:
        return self.db.get(Property, property_id)

    def create(self, data: PropertyCreate) -> Property:
        property_obj = Property(**data.model_dump())

        self.db.add(property_obj)
        self.db.commit()
        self.db.refresh(property_obj)

        return property_obj

    def update(
        self,
        property_obj: Property,
        data: PropertyUpdate,
    ) -> Property:
        update_data = data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(property_obj, field, value)

        self.db.commit()
        self.db.refresh(property_obj)

        return property_obj

    def delete(self, property_obj: Property) -> None:
        self.db.delete(property_obj)
        self.db.commit()
