"""工具集：Agent 用的工具都在这里，统一用 LangChain `@tool` 声明。

- `agent_tools`：工具本体（`get_chat_tools` / `get_tools`）、`ToolExecutor`、goal 状态；
  `BaseTool` / `tool` 也在这里转出去，上层要加新工具就从这儿拿；
- `skill_loader`：SKILL.md 的解析。
"""

from langchain_core.tools import BaseTool, tool

from werewolf_claw.tools.agent_tools import (
    GoalState,
    ToolCall,
    ToolExecutor,
    ToolResult,
    get_chat_tools,
    get_tools,
    goal_message,
)

__all__ = [
    "BaseTool",
    "GoalState",
    "ToolCall",
    "ToolExecutor",
    "ToolResult",
    "get_chat_tools",
    "get_tools",
    "goal_message",
    "tool",
]
