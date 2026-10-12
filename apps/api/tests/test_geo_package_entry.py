"""Product packaging must serve UI without weakening API authentication."""
import runpy
from pathlib import Path
import pytest
from starlette.testclient import TestClient


def test_ui_mount_keeps_authenticated_api_and_lifecycle(tmp_path, monkeypatch):
    (tmp_path / 'index.html').write_text('<html>GEO package UI</html>')
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets/app.js').write_text('window.geo=true')
    monkeypatch.setenv('GEO_UI_DIR', str(tmp_path))
    monkeypatch.setenv('GEO_AUTH_MODE', 'auth_context')
    monkeypatch.setenv('GEO_PRODUCT_DOOR', 'on')
    monkeypatch.setenv('GEO_RUNTIME_MODE', 'baseline')
    from app.main import app as api
    calls=[]
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def lifecycle(_app):
        calls.append('startup')
        yield
        calls.append('shutdown')
    monkeypatch.setattr(api.router, 'lifespan_context', lifecycle)
    entry=runpy.run_path(str(Path(__file__).resolve().parents[3] / 'docker/serve.py'))
    with TestClient(entry['app']) as client:
        assert client.get('/product/geo/').status_code == 200
        assert client.get('/product/geo/assets/app.js').text == 'window.geo=true'
        assert client.get('/api/product/geo/health').status_code == 401
        assert client.get('/api/product/geo/knowledge/materials').status_code == 401
        assert client.get('/product/geo/../../api/product/geo/health').status_code != 200
    assert calls == ['startup', 'shutdown']


def test_missing_ui_refuses_startup(tmp_path, monkeypatch):
    monkeypatch.setenv('GEO_UI_DIR', str(tmp_path))
    with pytest.raises(RuntimeError, match='UI artifact is missing'):
        runpy.run_path(str(Path(__file__).resolve().parents[3] / 'docker/serve.py'))
