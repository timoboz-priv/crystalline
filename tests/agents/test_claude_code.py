from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from crystalline.agents import ClaudeCodeAgent, TextChunk, Tool, ToolCallChunk


async def _handler(args):
    return {"content": [{"type": "text", "text": "ok"}]}


def test_tools_without_handler_are_builtin_references():
    agent = ClaudeCodeAgent("demo")
    agent.add_tool(Tool(name="Read"))
    agent.add_tool(Tool(name="Bash", enabled=False))

    opts = agent._build_options()
    assert opts.allowed_tools == ["Read"]
    assert opts.disallowed_tools == ["Bash"]
    assert opts.mcp_servers == {}


def test_handler_tools_default_to_crystalline_group():
    agent = ClaudeCodeAgent("demo")
    agent.add_tool(Tool(name="add", handler=_handler))

    opts = agent._build_options()
    assert opts.allowed_tools == ["mcp__crystalline__add"]
    assert set(opts.mcp_servers) == {"crystalline"}


def test_handler_tools_grouped_into_separate_mcp_servers():
    agent = ClaudeCodeAgent("demo")
    agent.add_tool(Tool(name="create_customer", handler=_handler, metadata={"group": "storage"}))
    agent.add_tool(Tool(name="create_user", handler=_handler, metadata={"group": "admin"}))

    opts = agent._build_options()
    assert set(opts.mcp_servers) == {"storage", "admin"}
    assert "mcp__storage__create_customer" in opts.allowed_tools
    assert "mcp__admin__create_user" in opts.allowed_tools


def test_disabled_handler_tool_is_disallowed_but_still_served():
    agent = ClaudeCodeAgent("demo")
    agent.add_tool(
        Tool(
            name="delete_customer",
            handler=_handler,
            metadata={"group": "storage"},
            enabled=False,
        )
    )

    opts = agent._build_options()
    assert "mcp__storage__delete_customer" in opts.disallowed_tools
    assert "storage" in opts.mcp_servers


def test_describe_message_extracts_text():
    agent = ClaudeCodeAgent("demo")
    message = AssistantMessage(content=[TextBlock(text="hi there")], model="claude")

    assert agent.describe_message(message) == [TextChunk(text="hi there")]


def test_describe_message_extracts_interleaved_text_and_tool_calls():
    agent = ClaudeCodeAgent("demo")
    message = AssistantMessage(
        content=[
            TextBlock(text="let me check"),
            ToolUseBlock(id="1", name="get_customer", input={"id": "c1"}),
            TextBlock(text="done"),
        ],
        model="claude",
    )

    assert agent.describe_message(message) == [
        TextChunk(text="let me check"),
        ToolCallChunk(name="get_customer", input={"id": "c1"}),
        TextChunk(text="done"),
    ]


def test_describe_message_ignores_non_assistant_messages():
    agent = ClaudeCodeAgent("demo")
    result = ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="s",
        stop_reason="end_turn",
        total_cost_usd=0.0,
        usage={},
        result="done",
        errors=None,
    )

    assert agent.describe_message(result) == []
