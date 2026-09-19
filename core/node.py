"""节点与流程。

`Node` 是所有操作节点的父类：每个节点从共享的 `context` 读输入，把结果写回 `context`，
这样一条链上的节点不需要互相持有引用。

`Flow` 负责把节点串成一条链，按加入顺序依次执行。

示例：

    class LoadPlayers(Node):
        def run(self, context: Context) -> Context:
            context["players"] = load_players()
            return context

    class AssignRoles(Node):
        def run(self, context: Context) -> Context:
            context["roles"] = assign_roles(context["players"])
            return context

    flow = Flow(LoadPlayers(), AssignRoles())
    result = flow.run()

`Flow(*nodes)`、`flow >> node`、`node_a >> node_b` 三种写法都在做同一件事：接上一段链路。

注意 `node_a >> node_b` 的返回值是 `node_b`，所以 `Flow(a >> b)` 只会加入 b。
要把两个节点都放进链路，用 `Flow(a, b)` 或 `Flow() >> a >> b`。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

Context = dict[str, Any]


class NodeError(RuntimeError):
    """节点执行失败。保留出错节点与原始异常，便于定位链路中的失败点。"""

    def __init__(self, node: "Node", cause: BaseException) -> None:
        super().__init__(f"节点 {node.name} 执行失败: {cause}")
        self.node = node
        self.cause = cause


class Node(ABC):
    """操作节点父类。

    子类只需要实现 `run()`：读 `context`，写回结果，返回它。
    返回 `None` 等价于返回传入的 `context`。
    """

    def __init__(self, name: str | None = None) -> None:
        self.name = name or type(self).__name__
        self.next: Node | None = None

    @abstractmethod
    def run(self, context: Context) -> Context:
        """执行节点逻辑。"""

    def __call__(self, context: Context) -> Context:
        result = self.run(context)
        return context if result is None else result

    def connect(self, node: "Node") -> "Node":
        """把 `node` 接到本节点之后，返回 `node`，便于继续拼接。"""
        if not isinstance(node, Node):
            raise TypeError(f"{node!r} 不是 Node 实例")
        if node is self:
            raise ValueError("节点不能连接到自身")
        if self.next is not None:
            raise ValueError(f"节点 {self.name} 已经连接了 {self.next.name}")
        self.next = node
        return node

    def __rshift__(self, node: "Node") -> "Node":
        return self.connect(node)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r})"


class Flow:
    """把节点串成一条链并顺序执行。"""

    def __init__(self, *nodes: Node, name: str | None = None) -> None:
        self.name = name or type(self).__name__
        self.head: Node | None = None
        self.tail: Node | None = None
        for node in nodes:
            self.then(node)

    def then(self, node: Node) -> "Flow":
        """在链尾追加节点，返回 self，便于链式调用。"""
        if any(existing is node for existing in self):
            raise ValueError(f"节点 {node.name} 已在链路中，重复加入会形成环")
        if self.tail is None:
            self.head = node
        else:
            self.tail.connect(node)
        self.tail = node
        return self

    def __rshift__(self, node: Node) -> "Flow":
        return self.then(node)

    def __iter__(self) -> Iterator[Node]:
        node = self.head
        while node is not None:
            yield node
            node = node.next

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __repr__(self) -> str:
        return f"Flow(name={self.name!r}, nodes={[node.name for node in self]})"

    def run(self, context: Context | None = None) -> Context:
        """按顺序执行所有节点，返回最终 `context`。"""
        current: Context = {} if context is None else context
        for node in self:
            try:
                current = node(current)
            except NodeError:
                raise
            except Exception as exc:
                raise NodeError(node, exc) from exc
        return current
