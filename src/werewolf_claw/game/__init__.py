"""对局运行器：把 agents 和 core 的能力串成可以跑、可以看、可以接手的一局。

- `game.py`：一局的运行器（发身份、建 Agent、后台线程跑完、给网页快照）；
- `human.py`：人类接管一个座位；
- `llm_agents.py`：把 `.env` 的模型接成 Agent 的入口；
- `pace.py`：暂停、倍速和步骤之间的等待。

网页入口在 `app/game.py`（`/game` 页面 + `/api/game/*` 接口）。
"""
