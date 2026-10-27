"""Base model for types shared across a Crystalline project."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CrystallineModel(BaseModel):
    """Base class for data types registered in a `SchemaRegistry`.

    Defaults are chosen for types that cross a boundary (tool
    input/output, event payloads, config): unknown fields are rejected
    rather than silently dropped, since a typo in a config-driven payload
    should fail loudly instead of validating against the wrong shape.
    """

    model_config = ConfigDict(extra="forbid")
