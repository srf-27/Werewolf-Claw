"""网页版聊天机器人 Agent：用 Node + Flow 串起一轮问答。

每个环节一个 Node：

    输入 -"回复"-> 回复 -"结束"-> 收尾
         -"编辑"-> 编辑（撤回上一轮后重新提问）-> 收尾
         -"重新生成"-> 重新生成 -> 收尾

一轮问答本身的实现仍在 `core.conversation`：上下文怎么拼、什么时候压缩、领域错误
有哪些、重新生成的结果怎么分段，都在那里。这里只负责编排，并给 app 层一个统一
入口：`ChatAgent(memory).send(...)`，返回值就是 `core.conversation.TurnResult`。

命令行版（`demo/chatbot.py`）自己有另一条 Flow，两边共用同一个 core。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from werewolf_claw.core import conversation
from werewolf_claw.core.memory import Memory
from werewolf_claw.core.node import DEFAULT_ACTION, Flow, Node

# 三条入口路径，InputNode 按这个分派。
SEND = "回复"
EDIT = "编辑"
REGENERATE = "重新生成"


@dataclass
class Turn:
    """一次 Flow 里传下去的东西。"""

    action: str
    text: str = ""
    quote: conversation.Quote | None = None
    result: conversation.TurnResult | None = None


class InputNode(Node):
    """输入：校验文本，交给后继节点。"""

    def __init__(self, agent: "ChatAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.agent = agent

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        if payload.action in (SEND, EDIT):
            text = payload.text.strip()
            if not text:
                raise conversation.InvalidRequest("消息内容不能为空")
            payload.text = text
        elif payload.action != REGENERATE:
            raise conversation.InvalidRequest(f"不认识的入口：{payload.action}")
        return payload.action, payload


class ReplyNode(Node):
    """回复：写入用户消息、调模型、写回记忆。"""

    def __init__(self, agent: "ChatAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.agent = agent

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        payload.result = conversation.send(self.agent.memory, payload.text, payload.quote)
        return "结束", payload


class EditNode(Node):
    """编辑：撤回最后一轮问答，用新内容重新提问。"""

    def __init__(self, agent: "ChatAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.agent = agent

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        payload.result = conversation.edit_last(self.agent.memory, payload.text)
        return "结束", payload


class RegenerateNode(Node):
    """重新生成：把之前几次的回答交给模型，先总结不足再重答。"""

    def __init__(self, agent: "ChatAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.agent = agent

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        payload.result = conversation.regenerate(self.agent.memory)
        return "结束", payload


class DoneNode(Node):
    """收尾：结果已经放在 payload 里，交回给调用方。"""

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        return DEFAULT_ACTION, payload


class ChatAgent:
    """一个会话上的聊天 Agent。会话数据仍然由 `Memory` 持有。"""

    def __init__(self, memory: Memory) -> None:
        self.memory = memory
        self.flow = self.build_flow()

    def build_flow(self) -> Flow:
        """把各个 Node 连成三条互斥的支路，都汇到收尾。"""
        entry = InputNode(self)
        reply = ReplyNode(self)
        edit = EditNode(self)
        regenerate = RegenerateNode(self)
        done = DoneNode()

        entry - SEND >> reply
        entry - EDIT >> edit
        entry - REGENERATE >> regenerate
        reply - "结束" >> done
        edit - "结束" >> done
        regenerate - "结束" >> done
        return Flow(entry)

    # ------------------------------------------------------------------ 入口

    def send(self, text: str, quote: conversation.Quote | None = None) -> conversation.TurnResult:
        """发一条用户消息，走完整条回复支路。"""
        return self._run(Turn(action=SEND, text=text, quote=quote))

    def edit(self, text: str) -> conversation.TurnResult:
        """撤回最后一轮问答，用编辑后的内容重新提问。"""
        return self._run(Turn(action=EDIT, text=text))

    def regenerate(self) -> conversation.TurnResult:
        """重新生成最后一条回复。"""
        return self._run(Turn(action=REGENERATE))

    def _run(self, turn: Turn) -> conversation.TurnResult:
        _, payload = self.flow.run(turn)
        if payload.result is None:
            raise conversation.ConflictError("这一轮没有产生结果")
        return payload.result
