from typing import Any, TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.property import Property
    from app.models.property_filter import PropertyFilter


class PropertyFilterValue(Base):
    __tablename__ = "property_filter_values"

    __table_args__ = (
        UniqueConstraint(
            "property_id",
            "property_filter_id",
            name="uq_property_filter_value",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    value: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
    )

    property_id: Mapped[str] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
    )

    property_filter_id: Mapped[str] = mapped_column(
        ForeignKey("property_filters.id", ondelete="CASCADE"),
        nullable=False,
    )

    property: Mapped["Property"] = relationship(
        back_populates="filter_values",
    )

    property_filter: Mapped["PropertyFilter"] = relationship(
        back_populates="values",
    )