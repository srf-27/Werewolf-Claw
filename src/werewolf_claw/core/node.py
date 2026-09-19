"""节点与流程。

节点是同步的：`exec(payload)` 处理输入，返回 `(action, next_payload)`。
`action` 决定下一步走哪个后继节点，`Flow` 从起点开始按 action 依次执行，
走到没有后继节点的 action 就结束。

跨节点共享的数据放在模块级 `shared` 字典里，payload 只传当前这一步需要的东西。

示例：

    class QueryNode(Node):
        def exec(self, payload):
            return "search", str(payload)

    class SearchNode(Node):
        def exec(self, payload):
            return "summarize", do_search(str(payload))

    class SummarizeNode(Node):
        def exec(self, payload):
            return "default", call_llm_simple(f"总结：{payload}")

    query, search, summarize = QueryNode(), SearchNode(), SummarizeNode()
    query - "search" >> search
    search - "summarize" >> summarize

    action, result = Flow(query).run("python asyncio 最佳实践")

`node >> other` 把 other 注册为当前 action 的后继节点；`node - "action"` 设置当前
action，所以 `a - "x" >> b` 读作“a 在 x 分支上连到 b”。不写 `- "action"` 时 action
是 `default`，因此 `a >> b` 连的是默认分支。

结束状态：节点返回的 action 没有对应后继节点时，`Flow.run()` 返回该 action 和当前
payload。约定最后一个节点返回 `DEFAULT_ACTION`，便于调用方判断流程是否正常收尾。
"""

from __future__ import annotations

import time
from typing import Any

DEFAULT_ACTION = "default"

# 跨节点共享的数据。节点直接读写它，避免把大对象塞进 payload。
shared: dict[str, Any] = {}


class Node:
    """同步节点：`exec(payload)` 返回 `(action, next_payload)`，失败可重试。"""

    def __init__(self, max_retries: int = 1, wait: float = 0) -> None:
        # 名字沿用 max_retries，但它是总尝试次数：1 表示不重试，2 表示最多再试 1 次。
        if max_retries < 1:
            raise ValueError("max_retries 是总尝试次数，至少为 1")
        self.successors: dict[str, Node] = {}
        self._action: str = DEFAULT_ACTION
        self.max_retries = max_retries
        self.wait = wait

    def exec(self, payload: Any) -> tuple[str, Any]:
        """处理 payload，返回 (action, next_payload)。子类必须实现。"""
        raise NotImplementedError

    def _exec(self, payload: Any) -> tuple[str, Any]:
        """带重试地调用 exec，次数用尽后抛出最后一次的异常。"""
        for cur_retry in range(self.max_retries):
            try:
                return self.exec(payload)
            except Exception:
                if cur_retry == self.max_retries - 1:
                    raise
                if self.wait > 0:
                    time.sleep(self.wait)
        raise RuntimeError("Unexpected error in Node._exec")

    def __rshift__(self, other: Node) -> Node:
        """把 other 注册为当前 action 的后继节点，然后把 action 复位为 default。"""
        self.successors[self._action] = other
        self._action = DEFAULT_ACTION
        return other

    def __sub__(self, action: str) -> Node:
        """设置下一次 `>>` 使用的 action。空字符串按 default 处理。"""
        if not isinstance(action, str):
            raise TypeError("Action must be a string")
        self._action = action or DEFAULT_ACTION
        return self

    def __repr__(self) -> str:
        return f"{type(self).__name__}(actions={sorted(self.successors)})"


class Flow:
    """同步编排器：按节点返回的 action 依次执行。"""

    def __init__(self, start: Node | None = None) -> None:
        self.start = start

    def run(self, payload: Any = None) -> tuple[str, Any]:
        """从 start 开始执行，返回最后一步的 (action, payload)。"""
        curr = self.start
        last_action = DEFAULT_ACTION
        while curr:
            last_action, payload = curr._exec(payload)
            curr = curr.successors.get(last_action)
        return last_action, payload

    def __repr__(self) -> str:
        return f"Flow(start={self.start!r})"
