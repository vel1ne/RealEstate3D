from sqlalchemy.orm import Session

from app.models.property import Property
from app.repositories.property import PropertyRepository
from app.repositories.property_type import PropertyTypeRepository
from app.schemas.property import PropertyCreate, PropertyUpdate
from app.services.property_type import PropertyTypeNotFoundError


class PropertyNotFoundError(Exception):
    pass


class PropertyService:
    def __init__(self, db: Session) -> None:
        self.repository = PropertyRepository(db)
        self.type_repository = PropertyTypeRepository(db)

    def get_all_properties(self) -> list[Property]:
        return self.repository.get_all()

    def get_property(self, property_id: str) -> Property:
        property_obj = self.repository.get_by_id(property_id)

        if property_obj is None:
            raise PropertyNotFoundError(
                f"Объект недвижимости с ID {property_id} не найден"
            )

        return property_obj

    def create_property(self, data: PropertyCreate) -> Property:
        if self.type_repository.get_by_id(data.property_type_id) is None:
            raise PropertyTypeNotFoundError("Property type not found")
        
        return self.repository.create(data)

    def update_property(
        self,
        property_id: str,
        data: PropertyUpdate,
    ) -> Property:
        property_obj = self.get_property(property_id)
        return self.repository.update(property_obj, data)

    def delete_property(self, property_id: str) -> None:
        property_obj = self.get_property(property_id)
        self.repository.delete(property_obj)
