from pathlib import Path

import pytest

from crystalline.project import Project, load_project, save_project
from crystalline.storage import SQLiteStorage

DEMO_PROJECT = (
    Path(__file__).resolve().parents[2] / "examples" / "demo_shop" / "project.yaml"
)


def _build_demo_project() -> Project:
    project = Project("demo-shop", "0.1.0", description="demo")
    from crystalline.project.fields import build_model_from_field_spec

    Customer = build_model_from_field_spec(
        "Customer", {"id": "str", "name": "str", "email": "str"}, project.schema
    )
    project.schema.register(Customer, name="Customer")

    Product = build_model_from_field_spec(
        "Product",
        {
            "id": "str",
            "name": "str",
            "description": {"type": "str", "required": False, "default": ""},
            "price": "float",
        },
        project.schema,
    )
    project.schema.register(Product, name="Product")

    OrderItem = build_model_from_field_spec(
        "OrderItem",
        {"product_id": "str", "count": "int", "subtotal": "float"},
        project.schema,
    )
    project.schema.register(OrderItem, name="OrderItem")

    Order = build_model_from_field_spec(
        "Order",
        {
            "id": "str",
            "customer_id": "str",
            "items": "list[OrderItem]",
            "total": "float",
        },
        project.schema,
    )
    project.schema.register(Order, name="Order")

    project.set_property("owner", "ada")
    return project


@pytest.mark.parametrize("suffix", [".yaml", ".yml", ".json"])
def test_save_and_load_round_trip(tmp_path, suffix):
    project = _build_demo_project()
    path = tmp_path / f"project{suffix}"
    save_project(project, path)

    reloaded = load_project(path)
    assert reloaded.name == project.name
    assert reloaded.version == project.version
    assert reloaded.description == project.description
    assert reloaded.properties == project.properties
    assert set(reloaded.schema) == {"Customer", "Product", "OrderItem", "Order", "User"}

    Product = reloaded.schema.get("Product")
    product = Product(id="p1", name="Widget", price=9.99)
    assert product.description == ""

    Order = reloaded.schema.get("Order")
    order = Order(
        id="o1",
        customer_id="c1",
        items=[{"product_id": "p1", "count": 2, "subtotal": 19.98}],
        total=19.98,
    )
    assert order.items[0].count == 2
    assert isinstance(order.items[0], reloaded.schema.get("OrderItem"))


def test_save_and_load_round_trip_with_sqlite_storage(tmp_path):
    project = _build_demo_project()
    project.storage = SQLiteStorage(str(tmp_path / "data.db"))
    path = tmp_path / "project.yaml"
    save_project(project, path)
    project.storage.close()

    reloaded = load_project(path)
    try:
        assert isinstance(reloaded.storage, SQLiteStorage)
        assert reloaded.storage.path == str(tmp_path / "data.db")
    finally:
        reloaded.storage.close()


def test_relative_storage_path_resolves_against_project_file_dir(tmp_path):
    project_dir = tmp_path / "nested" / "dir"
    project_dir.mkdir(parents=True)
    project_file = project_dir / "project.yaml"
    project_file.write_text(
        "name: demo\nversion: '0.1.0'\nschema: {}\n"
        "storage:\n  type: sqlite\n  path: data.db\nproperties: {}\n"
    )

    project = load_project(project_file)
    try:
        assert isinstance(project.storage, SQLiteStorage)
        assert project.storage.path == str(project_dir / "data.db")
    finally:
        project.storage.close()


def test_relative_storage_path_round_trips_through_save(tmp_path):
    # load_project resolves a relative storage.path to an absolute one;
    # save_project must convert it back to relative (against the save
    # target's own directory), not permanently bake in the absolute path.
    project_dir = tmp_path / "nested"
    project_dir.mkdir()
    project_file = project_dir / "project.yaml"
    project_file.write_text(
        "name: demo\nversion: '0.1.0'\nschema: {}\n"
        "storage:\n  type: sqlite\n  path: data.db\nproperties: {}\n"
    )

    project = load_project(project_file)
    try:
        assert project.storage.path == str(project_dir / "data.db")
        save_project(project, project_file)
    finally:
        project.storage.close()

    saved_text = project_file.read_text()
    assert "data.db" in saved_text
    assert str(project_dir) not in saved_text

    reloaded = load_project(project_file)
    try:
        assert reloaded.storage.path == str(project_dir / "data.db")
    finally:
        reloaded.storage.close()


