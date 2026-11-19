from sqlalchemy.exc import IntegrityError

from app.models.property_filter import PropertyFilter
from app.repositories.property_filter import PropertyFilterRepository
from app.repositories.property_type import PropertyTypeRepository
from app.schemas.property_filter import PropertyFilterCreate, PropertyFilterUpdate
from app.services.property_type import PropertyTypeNotFoundError


class PropertyFilterNotFoundError(Exception):
    pass


class PropertyFilterAlreadyExistsError(Exception):
    pass


class PropertyFilterInUseError(Exception):
    pass


class PropertyFilterService:
    def __init__(
        self,
        filter_repository: PropertyFilterRepository,
        type_repository: PropertyTypeRepository,
    ) -> None:
        self.filter_repository = filter_repository
        self.type_repository = type_repository

    def create(self, data: PropertyFilterCreate) -> PropertyFilter:
        property_type = self.type_repository.get_by_id(data.property_type_id)

        if property_type is None:
            raise PropertyTypeNotFoundError("Property type not found")

        existing_slug = self.filter_repository.get_by_slug(
            data.slug,
            data.property_type_id,
        )
        existing_name = self.filter_repository.get_by_name(
            data.name,
            data.property_type_id,
        )

        if existing_slug is not None or existing_name is not None:
            raise PropertyFilterAlreadyExistsError(
                "Filter with this name or slug already exists"
            )

        try:
            return self.filter_repository.create(data)
        except IntegrityError:
            raise PropertyFilterAlreadyExistsError(
                "Filter with this name or slug already exists"
            )

    def update(
        self,
        filter_id: str,
        data: PropertyFilterUpdate,
    ) -> PropertyFilter:
        property_filter = self.filter_repository.get_by_id(filter_id)

        if property_filter is None:
            raise PropertyFilterNotFoundError("Property filter not found")

        if data.slug is not None:
            existing_slug = self.filter_repository.get_by_slug(
                data.slug,
                property_filter.property_type_id,
            )

            if existing_slug is not None and existing_slug.id != filter_id:
                raise PropertyFilterAlreadyExistsError(
                    "Filter with this slug already exists"
                )

        if data.name is not None:
            existing_name = self.filter_repository.get_by_name(
                data.name,
                property_filter.property_type_id,
            )

            if existing_name is not None and existing_name.id != filter_id:
                raise PropertyFilterAlreadyExistsError(
                    "Filter with this name already exists"
                )

        return self.filter_repository.update(property_filter, data)

    def delete(self, filter_id: str) -> None:
        property_filter = self.filter_repository.get_by_id(filter_id)

        if property_filter is None:
            raise PropertyFilterNotFoundError("Property filter not found")

        if property_filter.values:
            raise PropertyFilterInUseError(
                "Cannot delete filter with associated property values"
            )

        self.filter_repository.delete(property_filter)
