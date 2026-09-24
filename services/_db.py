"""Deprecated compatibility facade; use services.repository."""
from services.repository import current_tenant_or_default, load_table, save_table

__all__ = ["current_tenant_or_default", "load_table", "save_table"]
