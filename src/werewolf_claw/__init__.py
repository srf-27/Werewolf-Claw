"""Werewolf-Claw：狼人杀对局项目。

代码分层：

- `werewolf_claw.core`：LLM 调用与节点流程等基础能力。
- `werewolf_claw.app`：对局编排与命令行入口。
- `werewolf_claw.tools`：供节点复用的通用工具。
"""

__version__ = "0.1.0"


def main() -> None:
    """命令行入口，对应 `[project.scripts]` 里的 `werewolf-claw`。"""
    raise NotImplementedError("命令行入口尚未实现，先写 app 层的对局启动逻辑")