def test_storage_path_outside_save_dir_stays_absolute(tmp_path):
    project_dir = tmp_path / "nested"
    project_dir.mkdir()
    elsewhere_dir = tmp_path / "elsewhere"
    elsewhere_dir.mkdir()
    project_file = project_dir / "project.yaml"
    absolute_db_path = elsewhere_dir / "data.db"
    project_file.write_text(
        "name: demo\nversion: '0.1.0'\nschema: {}\n"
        f"storage:\n  type: sqlite\n  path: {absolute_db_path}\nproperties: {{}}\n"
    )

    project = load_project(project_file)
    try:
        save_project(project, project_file)
    finally:
        project.storage.close()

    saved_text = project_file.read_text()
    assert str(absolute_db_path) in saved_text


def test_security_policy_round_trips(tmp_path):
    project = _build_demo_project()
    project.security.add_role("support", ["Order:read"])
    path = tmp_path / "project.yaml"
    save_project(project, path)

    reloaded = load_project(path)
    assert reloaded.security.secret_key == project.security.secret_key
    assert reloaded.security.get_role("support") == ["Order:read"]
    assert reloaded.security.roles["admin"] == project.security.roles["admin"]


def test_agent_config_defaults_to_claude_code(tmp_path):
    project = _build_demo_project()
    path = tmp_path / "project.yaml"
    save_project(project, path)

    reloaded = load_project(path)
    assert reloaded.agent_config == {"type": "claude_code"}


def test_agent_config_round_trips(tmp_path):
    project = _build_demo_project()
    project.agent_config = {"type": "claude_code", "model": "claude-sonnet-5-5"}
    path = tmp_path / "project.yaml"
    save_project(project, path)

    reloaded = load_project(path)
    assert reloaded.agent_config == {"type": "claude_code", "model": "claude-sonnet-5-5"}


def test_extensions_section_resolves_relative_to_project_file(tmp_path):
    project_dir = tmp_path / "nested"
    project_dir.mkdir()
    project_file = project_dir / "project.yaml"
    project_file.write_text(
        "name: demo\nversion: '0.1.0'\nschema: {}\n"
        "extensions: extensions\n"
        "properties: {}\n"
    )

    project = load_project(project_file)
    assert project.extensions_dir == str(project_dir / "extensions")


def test_load_project_does_not_execute_extensions_dir(tmp_path):
    # load_project only records the (resolved) path as data — it must
    # not scan/import anything in it. A path to a directory that doesn't
    # even exist should load fine; apply_extensions is what would fail on it.
    project_file = tmp_path / "project.yaml"
    project_file.write_text(
        "name: demo\nversion: '0.1.0'\nschema: {}\n"
        "extensions: does_not_exist\n"
        "properties: {}\n"
    )

    project = load_project(project_file)
    assert project.extensions_dir == str(tmp_path / "does_not_exist")
    assert project.tools.get_tool("answer") is None


def test_extensions_section_omitted_by_default(tmp_path):
    project = _build_demo_project()
    path = tmp_path / "project.yaml"
    save_project(project, path)

    reloaded = load_project(path)
    assert reloaded.extensions_dir is None


def test_monitoring_section_omitted_by_default(tmp_path):
    project = _build_demo_project()
    path = tmp_path / "project.yaml"
    save_project(project, path)

    reloaded = load_project(path)
    assert reloaded.monitoring_store is None


