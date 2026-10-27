import pytest
from pydantic import ValidationError

from crystalline.project.fields import (
    FieldSpecError,
    build_model_from_field_spec,
    field_spec_from_model,
    resolve_type,
    type_to_expr,
)
from crystalline.schema import SchemaRegistry


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("str", str),
        ("int", int),
        ("float", float),
        ("bool", bool),
        ("list[str]", list[str]),
        ("dict[str, int]", dict[str, int]),
        ("str | None", str | None),
        ("Optional[int]", int | None),
    ],
)
def test_resolve_type_primitives(expr, expected):
    registry = SchemaRegistry()
    assert resolve_type(expr, registry) == expected


def test_resolve_type_reference_to_registered_type():
    registry = SchemaRegistry()
    Model = build_model_from_field_spec("Customer", {"id": "str"}, registry)
    registry.register(Model, name="Customer")
    assert resolve_type("Customer", registry) is Model


def test_resolve_type_unknown_raises():
    registry = SchemaRegistry()
    with pytest.raises(FieldSpecError):
        resolve_type("NotAType", registry)


def test_nested_list_of_registered_type():
    registry = SchemaRegistry()
    OrderItem = build_model_from_field_spec(
        "OrderItem",
        {"product_id": "str", "count": "int", "subtotal": "float"},
        registry,
    )
    registry.register(OrderItem, name="OrderItem")

    Order = build_model_from_field_spec(
        "Order", {"id": "str", "items": "list[OrderItem]"}, registry
    )
    order = Order(id="o1", items=[{"product_id": "p1", "count": 2, "subtotal": 19.98}])
    assert isinstance(order.items[0], OrderItem)
    assert order.items[0].count == 2

    # round trip the Order field spec back to an expression string
    rebuilt_spec = field_spec_from_model(Order, registry)
    assert rebuilt_spec["items"] == "list[OrderItem]"


@pytest.mark.parametrize(
    ("py_type", "expr"),
    [
        (str, "str"),
        (list[str], "list[str]"),
        (dict[str, int], "dict[str, int]"),
        (str | None, "str | None"),
    ],
)
def test_type_to_expr_round_trip(py_type, expr):
    registry = SchemaRegistry()
    assert type_to_expr(py_type, registry) == expr
    assert resolve_type(expr, registry) == py_type


def test_build_model_from_field_spec_required_and_optional():
    registry = SchemaRegistry()
    Product = build_model_from_field_spec(
        "Product",
        {
            "id": "str",
            "price": "float",
            "description": {"type": "str", "required": False, "default": ""},
        },
        registry,
    )

    product = Product(id="p1", price=9.99)
    assert product.description == ""

    with pytest.raises(ValidationError):
        Product(price=9.99)  # id is required


def test_optional_field_with_no_explicit_default_defaults_to_none():
    # required: false with no "default" key must imply None, not stay a
    # required field (Field(default=...) is Pydantic's "no default"
    # sentinel, so forgetting to substitute None here silently makes the
    # field required despite required: false).
    registry = SchemaRegistry()
    Product = build_model_from_field_spec(
        "Product",
        {
            "id": "str",
            "nickname": {"type": "str | None", "required": False},
        },
        registry,
    )

    product = Product(id="p1")
    assert product.nickname is None


def test_build_model_rejects_unknown_fields():
    registry = SchemaRegistry()
    Customer = build_model_from_field_spec("Customer", {"id": "str"}, registry)
    with pytest.raises(ValidationError):
        Customer(id="c1", unexpected="nope")


def test_field_spec_from_model_round_trip():
    registry = SchemaRegistry()
    spec = {
        "id": "str",
        "price": "float",
        "description": {"type": "str", "required": False, "default": ""},
    }
    Product = build_model_from_field_spec("Product", spec, registry)
    registry.register(Product, name="Product")

    rebuilt_spec = field_spec_from_model(Product, registry)
    Rebuilt = build_model_from_field_spec("Product", rebuilt_spec, registry)

    product = Rebuilt(id="p1", price=1.5)
    assert product.description == ""
    assert Rebuilt(id="p1", price=1.5, description="x").description == "x"
