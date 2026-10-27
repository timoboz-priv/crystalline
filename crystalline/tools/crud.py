"""Auto-generate CRUD `Tool`s for every non-reserved type in a project's
schema, backed by its `Storage`.

One tool set per type (`create_x`/`get_x`/`update_x`/`delete_x`/`list_x`),
all in a single `"storage"` group/MCP server rather than one server per
type — a project's registered types are naturally "the storage API", and
one server keeps the tool list manageable as the schema grows instead of
spawning a new MCP server per type.

`sync_storage_tools` is the "auto-add mechanism": call it whenever a
project's schema may have changed (`crystalline.project.load_project`
does this automatically) to (re)generate tools for the current set of
types. It's idempotent — re-running it just overwrites the previous
generated tools with fresh ones reflecting the current schema/storage.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, create_model

from crystalline.schema import CrystallineModel, SchemaRegistry
from crystalline.security import RESERVED_TYPE_NAMES
from crystalline.storage import Storage

from .naming import to_snake_case
from .registry import ToolRegistry
from .tool import Tool

STORAGE_GROUP = "storage"


def _id_type(model: type[BaseModel]) -> Any:
    return model.model_fields["id"].annotation


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _optional_fields(
    model: type[BaseModel], *, exclude: set[str] = frozenset()
) -> dict[str, Any]:
    return {
        name: (info.annotation | None, None)
        for name, info in model.model_fields.items()
        if name not in exclude
    }


def _build_crud_tools_for_type(
    type_name: str, model: type[BaseModel], storage: Storage
) -> list[Tool]:
    snake = to_snake_case(type_name)
    id_type = _id_type(model)
    article = _article(type_name)

    id_input = create_model(
        f"{type_name}IdInput", __base__=CrystallineModel, id=(id_type, ...)
    )
    update_fields = _optional_fields(model, exclude={"id"})
    update_input = create_model(
        f"{type_name}UpdateInput",
        __base__=CrystallineModel,
        id=(id_type, ...),
        **update_fields,
    )
    list_input = create_model(
        f"{type_name}ListInput", __base__=CrystallineModel, **_optional_fields(model)
    )

    async def create_handler(data: BaseModel) -> BaseModel:
        return storage.create(data)

    async def get_handler(data: BaseModel) -> BaseModel | None:
        return storage.get(model, data.id)  # type: ignore[attr-defined]

    async def update_handler(data: BaseModel) -> BaseModel:
        changes = data.model_dump(exclude={"id"}, exclude_unset=True)
        return storage.update(model, data.id, **changes)  # type: ignore[attr-defined]

    async def delete_handler(data: BaseModel) -> bool:
        return storage.delete(model, data.id)  # type: ignore[attr-defined]

    async def list_handler(data: BaseModel) -> list[BaseModel]:
        filters = data.model_dump(exclude_unset=True)
        return storage.list(model, **filters)

    return [
        Tool(
            name=f"create_{snake}",
            description=f"Create {article} new {type_name} record.",
            input_model=model,
            output_model=model,
            handler=create_handler,
            scope=f"{type_name}:create",
            group=STORAGE_GROUP,
        ),
        Tool(
            name=f"get_{snake}",
            description=f"Get {article} {type_name} record by id.",
            input_model=id_input,
            output_model=model,
            handler=get_handler,
            scope=f"{type_name}:read",
            group=STORAGE_GROUP,
        ),
        Tool(
            name=f"update_{snake}",
            description=f"Partially update {article} {type_name} record by id.",
            input_model=update_input,
            output_model=model,
            handler=update_handler,
            scope=f"{type_name}:update",
            group=STORAGE_GROUP,
        ),
        Tool(
            name=f"delete_{snake}",
            description=f"Delete {article} {type_name} record by id.",
            input_model=id_input,
            handler=delete_handler,
            scope=f"{type_name}:delete",
            group=STORAGE_GROUP,
        ),
        Tool(
            name=f"list_{snake}",
            description=(
                f"List {type_name} records, optionally filtered by exact field match."
            ),
            input_model=list_input,
            output_model=model,
            handler=list_handler,
            scope=f"{type_name}:read",
            group=STORAGE_GROUP,
        ),
    ]


def generate_storage_tools(schema: SchemaRegistry, storage: Storage) -> list[Tool]:
    """Build CRUD tools for every registered type that both isn't
    reserved (e.g. `User`) and actually has an `id` field. Types without
    one (e.g. `OrderItem`, nested inside `Order`) are value objects, not
    independently stored entities — `Storage` itself requires an `id`
    field to manage a type, so there'd be nothing for CRUD tools to do.
    """
    tools: list[Tool] = []
    for type_name, model in schema.types.items():
        if type_name in RESERVED_TYPE_NAMES or "id" not in model.model_fields:
            continue
        tools.extend(_build_crud_tools_for_type(type_name, model, storage))
    return tools


def sync_storage_tools(
    registry: ToolRegistry, schema: SchemaRegistry, storage: Storage
) -> None:
    """(Re)generate CRUD tools for every current schema type into `registry`."""
    for tool in generate_storage_tools(schema, storage):
        registry.add_tool(tool, replace=True)
