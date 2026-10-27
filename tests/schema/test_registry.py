import pytest

from crystalline.schema import CrystallineModel, SchemaRegistry


class Point(CrystallineModel):
    x: int
    y: int


def test_register_direct_defaults_name_to_class_name():
    registry = SchemaRegistry()
    registry.register(Point)
    assert registry.get("Point") is Point
    assert "Point" in registry
    assert len(registry) == 1
    assert list(registry) == ["Point"]


def test_register_with_explicit_name():
    registry = SchemaRegistry()
    registry.register(Point, name="geo.Point")
    assert registry.get("geo.Point") is Point
    assert registry.get("Point") is None


def test_register_as_decorator():
    registry = SchemaRegistry()

    @registry.register()
    class Vector(CrystallineModel):
        dx: float
        dy: float

    assert registry.get("Vector") is Vector


def test_register_as_decorator_with_name():
    registry = SchemaRegistry()

    @registry.register(name="vec3")
    class Vector3(CrystallineModel):
        x: float
        y: float
        z: float

    assert registry.get("vec3") is Vector3
    assert "Vector3" not in registry


def test_register_duplicate_name_raises():
    registry = SchemaRegistry()
    registry.register(Point)

    class OtherPoint(CrystallineModel):
        x: int
        y: int

    with pytest.raises(ValueError):
        registry.register(OtherPoint, name="Point")


def test_register_duplicate_name_allowed_with_replace():
    registry = SchemaRegistry()
    registry.register(Point)

    class OtherPoint(CrystallineModel):
        x: int
        y: int

    registry.register(OtherPoint, name="Point", replace=True)
    assert registry.get("Point") is OtherPoint


def test_register_same_model_twice_is_not_a_conflict():
    registry = SchemaRegistry()
    registry.register(Point)
    registry.register(Point)  # no error: re-registering the same class
    assert registry.get("Point") is Point


def test_remove():
    registry = SchemaRegistry()
    registry.register(Point)
    assert registry.remove("Point") is Point
    assert registry.get("Point") is None
    assert registry.remove("Point") is None


def test_types_property_is_a_copy():
    registry = SchemaRegistry()
    registry.register(Point)
    snapshot = registry.types
    snapshot["Injected"] = Point
    assert "Injected" not in registry


def test_crystalline_model_rejects_unknown_fields():
    with pytest.raises(Exception):
        Point(x=1, y=2, z=3)
