from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


if TYPE_CHECKING:
    from app.models.property_filter_value import PropertyFilterValue
    from app.models.property_type import PropertyType


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    address: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    property_type_id: Mapped[str] = mapped_column(
        ForeignKey("property_types.id"),
        nullable=False,
    )

    property_type: Mapped["PropertyType"] = relationship(
        back_populates="properties",
    )
    filter_values: Mapped[list["PropertyFilterValue"]] = relationship(
        back_populates="property",
        cascade="all, delete-orphan",
    )