"""Shared repository facade for non-HTTP services.

All service code uses the same SQLAlchemy Store as the API. This avoids a
second sqlite3 implementation with different transaction semantics.
"""
from app.services.store import current_tenant, get_store


def current_tenant_or_default() -> str:
    return current_tenant()


def load_table(table: str) -> list[dict]:
    store = get_store()
    try:
        return store.load(table)
    finally:
        store.db.close()


def save_table(table: str, items: list[dict]) -> None:
    store = get_store()
    try:
        store.save(table, items)
    finally:
        store.db.close()
