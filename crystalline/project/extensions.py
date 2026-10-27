"""Discovering and loading hand-written tool/skill files from a
project's extensions directory.

Tools auto-generated from schema (`crystalline.tools.crud`/`admin`) have
nothing custom to configure; skills never had an auto-generation path to
begin with. Both are extended by dropping files into one directory,
declared in the project file:

    extensions: path/to/dir   # resolved relative to the project file

Convention: one tool or skill per file, named `tool_*.py` / `skill_*.py`.
A `tool_*.py` file needs a `build_tool(project) -> Tool` function; a
`skill_*.py` file needs `build_skill(project) -> Skill`. Each returns
exactly one object — there's no "register several things from one file"
escape hatch, so a project's extensions directory listing *is* the list
of its custom tools/skills, one file per capability.

`load_project` resolves `extensions:` (relative to the project file's own
directory, like `storage.path`) via `resolve_extensions_dir` and stores
it on `Project.extensions_dir` as plain data — it does **not** scan or
execute anything. Parsing a project file should never run arbitrary code
as a side effect. `apply_extensions(project)` is the explicit step that
actually discovers and imports the files; the CLI calls it automatically
right after `load_project` (and again on `/reload`), since by the time
something is about to run a project at all, it already trusts it with far
more than "also run the Python files it points to."
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from .project import Project


def resolve_extensions_dir(value: str | None, base_dir: Path | None) -> str | None:
    """Resolve a project file's `extensions:` value against `base_dir`
    (the project file's own directory), same convention as `storage.path`."""
    if value is None:
        return None
    candidate = Path(value)
    if base_dir is not None and not candidate.is_absolute():
        candidate = base_dir / candidate
    return str(candidate)


def _module_name(path: Path) -> str:
    # Qualified by the file's resolved absolute path (hashed, since a
    # module name can't contain path separators), not just its bare
    # stem — two different projects' extension files sharing a filename
    # (or a test suite reusing names like `tool_answer.py`) would
    # otherwise collide in `sys.modules`, corrupting Pydantic forward-
    # reference resolution for whichever one lost the race. Loading the
    # *same* file again (e.g. on `/reload`) reuses the same name on
    # purpose, so its `sys.modules` entry is replaced, not duplicated.
    digest = hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:16]
    return f"crystalline_extensions.{path.stem}_{digest}"


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(_module_name(path), path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load a Python module from {path}")
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules *before* executing it, not just after —
    # otherwise Pydantic models in the file that reference each other by
    # name (e.g. under `from __future__ import annotations`) can fail to
    # resolve, since Pydantic looks forward references up via
    # sys.modules[model.__module__].
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_tool_file(path: Path, project: Project) -> None:
    module = _load_module(path)
    build_tool = getattr(module, "build_tool", None)
    if build_tool is None:
        raise AttributeError(f"{path} does not define a build_tool(project) function")
    project.tools.add_tool(build_tool(project), replace=True)


def load_skill_file(path: Path, project: Project) -> None:
    module = _load_module(path)
    build_skill = getattr(module, "build_skill", None)
    if build_skill is None:
        raise AttributeError(f"{path} does not define a build_skill(project) function")
    project.skills.add_tool(build_skill(project), replace=True)


def apply_extensions(project: Project) -> None:
    """Discover and (re)load every `tool_*.py`/`skill_*.py` file in
    `project.extensions_dir` (a no-op if it's unset). Safe to call more
    than once on the same project — each file's tool/skill is replaced,
    not duplicated — which is what makes `/reload` work.
    """
    if project.extensions_dir is None:
        return
    directory = Path(project.extensions_dir)
    if not directory.is_dir():
        raise NotADirectoryError(
            f"extensions directory not found: {project.extensions_dir}"
        )
    for path in sorted(directory.glob("tool_*.py")):
        load_tool_file(path, project)
    for path in sorted(directory.glob("skill_*.py")):
        load_skill_file(path, project)
