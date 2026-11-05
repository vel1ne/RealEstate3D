from uuid import uuid4
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.property_type import PropertyType
    from app.models.property_filter_value import PropertyFilterValue


class PropertyFilter(Base):
    __tablename__ = "property_filters"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    slug: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    filter_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    is_required: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    property_type_id: Mapped[str] = mapped_column(
        ForeignKey("property_types.id"),
        nullable=False,
    )

    property_type: Mapped["PropertyType"] = relationship(
        back_populates="filters",
    )
    values: Mapped[list["PropertyFilterValue"]] = relationship(
        back_populates="property_filter",
        cascade="all, delete-orphan",
    )