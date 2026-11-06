import asyncio

import pytest

from crystalline.crystallization import CrystallizationContext, SessionReplayPlugin
from crystalline.monitoring import Session, SessionEvent, Turn
from crystalline.schema import CrystallineModel, SchemaRegistry


class _Order(CrystallineModel):
    id: str
    total: float


def _schema_with_order() -> SchemaRegistry:
    registry = SchemaRegistry()
    registry.register(_Order, name="Order")
    return registry


class _StubProject:
    name = "demo"
    schema = _schema_with_order()
    tools = []
    skills = []
    extensions_dir = None


class _FakeAgent:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def run(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._responses.pop(0)


def _ctx(agent: _FakeAgent) -> CrystallizationContext:
    return CrystallizationContext(
        project=_StubProject(),
        session=Session(id="s1", project_name="demo"),
        turns=[Turn(id="t1", session_id="s1")],
        events=[
            SessionEvent(
                session_id="s1", turn_id="t1", kind="tool_call", data={"name": "total_revenue"}
            )
        ],
        agent=agent,
    )


_VALID_RESPONSE = """TITLE: Dashboard skill
FILE: skill_dashboard.py
KIND: skill
ACTION: create
```python
def build_skill(project):
    pass
```
RATIONALE:
Chains total_revenue and list_customer into one skill.
"""

_MULTI_FILE_RESPONSE = """TITLE: Dashboard skill + helper tool
FILE: skill_dashboard.py
KIND: skill
ACTION: create
```python
def build_skill(project):
    pass
```
FILE: tool_helper.py
KIND: tool
ACTION: modify
```python
def build_tool(project):
    pass
```
RATIONALE:
Needs a new skill plus a tweak to an existing tool.
"""

_NOTHING_RESPONSE = "NOTHING: already covered by the existing place_order skill"

_MISSING_RATIONALE_RESPONSE = """TITLE: Oops
FILE: skill_x.py
KIND: skill
ACTION: create
```python
x = 1
```
"""

_SYNTAX_ERROR_RESPONSE = """TITLE: Broken
FILE: skill_broken.py
KIND: skill
ACTION: create
```python
def build_skill(project)
    pass
```
RATIONALE:
This one is syntactically broken.
"""

_KIND_FILENAME_MISMATCH_RESPONSE = """TITLE: Dashboard tool
FILE: tool_dashboard.py
KIND: skill
ACTION: create
```python
def build_skill(project):
    pass
```
RATIONALE:
Declares KIND: skill but keeps the tool_ filename.
"""

_TOOL_CHAINING_MULTIPLE_TOOLS_RESPONSE = """TITLE: Dashboard tool
FILE: tool_dashboard.py
KIND: tool
ACTION: create
```python
async def dashboard(data):
    customers = await list_customer.invoke(list_customer.input_model())
    products = await list_product.invoke(list_product.input_model())
    return {"customers": customers, "products": products}
```
RATIONALE:
Wrongly labeled a Tool even though it chains two other tools' .invoke().
"""

_WITH_SCHEMA_CHANGE_RESPONSE = """TITLE: Order summary skill
SCHEMA: OrderSummary
ACTION: create
FIELDS:
```json
{"order_id": "str", "total": "float", "item_count": "int"}
```
FILE: skill_summarize_order.py
KIND: skill
ACTION: create
```python
def build_skill(project):
    pass
```
RATIONALE:
Needs a new OrderSummary type to return from the skill.
"""

_SCHEMA_DELETE_RESPONSE = """TITLE: Drop OrderSummary
SCHEMA: OrderSummary
ACTION: delete
FILE: skill_summarize_order.py
KIND: skill
ACTION: delete
RATIONALE:
No longer needed.
"""

_SCHEMA_RESERVED_NAME_RESPONSE = """TITLE: Bad type name
SCHEMA: User
ACTION: create
FIELDS:
```json
{"x": "str"}
```
FILE: skill_x.py
KIND: skill
ACTION: create
```python
def build_skill(project):
    pass
```
RATIONALE:
Tries to redeclare the reserved User type.
"""

_SCHEMA_BAD_JSON_RESPONSE = """TITLE: Bad json
SCHEMA: OrderSummary
ACTION: create
FIELDS:
```json
{not valid json}
```
FILE: skill_x.py
KIND: skill
ACTION: create
```python
def build_skill(project):
    pass
```
RATIONALE:
FIELDS block isn't valid JSON.
"""


def test_parses_a_valid_single_file_proposal():
    agent = _FakeAgent([_VALID_RESPONSE])
    proposal = asyncio.run(SessionReplayPlugin().propose(_ctx(agent)))
    assert proposal is not None
    assert proposal.plugin == "session"
    assert proposal.title == "Dashboard skill"
    [change] = proposal.changes
    assert change.path == "skill_dashboard.py"
    assert change.action == "create"
    assert "build_skill" in change.content


def test_parses_multiple_file_blocks():
    agent = _FakeAgent([_MULTI_FILE_RESPONSE])
    proposal = asyncio.run(SessionReplayPlugin().propose(_ctx(agent)))
    assert proposal is not None
    assert [c.path for c in proposal.changes] == ["skill_dashboard.py", "tool_helper.py"]
    assert proposal.changes[1].action == "modify"


def test_nothing_response_returns_none():
    agent = _FakeAgent([_NOTHING_RESPONSE])
    proposal = asyncio.run(SessionReplayPlugin().propose(_ctx(agent)))
    assert proposal is None


def test_malformed_response_is_retried_then_succeeds():
    agent = _FakeAgent([_MISSING_RATIONALE_RESPONSE, _VALID_RESPONSE])
    proposal = asyncio.run(SessionReplayPlugin().propose(_ctx(agent)))
    assert proposal is not None
    assert len(agent.prompts) == 2
    assert "previous response had a problem" in agent.prompts[1]


def test_malformed_response_twice_raises():
    agent = _FakeAgent([_MISSING_RATIONALE_RESPONSE, _MISSING_RATIONALE_RESPONSE])
    with pytest.raises(ValueError):
        asyncio.run(SessionReplayPlugin().propose(_ctx(agent)))


def test_syntax_error_in_generated_code_is_rejected_and_retried():
    agent = _FakeAgent([_SYNTAX_ERROR_RESPONSE, _VALID_RESPONSE])
    proposal = asyncio.run(SessionReplayPlugin().propose(_ctx(agent)))
    assert proposal is not None
    assert len(agent.prompts) == 2


def test_kind_filename_mismatch_is_rejected_and_retried():
    agent = _FakeAgent([_KIND_FILENAME_MISMATCH_RESPONSE, _VALID_RESPONSE])
    proposal = asyncio.run(SessionReplayPlugin().propose(_ctx(agent)))
    assert proposal is not None
    assert len(agent.prompts) == 2
    assert "KIND: skill" in agent.prompts[1]


def test_tool_chaining_multiple_tool_invokes_is_rejected_and_retried():
    agent = _FakeAgent([_TOOL_CHAINING_MULTIPLE_TOOLS_RESPONSE, _VALID_RESPONSE])
    proposal = asyncio.run(SessionReplayPlugin().propose(_ctx(agent)))
    assert proposal is not None
    assert len(agent.prompts) == 2
    assert "makes this a Skill" in agent.prompts[1]


def test_parses_a_schema_change_alongside_a_file_change():
    agent = _FakeAgent([_WITH_SCHEMA_CHANGE_RESPONSE])
    proposal = asyncio.run(SessionReplayPlugin().propose(_ctx(agent)))
    assert proposal is not None
    [schema_change] = proposal.schema_changes
    assert schema_change.type_name == "OrderSummary"
    assert schema_change.action == "create"
    assert schema_change.field_spec == {
        "order_id": "str",
        "total": "float",
        "item_count": "int",
    }
    [file_change] = proposal.changes
    assert file_change.path == "skill_summarize_order.py"


def test_parses_a_schema_delete_with_no_fields_block():
    agent = _FakeAgent([_SCHEMA_DELETE_RESPONSE])
    proposal = asyncio.run(SessionReplayPlugin().propose(_ctx(agent)))
    assert proposal is not None
    [schema_change] = proposal.schema_changes
    assert schema_change.action == "delete"
    assert schema_change.field_spec is None


def test_response_without_a_schema_block_has_no_schema_changes():
    agent = _FakeAgent([_VALID_RESPONSE])
    proposal = asyncio.run(SessionReplayPlugin().propose(_ctx(agent)))
    assert proposal is not None
    assert proposal.schema_changes == []


def test_schema_change_with_reserved_type_name_is_rejected_and_retried():
    agent = _FakeAgent([_SCHEMA_RESERVED_NAME_RESPONSE, _VALID_RESPONSE])
    proposal = asyncio.run(SessionReplayPlugin().propose(_ctx(agent)))
    assert proposal is not None
    assert len(agent.prompts) == 2
    assert "reserved" in agent.prompts[1]


def test_schema_change_with_invalid_json_is_rejected_and_retried():
    agent = _FakeAgent([_SCHEMA_BAD_JSON_RESPONSE, _VALID_RESPONSE])
    proposal = asyncio.run(SessionReplayPlugin().propose(_ctx(agent)))
    assert proposal is not None
    assert len(agent.prompts) == 2
    assert "invalid JSON" in agent.prompts[1]
