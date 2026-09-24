"""Agent 层：每个 Agent 都由若干 Node 组成，各自有一条自己的 Flow。

- `chat_agent`：网页版聊天机器人。输入 -> 推断要不要调工具 ->（需要就调工具）-> 回复；
  另外两条入口是编辑（撤回上一轮后重新提问）和重新生成；
- `judge_agent`：法官。开场 -> 发身份 -> 夜里按固定顺序叫醒 -> 天亮公布 -> 发言 ->
  投票 -> 判胜负，循环到分出胜负；
- `player_agent`：玩家父类，所有身份共用一条 Flow。确认身份 -> 等待法官请求 ->
  读大屏 -> 推理（更新推测表）-> 决策 -> 发言 / 投票 / 夜间动作。

这一层只做编排，具体能力仍然在 `core`：节点流程用 `core.node`，模型调用用
`core.llm`，记忆用 `core.memory`，一轮问答的实现用 `core.conversation`；
板子数据在 `core.board`，角色父类在 `core.character`，大屏和消息在 `core.screen`，
昼夜、天数与发言/投票的节奏在 `core.system`；具体板子在 `werewolf_claw.boards`，
角色实现在和它平级的 `werewolf_claw.characters`。
"""
