from pydantic import BaseModel

from crystalline.project import Project
from crystalline.schema import SchemaRegistry
from crystalline.security import SecurityPolicy, User
from crystalline.skills import Skill, SkillRegistry
from crystalline.storage import InMemoryStorage, SQLiteStorage


class _Input(BaseModel):
    value: int


def test_defaults():
    project = Project("demo-shop", "0.1.0")
    assert project.name == "demo-shop"
    assert project.version == "0.1.0"
    assert project.description is None
    assert isinstance(project.schema, SchemaRegistry)
    assert isinstance(project.storage, InMemoryStorage)
    assert isinstance(project.security, SecurityPolicy)
    assert isinstance(project.skills, SkillRegistry)
    assert len(project.skills) == 0
    assert project.properties == {}


def test_custom_skills_registry():
    registry = SkillRegistry()

    async def handler(data):
        return data

    registry.add_tool(Skill(name="noop", input_model=_Input, handler=handler))
    project = Project("demo-shop", "0.1.0", skills=registry)
    assert project.skills is registry
    assert project.skills.get_tool("noop") is not None


def test_user_type_is_auto_registered():
    project = Project("demo-shop", "0.1.0")
    assert project.schema.get("User") is User
    assert len(project.schema) == 1


def test_custom_storage():
    storage = SQLiteStorage(":memory:")
    project = Project("demo-shop", "0.1.0", storage=storage)
    assert project.storage is storage
    storage.close()


def test_custom_security_policy():
    policy = SecurityPolicy(roles={"support": ["Order:read"]})
    project = Project("demo-shop", "0.1.0", security=policy)
    assert project.security is policy
    assert "support" in project.security.roles


def test_properties_crud():
    project = Project("demo-shop", "0.1.0")
    project.set_property("owner", "ada")
    assert project.get_property("owner") == "ada"
    assert project.get_property("missing", "fallback") == "fallback"

    snapshot = project.properties
    snapshot["owner"] = "mutated"
    assert project.get_property("owner") == "ada"  # snapshot is a copy

    assert project.remove_property("owner") == "ada"
    assert project.get_property("owner") is None


def test_schema_is_shared_registry_instance():
    project = Project("demo-shop", "0.1.0")
    assert project.schema is project.schema
