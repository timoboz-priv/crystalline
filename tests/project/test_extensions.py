from pathlib import Path

import pytest

from crystalline.project import (
    Project,
    apply_extensions,
    load_skill_file,
    load_tool_file,
    resolve_extensions_dir,
)


def test_resolve_extensions_dir_none():
    assert resolve_extensions_dir(None, Path("/base")) is None


def test_resolve_extensions_dir_relative():
    assert resolve_extensions_dir("extensions", Path("/base")) == str(Path("/base/extensions"))


def test_resolve_extensions_dir_absolute_untouched():
    absolute = str(Path("/elsewhere/extensions"))
    assert resolve_extensions_dir(absolute, Path("/base")) == absolute


def test_resolve_extensions_dir_no_base_dir_passthrough():
    assert resolve_extensions_dir("extensions", None) == "extensions"


def _write_tool_file(directory: Path, name: str = "tool_answer.py") -> Path:
    path = directory / name
    path.write_text(
        "from pydantic import BaseModel\n"
        "from crystalline.tools import Tool\n"
        "\n"
        "class Input(BaseModel):\n"
        "    pass\n"
        "\n"
        "async def handler(data):\n"
        "    return 42\n"
        "\n"
        "def build_tool(project):\n"
        "    return Tool(name='answer', input_model=Input, handler=handler)\n"
    )
    return path


def _write_skill_file(directory: Path, name: str = "skill_answer.py") -> Path:
    path = directory / name
    path.write_text(
        "from pydantic import BaseModel\n"
        "from crystalline.skills import Skill\n"
        "\n"
        "class Input(BaseModel):\n"
        "    pass\n"
        "\n"
        "async def handler(data):\n"
        "    return 42\n"
        "\n"
        "def build_skill(project):\n"
        "    return Skill(name='answer', input_model=Input, handler=handler)\n"
    )
    return path


def test_load_tool_file(tmp_path):
    project = Project("demo", "0.1.0")
    load_tool_file(_write_tool_file(tmp_path), project)
    assert project.tools.get_tool("answer") is not None


def test_load_skill_file(tmp_path):
    project = Project("demo", "0.1.0")
    load_skill_file(_write_skill_file(tmp_path), project)
    assert project.skills.get_tool("answer") is not None


def test_load_tool_file_missing_function_raises(tmp_path):
    path = tmp_path / "tool_bad.py"
    path.write_text("x = 1\n")
    project = Project("demo", "0.1.0")
    with pytest.raises(AttributeError):
        load_tool_file(path, project)


def test_load_skill_file_missing_function_raises(tmp_path):
    path = tmp_path / "skill_bad.py"
    path.write_text("x = 1\n")
    project = Project("demo", "0.1.0")
    with pytest.raises(AttributeError):
        load_skill_file(path, project)


def test_apply_extensions_discovers_tool_and_skill_files(tmp_path):
    _write_tool_file(tmp_path)
    _write_skill_file(tmp_path)
    project = Project("demo", "0.1.0", extensions_dir=str(tmp_path))

    apply_extensions(project)

    assert project.tools.get_tool("answer") is not None
    assert project.skills.get_tool("answer") is not None


def test_apply_extensions_ignores_files_without_the_prefix(tmp_path):
    _write_tool_file(tmp_path)
    (tmp_path / "helpers.py").write_text("x = 1\n")
    project = Project("demo", "0.1.0", extensions_dir=str(tmp_path))

    apply_extensions(project)  # should not try to load helpers.py

    assert project.tools.get_tool("answer") is not None


def test_apply_extensions_with_no_extensions_dir_is_a_no_op():
    project = Project("demo", "0.1.0")
    apply_extensions(project)  # should not raise
    assert len(project.skills) == 0


def test_apply_extensions_missing_directory_raises(tmp_path):
    project = Project("demo", "0.1.0", extensions_dir=str(tmp_path / "does-not-exist"))
    with pytest.raises(NotADirectoryError):
        apply_extensions(project)


def test_same_filename_in_different_directories_do_not_collide(tmp_path):
    # Two different projects' extension files sharing a filename stem
    # (here, both "tool_mixed.py") must not collide in sys.modules — a
    # collision would make the earlier file's lazily-resolved forward
    # references (`from __future__ import annotations`) look themselves
    # up in the *later* file's namespace instead of their own.
    dir_a = tmp_path / "project_a"
    dir_b = tmp_path / "project_b"
    dir_a.mkdir()
    dir_b.mkdir()

    (dir_a / "tool_mixed.py").write_text(
        "from __future__ import annotations\n"
        "from pydantic import BaseModel\n"
        "from crystalline.tools import Tool\n"
        "\n"
        "class Item(BaseModel):\n"
        "    value: int\n"
        "\n"
        "class Input(BaseModel):\n"
        "    items: list[Item]\n"
        "\n"
        "async def handler(data):\n"
        "    return sum(item.value for item in data.items)\n"
        "\n"
        "def build_tool(project):\n"
        "    return Tool(name='answer_a', input_model=Input, handler=handler)\n"
    )
    (dir_b / "tool_mixed.py").write_text(
        "from __future__ import annotations\n"
        "from pydantic import BaseModel\n"
        "from crystalline.tools import Tool\n"
        "\n"
        "class Item(BaseModel):\n"
        "    count: int\n"
        "\n"
        "class Input(BaseModel):\n"
        "    items: list[Item]\n"
        "\n"
        "async def handler(data):\n"
        "    return sum(item.count for item in data.items)\n"
        "\n"
        "def build_tool(project):\n"
        "    return Tool(name='answer_b', input_model=Input, handler=handler)\n"
    )

    project_a = Project("a", "0.1.0")
    project_b = Project("b", "0.1.0")
    load_tool_file(dir_a / "tool_mixed.py", project_a)
    load_tool_file(dir_b / "tool_mixed.py", project_b)

    tool_a = project_a.tools.get_tool("answer_a")
    tool_b = project_b.tools.get_tool("answer_b")
    instance_a = tool_a.input_model(items=[{"value": 5}])
    instance_b = tool_b.input_model(items=[{"count": 7}])
    assert instance_a.items[0].value == 5
    assert instance_b.items[0].count == 7


def test_apply_extensions_is_idempotent_for_reload(tmp_path):
    _write_tool_file(tmp_path)
    project = Project("demo", "0.1.0", extensions_dir=str(tmp_path))

    apply_extensions(project)
    apply_extensions(project)

    tools = [t for t in project.tools if t.name == "answer"]
    assert len(tools) == 1
