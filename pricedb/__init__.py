"""Materials & prices database and its PriceSource implementation (epic 5)."""
from .admin import MaterialRow, add_material, list_materials_with_price, update_price
from .db import DAMAGE_CLASSES, create_db, get_engine, open_db, session_factory, sqlite_url
from .models import Base, DamageClass, Material, Price, WorkMaterial, WorkType
from .prices import get_price_as_of, price_history, set_price
from .seed import load_seed
from .source import CsvPriceSource, MaterialsDbPriceSource, export_csv

__all__ = [
    "Base", "DamageClass", "WorkType", "Material", "WorkMaterial", "Price",
    "DAMAGE_CLASSES", "create_db", "open_db", "get_engine", "session_factory", "sqlite_url",
    "get_price_as_of", "price_history", "set_price", "load_seed",
    "MaterialsDbPriceSource", "CsvPriceSource", "export_csv",
    "MaterialRow", "add_material", "list_materials_with_price", "update_price",
]