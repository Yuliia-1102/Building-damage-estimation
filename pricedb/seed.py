"""Load initial data into the database (epic 5.2). Safe to run repeatedly."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import seed_data
from .models import DamageClass, Material, Price, WorkMaterial, WorkType


def _get_or_create_material(session: Session, name: str, unit: str) -> Material:
    material = session.scalar(select(Material).where(Material.name == name))
    if material is None:
        material = Material(name=name, unit=unit)
        session.add(material)
        session.flush()
    return material


def load_seed(session: Session) -> None:
    materials = {
        name: _get_or_create_material(session, name, unit)
        for name, unit in seed_data.MATERIALS.items()
    }

    for name, material in materials.items():
        if session.scalar(select(Price).where(
                Price.material_id == material.id,
                Price.valid_from == seed_data.PRICE_DATE)) is None:
            source, url = seed_data.SOURCES.get(name, (seed_data.DEFAULT_SOURCE, None))
            session.add(Price(material=material, value=seed_data.PRICES[name],
                              currency="UAH", valid_from=seed_data.PRICE_DATE,
                              source=source, source_url=url))

    classes = {c.code: c for c in session.scalars(select(DamageClass))}
    for code, (name, class_code, used) in seed_data.WORKS.items():
        work = session.scalar(select(WorkType).where(WorkType.code == code))
        if work is None:
            work = WorkType(code=code, name=name, unit="m2",
                            damage_class=classes[class_code])
            session.add(work)
            session.flush()
        for material_name, qty in used.items():
            if session.get(WorkMaterial, (work.id, materials[material_name].id)) is None:
                session.add(WorkMaterial(work_type=work, material=materials[material_name],
                                        quantity_per_unit=qty))

    session.commit()
