"""Application-owned lifecycle for GEO Product PostgreSQL connections."""
from __future__ import annotations

import os

from sqlalchemy import create_engine

from app.product.http_auth import auth_context_mode_enabled, product_storage_ready
from app.product.runtime.monitor_run import ProductRuntimeUnavailable


def start_product_database(app) -> None:
    """Create exactly one shared engine for strict Product runtime mode."""
    if not (auth_context_mode_enabled() and product_storage_ready()):
        return
    if getattr(app.state, "product_database_engine", None) is not None:
        return
    url = os.environ.get("GEO_PRODUCT_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        raise ProductRuntimeUnavailable("strict Product runtime requires GEO_PRODUCT_DATABASE_URL PostgreSQL configuration")
    app.state.product_database_engine = create_engine(url, pool_pre_ping=True)


def stop_product_database(app) -> None:
    engine = getattr(app.state, "product_database_engine", None)
    if engine is not None:
        engine.dispose()
        delattr(app.state, "product_database_engine")
