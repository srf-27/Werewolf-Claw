"""Agent 工具集：用 LangChain `@tool` 装饰器声明，供 tool-calling agent 调用。

- 一个工具就是一个带类型标注和 Google 风格文档字符串的函数：名字、说明、参数 schema 都由
  `@tool` 从函数本身推出来（`parse_docstring=True` 会把 `Args:` 里的说明写进参数 schema）；
- `ToolExecutor`：把工具转成模型要的 OpenAI 格式（`convert_to_openai_tool`）、解析模型返回的
  tool_calls，再用 `tool.invoke()` 执行，产出 `role="tool"` 的消息；
- `get_chat_tools()`：网页版聊天机器人的工具集（查板子、查身份规则），资料都在项目里，不联网；
- `get_tools(target)`：玩家 Agent 的工具集（读大屏、查历史发言、记笔记、推理），闭包把玩家
  对象塞进实现里，声明方式和上面一样；
- `GoalState` / `goal_message`：goal 循环的状态和提醒消息（提醒文案在 `agents/prompts.py`）。

`core.llm.chat_full()` 已经支持 `tools`，这里只做工具本身，不碰模型调用。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import BaseTool, tool
from langchain_core.utils.function_calling import convert_to_openai_tool

from werewolf_claw.agents.prompts import goal_message as build_goal_message
from werewolf_claw.boards import BOARD_LABELS, BOARDS, DEFAULT_BOARD, board_id_of, board_options
from werewolf_claw.core.board import Board
from werewolf_claw.core.screen import PUBLIC
from werewolf_claw.core.vector_retriever import retrieve_similar


@dataclass
class GoalState:
    """一个 Agent 的目标：文本 + 是否还在追（玩家固定「获得游戏胜利」）。"""

    text: str | None = None
    active: bool = False

    def start(self, text: str) -> None:
        self.text = text
        self.active = True

    def clear(self) -> None:
        self.text = None
        self.active = False

    def complete(self) -> str:
        if not self.active:
            return "No active goal"
        self.clear()
        return "Goal complete"


def goal_message(goal: GoalState) -> dict[str, str]:
    """写进历史的 goal 提醒消息（GoalState 版，文本见 prompts.GOAL_MESSAGE）。"""
    return build_goal_message(goal.text or "")


@dataclass
class ToolCall:
    """模型要调用的一次工具。"""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    id: str = ""

    def to_message(self) -> dict[str, Any]:
        """转成 assistant 消息里的一项 `tool_calls`（参数是 JSON 字符串）。"""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass
class ToolResult:
    """一次工具调用的结果，可以直接塞回消息历史。"""

    name: str
    content: str
    tool_call_id: str = ""
    is_error: bool = False

    def to_message(self) -> dict[str, Any]:
        message: dict[str, Any] = {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "content": self.content,
        }
        return message


class ToolExecutor:
    """工具表：把工具清单交给模型，解析模型返回的 tool_calls，执行它们。"""

    def __init__(self, tools: Iterable[BaseTool] = ()) -> None:
        self.tools: list[BaseTool] = list(tools)
        self.tool_map: dict[str, BaseTool] = {item.name: item for item in self.tools}

    def add(self, item: BaseTool) -> BaseTool:
        self.tools.append(item)
        self.tool_map[item.name] = item
        return item

    def llm_tools(self) -> list[dict[str, Any]]:
        """交给模型的工具清单（OpenAI 的 function 格式）。"""
        return [convert_to_openai_tool(item) for item in self.tools]

    def parse_tool_calls(self, message: Any) -> list[ToolCall]:
        """从模型的回复里掏出 tool_calls，兼容 SDK 对象和 dict。"""
        raw = message.get("tool_calls") if isinstance(message, Mapping) else getattr(message, "tool_calls", None)
        calls: list[ToolCall] = []
        for item in raw or ():
            function = item.get("function") if isinstance(item, Mapping) else getattr(item, "function", None)
            if function is None:
                continue
            name = function.get("name") if isinstance(function, Mapping) else getattr(function, "name", "")
            arguments = function.get("arguments") if isinstance(function, Mapping) else getattr(function, "arguments", "")
            call_id = item.get("id", "") if isinstance(item, Mapping) else getattr(item, "id", "")
            calls.append(ToolCall(name=str(name or ""), arguments=_loads(arguments), id=str(call_id or "")))
        return calls

    def execute(self, call: ToolCall) -> ToolResult:
        """执行一次工具调用：调 `tool.invoke()`。

        没有这个工具、参数不合法、工具自己抛错，都变成一条错误结果，不打断这一轮。
        """
        item = self.tool_map.get(call.name)
        if item is None:
            return ToolResult(call.name, f"没有这个工具：{call.name}", call.id, is_error=True)
        try:
            return ToolResult(call.name, str(item.invoke(call.arguments)), call.id)
        except Exception as exc:
            return ToolResult(call.name, f"工具执行失败：{type(exc).__name__}: {exc}", call.id, is_error=True)

    def execute_all(self, calls: Sequence[ToolCall]) -> list[ToolResult]:
        return [self.execute(call) for call in calls]


def _loads(arguments: Any) -> dict[str, Any]:
    """工具参数：SDK 给的是 JSON 字符串，容忍空值和脏数据。"""
    if isinstance(arguments, Mapping):
        return dict(arguments)
    if not arguments:
        return {}
    try:
        data = json.loads(str(arguments))
    except json.JSONDecodeError:
        return {}
    return dict(data) if isinstance(data, Mapping) else {}


# ------------------------------------------------------------------ 聊天机器人的工具


@tool(parse_docstring=True)
def list_boards() -> str:
    """列出这个项目里能玩的板子：名字、人数和身份分布，各占一行。"""
    rows = [
        f"{options['name']}（{options['size']} 人）：{'、'.join(str(role) for role in options['distribution'])}"
        for options in board_options()
    ]
    return "\n".join(rows) if rows else "没有登记任何板子。"


@tool(parse_docstring=True)
def board_detail(board: str = "") -> str:
    """看一个板子的完整资料：人数、身份分布、各身份阵营、夜晚叫醒顺序、每个身份的规则。

    Args:
        board: 板子 id、名字或人数，例如 standard12_board、12 人标准板、12；留空用默认板子。
    """
    picked = _pick_board(str(board or ""))
    if picked is None:
        return f"没有这个板子：{board}。现有板子：" + "、".join(BOARDS)

    board_id, item = picked
    lines = [
        f"{BOARD_LABELS.get(board_id, board_id)}（{item.size} 人）",
        "身份分布：" + "、".join(item.distribution),
        "夜晚叫醒顺序：" + ("、".join(item.night_phases) if item.night_phases else "没有被叫醒的身份"),
        "身份规则：",
    ]
    for role in sorted(set(item.distribution)):
        character = item.characters[role]
        skill = character.skill or "无"
        lines.append(f"- {role}（{item.camps[role]}，技能：{skill}）：{character.describe}")
    return "\n".join(lines)


@tool(parse_docstring=True)
def role_rule(role: str) -> str:
    """查一个身份的通行规则说明，例如 Werewolf、Seer、Witch、Hunter、Guard、Villager。

    Args:
        role: 身份名，例如 Seer。
    """
    wanted = str(role or "").strip()
    for item in BOARDS.values():
        for name, character in item.characters.items():
            if wanted in (name, character.role):
                skill = character.skill or "无"
                return f"{name}（{character.camp}，技能：{skill}）：{character.describe}"
    known = sorted({name for item in BOARDS.values() for name in item.characters})
    return f"没有这个身份：{role}。现有身份：" + "、".join(known)


def _pick_board(board: str) -> tuple[str, Board] | None:
    """按 id、名字或人数挑板子；没给就用默认板子。空格不影响匹配。"""
    key = "".join(board.split())
    if not key:
        return board_id_of(DEFAULT_BOARD), DEFAULT_BOARD
    for board_id, item in BOARDS.items():
        names = {board_id, board_id.removesuffix("_board"), str(item.size)}
        label = "".join(BOARD_LABELS.get(board_id, "").split())
        if key in names or key == label or key.startswith(f"{item.size}人"):
            return board_id, item
    return None


@tool(parse_docstring=True)
def retrieve_similar_games(situation: str) -> str:
    """检索和当前对局形势相似的历史狼人杀对局，给玩家建议用。

    适用于：用户描述了当前对局的阶段、存活情况、自己的身份和情报、场上公开事件，
    想参考相似局怎么打的。检索的是真实对局录像库里相似片段 + 那一局的结局。

    Args:
        situation: 当前对局形势的自然语言描述，越具体越好。建议包含：
            阶段（如 Day 2 Daytime）、自己的座位号和身份、还活着谁、
            前面玩家的发言要点、自己面临的选择（发言/投票/夜间动作）。
    """
    query = (situation or "").strip()
    if not query:
        return "请先描述当前对局形势，再检索相似局。"
    text, hits = retrieve_similar(query)
    if not hits:
        return (
            "没有检索到相似的历史对局，可能是向量库还没建好或检索服务不可用。"
            "请检查 Werewolf-VectorDB 是否已经跑过 build_db.py，"
            "以及 .env 里 CHROMA_API_KEY/CHROMA_TENANT/CHROMA_DATABASE 是否配好。"
        )
    return (
        "以下是向量库里和当前形势相似的历史对局片段（按相似度排序），"
        "供你参考这些局里玩家是怎么发言、怎么投票、怎么用技能的，以及最终结局：\n\n"
        + text
    )


def get_chat_tools() -> list[BaseTool]:
    """网页版聊天机器人的工具集：查板子、查身份规则、检索相似历史对局。

    资料分两类：板子和身份规则在项目里（`werewolf_claw.boards`），不联网；
    历史对局片段在向量库里（`core.vector_retriever`），首次调用时才加载
    chromadb 和 sentence-transformers，没装这俩包时降级返回提示，不影响其它工具。
    """
    return [list_boards, board_detail, role_rule, retrieve_similar_games]


# ------------------------------------------------------------------ 通用的博弈工具


def get_tools(target: Any = None) -> list[BaseTool]:
    """给玩家 Agent 的工具集。

    `target` 是带着大屏和私有记忆的对象（玩家 Agent）：需要 `transcript(limit=...)`
    拿大屏、`notes` 记私有记忆。没传就只给基础工具。
    """

    @tool("read_board", parse_docstring=True)
    def read_board(limit: int = 30) -> str:
        """读大屏最近的消息（公开信息），用来看场上发生了什么。

        Args:
            limit: 读多少条，默认 30。
        """
        return _board(target, limit)

    @tool("search_statements", parse_docstring=True)
    def search_statements(seat: int) -> str:
        """查某个座位历史上的公开发言，用来复盘他的立场和票型。

        Args:
            seat: 座位号。
        """
        return _statements(target, seat)

    @tool("note", parse_docstring=True)
    def note(text: str) -> str:
        """把一条判断记进自己的私有记忆，别人看不到。

        Args:
            text: 要记住的内容。
        """
        return _note(target, text)

    basic: list[BaseTool] = [read_board, search_statements, note]
    if target is None:
        return basic

    # 推理这类「能力」也做成工具：模型想更新判断、看自己的情报时自己调
    @tool("reason", parse_docstring=True)
    def reason() -> str:
        """重新推理一遍：按大屏上的发言、票型加上自己的私有情报，更新每个座位的怀疑度。

        想改变判断时调用它。
        """
        return _reason(target)

    @tool("top_suspects", parse_docstring=True)
    def top_suspects(count: int = 3) -> str:
        """看自己推测表里最可疑的几个座位（推测身份、置信度、理由）。

        Args:
            count: 看几个，默认 3。
        """
        return _suspects(target, count)

    @tool("my_intel", parse_docstring=True)
    def my_intel() -> str:
        """看我自己收到的情报（例如 Seer 查到的阵营、Witch 看到的刀口）。"""
        return _intel(target)

    @tool("speak_position", parse_docstring=True)
    def speak_position() -> str:
        """看自己排在第几个发言、前面已经有哪些人发过言（决定发言策略用）。"""
        return _position(target)

    @tool("retrieve_similar", parse_docstring=True)
    def retrieve_similar(extra: str = "") -> str:
        """检索和当前对局形势相似的历史狼人杀对局片段，参考别人怎么发言、投票、用技能。

        会自动用你的座位、身份、当前阶段、场上存活、最可疑的人构造查询，不用自己写。
        想强调某些关键词（比如「被查杀」「刀口」「跳 Seer」）可以传 extra 补充。

        Args:
            extra: 额外想强调的关键词，可选。
        """
        return _retrieve_similar(target, extra)

    return [
        *basic,
        reason,
        top_suspects,
        my_intel,
        speak_position,
        retrieve_similar,
    ]


def _board(target: Any, limit: int = 30) -> str:
    """读大屏：只取公开通道，私聊（查验回执、狼队频道）不进这个工具。"""
    if target is None or not hasattr(target, "transcript"):
        return "没有大屏可读。"
    return target.transcript(limit=int(limit), channel=PUBLIC) or "大屏还没有内容。"


def _statements(target: Any, seat: int) -> str:
    inbox = getattr(target, "inbox", None) or []
    rows = [
        f"#{message.seq} {message.text}"
        for message in inbox
        if getattr(message, "kind", "") == "statement" and f"{seat} 号" in getattr(message, "text", "")
    ]
    return "\n".join(rows[-10:]) if rows else f"{seat} 号还没有发过言。"


def _note(target: Any, text: str) -> str:
    notes = getattr(target, "notes", None)
    if notes is None:
        return "没有私有记忆可写。"
    notes.append(str(text))
    return "已记下。"


def _reason(target: Any) -> str:
    """推理工具：调用玩家的推理，更新推测表，再把结果说回给模型。"""
    reason = getattr(target, "reason", None)
    if reason is None:
        return "没有可用的推理。"
    alive = tuple(getattr(target, "alive_list", ()) or ())
    if not alive:
        return "还不知道场上活着谁，先等大屏。"
    belief = reason(alive)
    # 和 ReasonNode 一致：推理出来的表要换回玩家身上，后面的工具/发言都读它
    if hasattr(target, "belief"):
        target.belief = belief
    lines = [
        f"{seat} 号：推测 {belief.guess(seat).role}（置信度 {belief.guess(seat).confidence:.2f}，"
        f"{belief.guess(seat).reason}）"
        for seat in sorted(alive)
        if seat != getattr(target, "seat", None)
    ]
    suspects = list(target.suspects(alive)) if hasattr(target, "suspects") else []
    top = suspects[0] if suspects else None
    head = f"最可疑：{top} 号。" if top is not None else "暂时没有明确目标。"
    return head + "\n" + "\n".join(lines) if lines else head


def _suspects(target: Any, count: int = 3) -> str:
    call = getattr(target, "suspects", None)
    if call is None:
        return "没有推测表。"
    seats = list(call())[: max(1, int(count))]
    if not seats:
        return "推测表里没有可怀疑的人。"
    belief = getattr(target, "belief", None)
    rows = []
    for seat in seats:
        guess = belief.guess(seat) if belief is not None else None
        if guess is None:
            rows.append(f"{seat} 号")
        else:
            rows.append(f"{seat} 号：{guess.role}（{guess.confidence:.2f}，{guess.reason}）")
    return "最可疑的依次是：" + "；".join(rows)


def _intel(target: Any) -> str:
    checks = getattr(target, "checks", None)
    if checks is None:
        return "没有情报。"
    rows = [f"{seat} 号：{camp}" for seat, camp in checks()]
    attacked = getattr(target, "attacked", None)
    if attacked is not None:
        rows.append(f"今晚被袭击的是 {attacked} 号")
    return "\n".join(rows) if rows else "我还没有收到任何情报。"


def _position(target: Any) -> str:
    context = getattr(target, "speak_context", None)
    if context is None:
        return "不知道发言位置。"
    position, earlier = context()
    return position + (f"已经发过言：{earlier}" if earlier else "")


def _retrieve_similar(target: Any, extra: str = "") -> str:
    """检索相似历史对局：用玩家当前状态自动构造查询文本。

    查询结构和向量库里 utterance 的 document 文本对齐（阶段、视角、意图、摘要），
    这样检索出来的相似片段才是「相似角色在相似阶段的相似处境」。
    """
    # 1. 用玩家当前状态拼查询
    seat = getattr(target, "seat", "?")
    role = getattr(target, "role", "未知")
    day = getattr(target, "day", 0)
    kind = getattr(target, "request_kind", "")
    alive = getattr(target, "alive_list", ()) or ()
    # 把当前请求类型翻成向量库里的阶段语义
    if kind == "发言":
        phase = f"Day {day} Daytime"
        action_hint = "公开发言"
    elif kind == "投票":
        phase = f"Day {day} Daytime"
        action_hint = "投票放逐"
    elif kind in ("技能", "出局技能"):
        phase = f"Day {day} Night"
        action_hint = "夜间技能"
    elif kind == "讨论":
        phase = f"Day {day} Night"
        action_hint = "队伍讨论"
    else:
        phase = f"Day {day}"
        action_hint = ""

    # 推测表里最可疑的几个人，作为查询的「意图」
    suspects_call = getattr(target, "suspects", None)
    suspect_hint = ""
    if suspects_call is not None:
        try:
            top = list(suspects_call())[:3]
            if top:
                suspect_hint = "、".join(f"{s} 号" for s in top)
        except Exception:
            pass

    # 自己的情报（查验结果、刀口），强化查询的处境
    intel_lines: list[str] = []
    checks = getattr(target, "checks", None)
    if checks is not None:
        try:
            for t, camp in checks()[-3:]:
                intel_lines.append(f"查验过 {t} 号是{camp}")
        except Exception:
            pass
    attacked = getattr(target, "attacked", None)
    if attacked is not None:
        intel_lines.append(f"今晚 {attacked} 号被刀")

    parts = [f"阶段：{phase}", f"视角：{seat} 号 {role}"]
    if alive:
        parts.append(f"存活：{'、'.join(str(s) for s in alive)}")
    if action_hint:
        parts.append(f"当前要做：{action_hint}")
    if suspect_hint:
        parts.append(f"最可疑：{suspect_hint}")
    if intel_lines:
        parts.append("情报：" + "；".join(intel_lines))
    extra = (extra or "").strip()
    if extra:
        parts.append(f"补充：{extra}")
    query = "\n".join(parts)

    # 2. 检索
    text, hits = retrieve_similar(query)
    if not hits:
        return (
            "没有检索到相似的历史对局片段。可能是向量库还没建好或检索服务不可用，"
            "先按自己的推理给出结果。"
        )
    return (
        "以下是向量库里和你当前处境相似的历史对局片段（按相似度排序），"
        "参考这些局里同角色在相似阶段是怎么发言、投票、用技能的，以及最终结局：\n\n"
        + text
    )
