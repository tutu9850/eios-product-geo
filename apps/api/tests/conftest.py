"""每个测试进程都跑在自己的临时 GEO 库上。

GEO 的存储被**两条路**读：``app.models``（SQLAlchemy）与 ``services._db``（直连 sqlite3）。
两条路都在 **import 时**把 ``GEO_DB_PATH`` 读成常量，所以「谁先被 import」决定了它们指向哪：

* 单个模块跑（``pytest tests/test_store.py``）时，模块自己 setdefault 的 ``:memory:`` 先生效，
  两层一致，测试通过；
* 全套跑时 ``test_engines.py`` 先 import 了 ``services.*``，那条路已经把仓库里被跟踪的
  ``apps/geo.db`` 钉死了，于是**测试把行写进了 dev 库**；下一次跑读到的就是上一次留下的行，
  ``test_store`` 的三条精确计数断言随之失败（``assert 2 == 1`` 等）。

Owner 2026-09-13 的红线：dev 库不是草稿纸，跑一次就往里堆一份数据会让下一次验收不可信。
所以这里在任何测试模块被 import 之前把路径钉到一个临时文件，两层读同一个库；进程结束即删除。
显式设过 ``GEO_DB_PATH`` 的（CI / 定向复现）不被覆盖 —— 那是调用方的选择。
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP_DIR = Path(tempfile.mkdtemp(prefix="geo-pytest-"))
os.environ.setdefault("GEO_DB_PATH", str(_TMP_DIR / "geo-test.db"))


@pytest.fixture(autouse=True)
def _fresh_geo_db():
    """每个测试从**空库**开始。

    库以前是 ``:memory:``，而 ``:memory:`` 的内容随连接池销毁而消失 —— 那份「每个测试都是空的」
    语义是 test_store 的精确计数断言依赖的。换成临时文件后必须显式还回来，否则上一个测试的
    行会被下一个看到（``len(load('questions')) == 0`` 之类会变成运气）。

    删文件也要 dispose 引擎：连接池里握着的连接指向已被 unlink 的 inode，不清掉的话
    ``create_all()`` 会建在死文件上，而 ``services._db`` 又新开一个 —— 那就是这次的病根。
    """
    db_path = os.environ.get("GEO_DB_PATH", "")
    if db_path and db_path != ":memory:":
        Path(db_path).unlink(missing_ok=True)
        from app.models.geo_models import engine

        engine.dispose()
    yield


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001 - pytest hook signature
    shutil.rmtree(_TMP_DIR, ignore_errors=True)
