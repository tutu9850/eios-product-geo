"""Serve GEO-owned UI bytes and the existing authenticated API on one product upstream."""
from contextlib import asynccontextmanager
import os
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from app.main import app as api

ui_dir = Path(os.environ["GEO_UI_DIR"])
if not (ui_dir / "index.html").is_file():
    raise RuntimeError("GEO UI artifact is missing")
# Static bytes are public like the existing Product Host assets. Every API path
# still enters app.main and its existing AuthContext/PDP/product-door middleware.
@asynccontextmanager
async def lifespan(_app):
    async with api.router.lifespan_context(api):
        yield

app = Starlette(routes=[Mount("/product/geo", StaticFiles(directory=ui_dir, html=True)), Mount("/", api)], lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8091, access_log=False)
