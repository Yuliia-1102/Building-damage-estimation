"""Materials database schema (epic 5).

    damage_class 1 ── N work_type N ── M material 1 ── N price
                               (work_material)

work_type.code matches core.reference.WORK_TYPES codes, so the decision layer and
the price source speak the same language.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import (
    CheckConstraint, Date, Float, ForeignKey, Index, String, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class DamageClass(Base):
    """Damaged segmentation classes that have a repair cost (3, 4, 5). Linked by `code`."""
    __tablename__ = "damage_class"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))

    work_types: Mapped[list[WorkType]] = relationship(back_populates="damage_class")

    def __repr__(self) -> str:
        return f"DamageClass({self.code!r})"


class WorkType(Base):
    """A repair work. `code` equals a core.reference.WORK_TYPES code."""
    __tablename__ = "work_type"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(20))  # m2 for every work type
    damage_class_id: Mapped[int] = mapped_column(
        ForeignKey("damage_class.id", ondelete="RESTRICT")
    )

    damage_class: Mapped[DamageClass] = relationship(back_populates="work_types")
    materials: Mapped[list[WorkMaterial]] = relationship(
        back_populates="work_type", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("idx_work_type_damage_class", "damage_class_id"),)

    def __repr__(self) -> str:
        return f"WorkType({self.code!r})"


class Material(Base):
    """A material bought for repairs."""
    __tablename__ = "material"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    unit: Mapped[str] = mapped_column(String(20))  # kg, l, m2, m, pcs

    used_in: Mapped[list[WorkMaterial]] = relationship(back_populates="material")
    prices: Mapped[list[Price]] = relationship(
        back_populates="material", order_by="Price.valid_from"
    )

    def __repr__(self) -> str:
        return f"Material({self.name!r})"


class WorkMaterial(Base):
    """M:N link: how much material one unit (1 m2) of work consumes."""
    __tablename__ = "work_material"

    work_type_id: Mapped[int] = mapped_column(
        ForeignKey("work_type.id", ondelete="CASCADE"), primary_key=True
    )
    material_id: Mapped[int] = mapped_column(
        ForeignKey("material.id", ondelete="RESTRICT"), primary_key=True
    )
    quantity_per_unit: Mapped[float] = mapped_column(Float)

    work_type: Mapped[WorkType] = relationship(back_populates="materials")
    material: Mapped[Material] = relationship(back_populates="used_in")

    __table_args__ = (
        CheckConstraint("quantity_per_unit > 0", name="ck_quantity_positive"),
    )


class Price(Base):
    """One dated price for a material. Rows are only ever inserted."""
    __tablename__ = "price"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(
        ForeignKey("material.id", ondelete="RESTRICT")
    )
    value: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="UAH")
    valid_from: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(String(500))

    material: Mapped[Material] = relationship(back_populates="prices")

    __table_args__ = (
        UniqueConstraint("material_id", "valid_from", name="uq_price_per_date"),
        CheckConstraint("value >= 0", name="ck_price_non_negative"),
        Index("idx_price_lookup", "material_id", "valid_from"),
    )

    def __repr__(self) -> str:
        return f"Price({self.value} {self.currency} {self.valid_from})"
