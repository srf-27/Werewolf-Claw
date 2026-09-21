"""Agent 层：每个 Agent 都由若干 Node 组成，各自有一条自己的 Flow。

- `chatagent`：网页版聊天机器人。一轮问答 = 写入、调模型、写回、起标题；
- `judge_agent`：法官。发身份 -> 按天循环推进对局 -> 输出胜利者；
- `player_agent`：玩家。读取大屏 -> 推理 -> 决策 -> 表达 -> 投票 -> 反思 的闭环。

这一层只做编排，具体能力仍然在 `core`：节点流程用 `core.node`，模型调用用
`core.llm`，记忆用 `core.memory`，一轮问答的实现用 `core.conversation`。
"""