def test_monitoring_section_round_trips_relative_path(tmp_path):
    from crystalline.monitoring import SQLiteSessionStore

    project_dir = tmp_path / "nested"
    project_dir.mkdir()
    project_file = project_dir / "project.yaml"
    project_file.write_text(
        "name: demo\nversion: '0.1.0'\nschema: {}\n"
        "monitoring:\n  type: sqlite\n  path: monitoring.db\nproperties: {}\n"
    )

    project = load_project(project_file)
    try:
        assert isinstance(project.monitoring_store, SQLiteSessionStore)
        assert project.monitoring_store.path == str(project_dir / "monitoring.db")

        save_project(project, project_file)
        saved_text = project_file.read_text()
        assert "monitoring.db" in saved_text
        assert str(project_dir) not in saved_text
    finally:
        project.monitoring_store.close()


def test_declaring_user_type_in_schema_raises(tmp_path):
    path = tmp_path / "project.yaml"
    path.write_text(
        "name: demo\nversion: '0.1.0'\nschema:\n  User:\n    id: str\nproperties: {}\n"
    )
    with pytest.raises(ValueError):
        load_project(path)


def test_declaring_role_type_in_schema_raises(tmp_path):
    # "Role" is reserved too (crystalline.security.RESERVED_TYPE_NAMES),
    # matching crystalline.security.scopes.PROTECTED_TYPES — otherwise a
    # project-declared Role type's generated CRUD tools would be silently
    # overwritten by the framework's own role-policy admin tools of the
    # same name.
    path = tmp_path / "project.yaml"
    path.write_text(
        "name: demo\nversion: '0.1.0'\nschema:\n  Role:\n    id: str\nproperties: {}\n"
    )
    with pytest.raises(ValueError):
        load_project(path)


def test_seeded_users_are_created_and_idempotent(tmp_path):
    from crystalline.security import User, authenticate

    path = tmp_path / "project.yaml"
    path.write_text(
        "name: demo\nversion: '0.1.0'\nschema: {}\n"
        "storage:\n  type: sqlite\n  path: data.db\n"
        "users:\n  - id: alice\n    password: secret\n    roles: [admin]\n"
        "properties: {}\n"
    )

    project = load_project(path)
    try:
        user = authenticate(project.storage, "alice", "secret")
        assert user.roles == ["admin"]

        # seeding is idempotent: reloading doesn't reset a changed password
        project.storage.update(User, "alice", password_hash=user.password_hash)
    finally:
        project.storage.close()

    reloaded = load_project(path)
    try:
        # still logs in fine; seeding did not recreate/overwrite the user
        authenticate(reloaded.storage, "alice", "secret")
        assert len(reloaded.storage.list(User)) == 1
    finally:
        reloaded.storage.close()


def test_load_unsupported_extension_raises(tmp_path):
    path = tmp_path / "project.toml"
    path.write_text("name = 'x'")
    with pytest.raises(ValueError):
        load_project(path)


def test_save_unsupported_extension_raises(tmp_path):
    project = _build_demo_project()
    path = tmp_path / "project.toml"
    with pytest.raises(ValueError):
        save_project(project, path)


def test_loads_demo_shop_example(tmp_path):
    # examples/demo_shop is the user's own live demo project — reading
    # its project.yaml is fine, but loading it directly would create/
    # open the real demo_shop.db as a side effect. Load a copy from a
    # throwaway directory instead, so this test never touches it.
    copy_path = tmp_path / "project.yaml"
    copy_path.write_text(DEMO_PROJECT.read_text())

    project = load_project(copy_path)
    try:
        assert project.name == "demo-shop"
        assert set(project.schema) == {"Customer", "Product", "OrderItem", "Order", "User"}
        assert isinstance(project.storage, SQLiteStorage)
        assert project.storage.path == str(tmp_path / "demo_shop.db")

        Order = project.schema.get("Order")
        order = Order(
            id="o1",
            customer_id="c1",
            items=[{"product_id": "p1", "count": 1, "subtotal": 9.99}],
            total=9.99,
        )
        assert order.total == 9.99
        assert order.items[0].product_id == "p1"
    finally:
        project.storage.close()
