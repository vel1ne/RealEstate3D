from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.property_filter import PropertyFilter
from app.schemas.property_filter import PropertyFilterCreate, PropertyFilterUpdate


class PropertyFilterRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, filter_id: str) -> PropertyFilter | None:
        return self.db.get(PropertyFilter, filter_id)

    def get_by_property_type_id(
        self,
        property_type_id: str,
    ) -> list[PropertyFilter]:
        statement = select(PropertyFilter).where(
            PropertyFilter.property_type_id == property_type_id
        )
        return list(self.db.scalars(statement).all())

    def create(self, data: PropertyFilterCreate) -> PropertyFilter:
        property_filter = PropertyFilter(**data.model_dump())

        self.db.add(property_filter)

        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise

        self.db.refresh(property_filter)

        return property_filter

    def update(
        self,
        property_filter: PropertyFilter,
        data: PropertyFilterUpdate,
    ) -> PropertyFilter:
        update_data = data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(property_filter, field, value)

        self.db.commit()
        self.db.refresh(property_filter)

        return property_filter

    def delete(self, property_filter: PropertyFilter) -> None:
        self.db.delete(property_filter)
        self.db.commit()

    def get_by_slug(
        self,
        slug: str,
        property_type_id: str,
    ) -> PropertyFilter | None:
        statement = select(PropertyFilter).where(
            PropertyFilter.slug == slug,
            PropertyFilter.property_type_id == property_type_id,
        )
        return self.db.scalar(statement)

    def get_by_name(
        self,
        name: str,
        property_type_id: str,
    ) -> PropertyFilter | None:
        statement = select(PropertyFilter).where(
            PropertyFilter.name == name,
            PropertyFilter.property_type_id == property_type_id,
        )
        return self.db.scalar(statement)
