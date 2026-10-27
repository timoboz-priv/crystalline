"""examples/load_demo_shop.py must never open/write the user's own live
examples/demo_shop/demo_shop.db — it's a smoke-test script, not something
that should interfere with the demo project the user plays with by hand
(see CLAUDE.md's "never touch examples/demo_shop/" rule)."""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "examples" / "load_demo_shop.py"
LIVE_DB_PATH = REPO_ROOT / "examples" / "demo_shop" / "demo_shop.db"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("load_demo_shop", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_does_not_touch_the_live_demo_db(capsys):
    db_existed_before = LIVE_DB_PATH.exists()
    mtime_before = LIVE_DB_PATH.stat().st_mtime if db_existed_before else None

    module = _load_script_module()
    module.main()

    assert "demo-shop" in capsys.readouterr().out
    assert LIVE_DB_PATH.exists() == db_existed_before
    if db_existed_before:
        assert LIVE_DB_PATH.stat().st_mtime == mtime_before
