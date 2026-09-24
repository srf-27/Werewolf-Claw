"""
网页版聊天机器人 Agent：。

workflows：

    输入 ->通过输入推断是否需要调用工具- "需要"->调用工具-"回复"
                                 - "不需要"->"回复"
        -"编辑"-> 编辑（撤回上一轮后重新提问）-> "回复"
        -"重新生成"-> 重新生成 -> "回复"

说明：

- 「推断」带着工具清单问一次模型：模型直接给出正文就是「不需要」，这段正文就是这一轮的回答；
  返回 tool_calls 就是「需要」。
- 「调用工具」执行这些 tool_calls，把这一轮的工具消息接回上下文交给「回复」；工具消息只参与
  这一轮，会话里只留最终回答。
- 「编辑」撤回上一轮后重新提问，问题照样走「推断」，所以改过的问法一样能调工具。
- 工具集见 `werewolf_claw.tools.get_chat_tools()`，系统提示词见 `werewolf_claw.agents.prompts`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from werewolf_claw.agents.prompts import CHAT_SYSTEM_PROMPT, TOOLS_SECTION
from werewolf_claw.core import conversation
from werewolf_claw.core import llm
from werewolf_claw.core.memory import Memory
from werewolf_claw.core.node import DEFAULT_ACTION, Flow, Node
from werewolf_claw.tools import (
    BaseTool,
    GoalState,
    ToolCall,
    ToolExecutor,
    get_chat_tools,
    goal_message,
    tool,
)

# 三条入口路径，InputNode 按这个分派。
SEND = "回复"
EDIT = "编辑"
REGENERATE = "重新生成"

# 推断节点的两条出边：这一轮要不要调用工具。
NEED_TOOL = "需要"
NO_TOOL = "不需要"

# 编辑支路：撤回上一轮、重新提问之后回到推断节点。
INFER = "推断"

# 各条支路的收尾 action。
FINISH = "结束"


def make_goal_complete_tool(goal: GoalState) -> BaseTool:
    """参考脚本里的 `goal_complete` 工具：模型自己宣布目标完成。"""

    @tool("goal_complete", parse_docstring=True)
    def goal_complete() -> str:
        """Mark the active goal as complete.

        Only call this after the goal is fully finished and verified.
        If no goal is active, this tool does nothing.
        """
        return goal.complete()

    return goal_complete


@dataclass
class Turn:
    """一次 Flow 里传下去的东西。"""

    action: str
    text: str = ""
    quote: conversation.Quote | None = None
    # 已经写进记忆、还没回答的那一轮（推断节点写用户消息时拿到）
    handle: conversation.TurnHandle | None = None
    # 推断节点的模型答复：有 tool_calls 就是「需要」，否则正文就是这一轮的回答
    answer: conversation.ModelAnswer | None = None
    # 推断节点从答复里解出来的工具调用；有就说明这一轮「需要」调用工具
    calls: list[ToolCall] = field(default_factory=list)
    # 调用工具那条支路要接回上下文的消息：assistant 的 tool_calls + 每条 tool 结果
    tool_messages: list[dict[str, Any]] = field(default_factory=list)
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


class InferNode(Node):
    """推断是否需要调用工具：带着工具清单问一次模型。

    模型返回 tool_calls 就是「需要」；直接给出正文就是「不需要」，这段正文就是这一轮的回答。
    """

    def __init__(self, agent: "ChatAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.agent = agent

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        # 用户消息先落库：这一轮的回答要挂在它后面（编辑支路已经撤回上一轮）
        payload.handle = conversation.open_turn(self.agent.memory, payload.text, payload.quote)
        payload.answer = conversation.ask(
            self.agent.memory,
            system=self.agent.system_prompt,
            tools=self.agent.tools.llm_tools(),
        )
        calls = self.agent.tools.parse_tool_calls({"tool_calls": payload.answer.tool_calls})
        payload.calls = calls
        return (NEED_TOOL if calls else NO_TOOL), payload


class ToolNode(Node):
    """调用工具：执行模型要调的每个工具，拼出这一轮的工具消息。"""

    def __init__(self, agent: "ChatAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.agent = agent

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        results = self.agent.tools.execute_all(payload.calls)
        payload.tool_messages = [
            {
                "role": "assistant",
                "content": payload.answer.content if payload.answer else "",
                "tool_calls": [call.to_message() for call in payload.calls],
            },
            *(result.to_message() for result in results),
        ]
        return FINISH, payload


class ReplyNode(Node):
    """回复：生成这一轮的回答，写回记忆。"""

    def __init__(self, agent: "ChatAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.agent = agent

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        answer = payload.answer
        if payload.tool_messages:
            # 调用工具那条支路：工具结果接回上下文，再让模型按结果回答（这一次不再带工具）
            answer = conversation.ask(
                self.agent.memory,
                system=self.agent.system_prompt,
                extra_messages=payload.tool_messages,
            )
        if answer is None or payload.handle is None:
            raise conversation.ConflictError("这一轮还没有问过模型")
        payload.result = conversation.answer_turn(
            self.agent.memory, payload.handle, answer.content, answer.usage
        )
        return FINISH, payload


class EditNode(Node):
    """编辑：撤回最后一轮问答，把编辑后的内容重新提给推断节点。"""

    def __init__(self, agent: "ChatAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.agent = agent

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        conversation.retract_last(self.agent.memory)
        return INFER, payload


class RegenerateNode(Node):
    """重新生成：把之前几次的回答交给模型，先总结不足再重答。

    新回答直接覆盖原来那条，所以这条支路自己就把结果写回了记忆，不用再走回复节点。
    """

    def __init__(self, agent: "ChatAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.agent = agent

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        payload.result = conversation.regenerate(self.agent.memory)
        return FINISH, payload


class DoneNode(Node):
    """收尾：结果已经放在 payload 里，交回给调用方。"""

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        return DEFAULT_ACTION, payload


class ChatAgent:
    """一个会话上的聊天 Agent。会话数据仍然由 `Memory` 持有。"""

    def __init__(self, memory: Memory) -> None:
        self.memory = memory
        # 人设 + 「有哪些工具、什么时候该用」（见 agents/prompts.py）
        self.system_prompt = f"{CHAT_SYSTEM_PROMPT}\n\n{TOOLS_SECTION}"
        # 工具：模型自己宣布目标完成，外加查板子和身份资料
        self.goal = GoalState()
        self.tools = ToolExecutor([make_goal_complete_tool(self.goal), *get_chat_tools()])
        self.flow = self.build_flow()

    def build_flow(self) -> Flow:
        """把各个 Node 连成一张图：三条入口，推断节点分两条出边，最后都汇到收尾。"""
        entry = InputNode(self)
        infer = InferNode(self)
        call = ToolNode(self)
        reply = ReplyNode(self)
        edit = EditNode(self)
        regenerate = RegenerateNode(self)
        done = DoneNode()

        entry - SEND >> infer
        entry - EDIT >> edit
        entry - REGENERATE >> regenerate
        infer - NEED_TOOL >> call
        infer - NO_TOOL >> reply
        call - FINISH >> reply
        edit - INFER >> infer  # 撤回过之后重新提问，一样要推断要不要调工具
        regenerate - FINISH >> done  # 重新生成自己覆盖了新回答，直接收尾
        reply - FINISH >> done
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

    # ------------------------------------------------------------------ goal 循环

    def run_goal(self, text: str, *, rounds: int = 6) -> list[str]:
        """带着目标反复跑，直到模型调用 `goal_complete`（或到轮数上限）。

        和参考脚本的 `run_goal()` 一个意思：每轮先把 goal 提醒写进历史，再让模型干活；
        这一轮里模型调了什么工具就执行什么，工具结果同样进历史。
        """
        self.goal.start(text)
        replies: list[str] = []
        while self.goal.active and len(replies) < rounds:
            self.memory.add_user(goal_message(self.goal)["content"])
            context = self.memory.build_context(self.system_prompt)
            completion = llm.chat_full(context, tools=self.tools.llm_tools())
            message = completion.choices[0].message
            calls = self.tools.parse_tool_calls(message)
            # 要调什么工具、工具返回什么都要留在历史里，否则下一条 tool 消息接不上这次调用
            self.memory.add_assistant(
                message.content or "",
                usage=completion.usage,
                extra={"tool_calls": [call.to_message() for call in calls]} if calls else None,
            )
            replies.append(message.content or "")
            for result in self.tools.execute_all(calls):
                self.memory.add_message(
                    "tool",
                    result.content,
                    extra={"tool_call_id": result.tool_call_id, "name": result.name},
                )
        return replies
