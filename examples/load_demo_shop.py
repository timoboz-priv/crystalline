"""End-to-end smoke test: load a disposable copy of the demo project and
print its properties.

Copies `examples/demo_shop/project.yaml` into a temporary directory
before loading it, specifically so this never opens/writes the user's own
live `examples/demo_shop/demo_shop.db` — see CLAUDE.md's "never touch
examples/demo_shop/ for ad hoc/live testing" rule. Only `project.yaml`
itself is read directly; the copy gets its own throwaway `demo_shop.db`
next to it instead.

Run with:
    python examples/load_demo_shop.py
"""

import shutil
import tempfile
from pathlib import Path

from crystalline.project import describe_project, load_project

PROJECT_PATH = Path(__file__).parent / "demo_shop" / "project.yaml"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        copy_path = Path(tmp_dir) / "project.yaml"
        shutil.copy(PROJECT_PATH, copy_path)
        project = load_project(copy_path)
        try:
            print(describe_project(project))
        finally:
            project.storage.close()


if __name__ == "__main__":
    main()
