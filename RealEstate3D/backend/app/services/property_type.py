from app.models.property_type import PropertyType
from app.repositories.property_type import PropertyTypeRepository
from app.schemas.property_type import PropertyTypeCreate, PropertyTypeUpdate


class PropertyTypeNotFoundError(Exception):
    pass


class PropertyTypeAlreadyExistsError(Exception):
    pass


class PropertyTypeInUseError(Exception):
    pass


class PropertyTypeService:
    def __init__(self, repository: PropertyTypeRepository) -> None:
        self.repository = repository

    def get_all(self) -> list[PropertyType]:
        return self.repository.get_all()

    def get_by_slug(self, slug: str) -> PropertyType:
        property_type = self.repository.get_by_slug(slug)

        if property_type is None:
            raise PropertyTypeNotFoundError("Property type not found")

        return property_type

    def create(self, data: PropertyTypeCreate) -> PropertyType:
        existing_slug = self.repository.get_by_slug(data.slug)
        existing_name = self.repository.get_by_name(data.name)

        if existing_slug is not None:
            raise PropertyTypeAlreadyExistsError(
                "Property type with this slug already exists"
            )

        if existing_name is not None:
            raise PropertyTypeAlreadyExistsError(
                "Property type with this name already exists"
            )

        return self.repository.create(data)

    def update(
        self,
        property_type_id: str,
        data: PropertyTypeUpdate,
    ) -> PropertyType:
        property_type = self.repository.get_by_id(property_type_id)

        if property_type is None:
            raise PropertyTypeNotFoundError("Property type not found")

        if data.slug is not None:
            existing_slug = self.repository.get_by_slug(data.slug)

            if existing_slug is not None and existing_slug.id != property_type_id:
                raise PropertyTypeAlreadyExistsError(
                    "Property type with this slug already exists"
                )

        if data.name is not None:
            existing_name = self.repository.get_by_name(data.name)

            if existing_name is not None and existing_name.id != property_type_id:
                raise PropertyTypeAlreadyExistsError(
                    "Property type with this name already exists"
                )

        return self.repository.update(property_type, data)

    def delete(self, property_type_id: str) -> None:
        property_type = self.repository.get_by_id(property_type_id)

        if property_type is None:
            raise PropertyTypeNotFoundError("Property type not found")

        if property_type.properties or property_type.filters:
            raise PropertyTypeInUseError(
                "Cannot delete property type with associated properties or filters"
            )

        self.repository.delete(property_type)
