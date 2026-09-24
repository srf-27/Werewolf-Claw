# Werewolf-Claw

基于 LLM Agent 的狼人杀对局项目：让多个 AI Agent（1 名法官 + 多名玩家）在网页大屏上跑完一整局狼人杀，同时自带一个支持长期记忆与工具调用的聊天机器人。

底层不用重型 Agent 框架，只用 LangChain 的 `@tool` 声明工具，其余编排全部由自己实现的 Node + Flow 完成；任何 OpenAI 兼容接口（DeepSeek、OpenAI、本地模型等）都能当对局引擎。

## 功能特性

- **完整对局**：法官按板子发身份、夜晚按固定顺序叫醒、天亮公布结果、白天发言投票、判定胜负，一局跑到底。
- **多模型配置**：`.env` 里最多存 8 套模型配置，网页上可新增、切换、排序、删除，保存即生效，还能给每个座位单独指定模型。
- **人类接管**：对局进行中可以把任意座位接管给真人操作，退出后 Agent 带着原有记忆继续玩。
- **对局控制**：暂停 / 继续、0.5~8 倍速、中途停止、导出对局 JSON。
- **聊天机器人**：独立聊天页，支持多会话、置顶、重命名、导入导出、消息引用、编辑重发、重新生成（带历史不足总结）。
- **长期记忆与上下文压缩**：用户说「记住…」时写入长期记忆；上下文到达上限 90% 时自动压缩成摘要，SQLite 持久化。
- **向量检索（可选）**：对接 Werewolf-VectorDB 的 Chroma 向量库，按当前对局形势检索相似历史对局片段给 Agent 参考；没配置就自动降级，不影响对局。
- **纯规则模式**：不联网、不调模型也能跑完整流程，方便验证和演示。

## 技术栈

| 组件 | 说明 |
| --- | --- |
| Python | >= 3.13，包管理与运行用 [uv](https://docs.astral.sh/uv/) |
| FastAPI + Uvicorn | Web 后端与静态资源托管 |
| LangChain Core | 仅用 `@tool` 声明工具；编排用自研 Node + Flow |
| OpenAI SDK | 调用任意 OpenAI 兼容接口 |
| SQLite | 会话、消息、长期记忆、对局记录持久化 |
| Chroma（可选） | 历史对局向量检索，依赖 Werewolf-VectorDB 项目 |
| 原生 HTML/CSS/JS | 前端无构建步骤，改文件刷新即生效 |

## 快速开始

### 1. 环境要求

- Python >= 3.13
- [uv](https://docs.astral.sh/uv/)（`pip install uv` 或参考官方安装方式）

### 2. 安装依赖

```bash
git clone https://github.com/srf-27/Werewolf-Claw.git
cd Werewolf-Claw
uv sync
```

### 3. 配置模型

复制 `.env.example` 为 `.env`，填入自己的密钥：

```dotenv
LLM_ACTIVE_PROFILE=1

LLM_PROFILE_1_NAME=模型配置一
LLM_PROFILE_1_API_KEY=sk-xxxx
LLM_PROFILE_1_BASE_URL=https://api.deepseek.com/
LLM_PROFILE_1_MODEL=deepseek-chat
```

- `BASE_URL` 支持任意 OpenAI 兼容接口，留空表示 OpenAI 官方地址。
- 最多 8 套配置（`LLM_PROFILE_2_NAME=...` 依次编号），`LLM_ACTIVE_PROFILE` 指定当前生效的一套；只想配一套也可以直接写 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `LLM_MODEL` 三个老键。
- 向量检索是可选功能，不配 `CHROMA_*` 时自动降级；需要时参考 `.env.example` 里的注释，凭证也可以放在隔壁 `Werewolf-VectorDB/.env` 里。

### 4. 启动

```bash
uv run uvicorn werewolf_claw.app.server:app --reload
```

打开 <http://127.0.0.1:8000/>：

| 页面 | 路径 | 说明 |
| --- | --- | --- |
| 首页 | `/` | 入口导航 |
| 聊天页 | `/chat` | 聊天机器人：多会话、引用、重新生成、导入导出、模型配置管理 |
| 对局页 | `/game` | 狼人杀大屏：开新对局、上帝视角、人类接管、暂停倍速 |
| 使用帮助 | `/help` | 页面操作说明 |
| 关于 | `/about` | 版本号、当前模型、项目简介 |
| 接口文档 | `/api-docs` | FastAPI 自动生成的交互式文档 |

服务监听地址由环境变量控制：`WEREWOLF_HOST`（默认 `127.0.0.1`）、`WEREWOLF_PORT`（默认 `8000`）、`WEREWOLF_DB`（SQLite 路径，默认 `memory/chat.db`）。接口无鉴权，只监听本机，不要直接暴露到公网。

### 5. 命令行聊天机器人

```bash
uv run python -m werewolf_claw.demos.chatbot          # 启动后先问要不要进旧会话
uv run python -m werewolf_claw.demos.chatbot game-1   # 直接进指定会话
```

和网页版共用同一个数据库与模型配置，命令行聊到一半换网页接着聊也没问题。聊天中输入 `history` 看当前会话历史，`sessions` 看所有会话，`exit` 退出。

### 6. 跑一局对局

1. 打开 `/game`，选择板子（当前内置 9 人标准板）和模型配置，或勾掉「用模型」纯规则跑。
2. 点击开局，7 个 Agent（1 法官 + 6 玩家，按板子人数）在后台线程跑对局，页面轮询刷新大屏。
3. 顶栏可以暂停 / 继续 / 调倍速；座位卡上点「接管」由人来替这个 Agent 行动，「退出」后换回模型继续。
4. 切换「上帝视角」可看身份徽章和狼频道私聊；对局可导出 JSON。

一局 9 人局大约 20~40 次模型调用，1~3 分钟（视模型与网络而定）。模型调用失败时该次动作自动退回规则版，对局不会中断。

## 项目结构

```
Werewolf-Claw/
├── src/werewolf_claw/
│   ├── core/                  # 基础实现层（不依赖 FastAPI，可被任意入口复用）
│   │   ├── node.py            #   Node + Flow：节点流程引擎
│   │   ├── llm.py             #   模型配置：.env 多套配置的读写、打码、生效切换
│   │   ├── conversation.py    #   一轮问答：open_turn / ask / answer_turn、重新生成、压缩
│   │   ├── memory.py          #   SQLite 存储：会话、消息、长期记忆、标题、导入导出
│   │   ├── board.py           #   Board 数据类：人数、身份分布、阵营、夜晚阶段
│   │   ├── character.py       #   Character 角色父类：role / camp / skill / skill_action
│   │   ├── screen.py          #   大屏与私聊通道：消息记账、可见性判定
│   │   ├── system.py          #   系统级：昼夜天数、存活镜像、发言投票节奏
│   │   ├── player.py          #   PlayerProtocol：玩家对外的接口
│   │   ├── match.py           #   对局记录存储
│   │   └── vector_retriever.py#   Chroma 向量检索客户端（可选，失败自动降级）
│   ├── agents/                # Agent 编排层：每个 Agent 一条 Node + Flow
│   │   ├── chat_agent.py      #   聊天 Agent：输入 -> 推断工具 ->（调工具）-> 回复
│   │   ├── judge_agent.py     #   法官：发身份、夜晚叫醒、结算、白天流程、胜负判定
│   │   ├── player_agent.py    #   玩家父类：确认身份 -> 等请求 -> 读大屏 -> 推理 -> 决策
│   │   └── prompts.py         #   各 Agent 的系统提示词
│   ├── boards/                # 具体板子：一个板子一个目录
│   │   ├── default_board/     #   9 人标准板：3 狼 3 民 + 预言家 / 女巫 / 猎人
│   │   └── standard12_board/  #   12 人标准板：4 狼 4 民 + 预女猎守（已从可选列表移除）
│   ├── characters/            # 角色实现：一个身份一个类，可被多个板子复用
│   │   ├── wolf.py            #   狼人（可自刀，先商量再投刀）
│   │   ├── seer.py            #   预言家（查验）
│   │   ├── witch.py           #   女巫（解药 / 毒药各一瓶，法官私下通报刀口）
│   │   ├── hunter.py          #   猎人（出局开枪，被毒不能开枪）
│   │   ├── guard.py           #   守卫（不能连守同一人）
│   │   └── villager.py        #   平民（夜间不被叫醒）
│   ├── tools/                 # Agent 工具
│   │   ├── agent_tools.py     #   LangChain @tool：查板子、查身份规则；ToolExecutor
│   │   └── skill_loader.py    #   技能加载
│   ├── game/                  # 对局运行器
│   │   ├── game.py            #   一局的运行器：发身份、建 Agent、后台线程、快照
│   │   ├── llm_agents.py      #   把 .env 的模型接成 Agent 入口，统计调用次数与失败
│   │   ├── human.py           #   人类接管一个座位：对局线程等网页提交答案
│   │   └── pace.py            #   暂停、倍速、步骤间等待
│   ├── app/                   # HTTP 层 + 前端静态资源
│   │   ├── server.py          #   聊天相关接口（/api/*）与页面路由
│   │   ├── game.py            #   对局接口（/api/game/*）与 /game 页面
│   │   └── static/            #   前端：home / chat / game / help / about 五个页面
│   └── demos/
│       └── chatbot.py         #   命令行聊天机器人（Node + Flow 组链路）
├── tests/                     # unittest 单测：法官夜间顺序、平票、空刀、玩家流程
├── docs/
│   ├── api.md                 # 接口说明（聊天相关接口的完整字段说明）
│   └── customize.md           # 可自定义字段参考（想改什么去哪个文件改哪个符号）
├── pyproject.toml             # 项目元信息、依赖、入口
└── .env.example               # 环境变量模板
```

### 分层原则

能被多个入口（Web、命令行、脚本）复用且与传输方式无关的逻辑放 `core/`；把 `core/` 的能力串成一条 Node + Flow 的流程放 `agents/`；只服务某个具体入口的（HTTP 校验、静态页面、运行器细节）放 `app/` 和 `game/`。板子只放数据与登记角色，角色实现与板子解耦，新增板子照抄 `default_board/` 即可。

## 架构说明

### 聊天 Agent 的流程

```
输入 -"回复"-> 推断是否需要调用工具 -"需要"-> 调用工具 -> 回复
                                 -"不需要"-------------> 回复
    -"编辑"-> 编辑（撤回上一轮后重新提问）-> 推断
    -"重新生成"-> 重新生成（总结历次不足）-> 回复
```

工具（查板子、查身份规则）只参与当轮，不写进会话记录。

### 对局的流程

```
法官开场 -> 发身份 -> 夜晚（按板子阶段依次叫醒：狼人 -> 预言家 -> 女巫 -> 守卫 -> 猎人）
        -> 天亮公布 -> 遗言 -> 白天发言 -> 投票 -> 放逐 -> 判胜负 -> 循环到分出胜负
```

- 所有消息走 `Screen` 的大屏（公开）和私聊（定向）两条通道，玩家收件箱按序号合并去重，信息隔离只靠 `Message.visible_to()` 一处判定。
- 狼队夜晚先在队伍频道商量（轮数可调），再各自投刀；法官把最终刀口同步给狼队。
- 技能结算统一由法官按动作字典里的 `effect`（kill / protect / check / save / poison / shoot）执行，模型只能选目标、不能改效果；玩家用 `candidates` 校验模型输出。
- 胜负判定在 `core/system.py`：一方阵营全部出局才结束，不比人数。

## 接口一览

聊天相关接口（完整字段说明见 [docs/api.md](docs/api.md)）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查，返回版本与当前模型 |
| GET / POST | `/api/sessions` | 会话列表 / 新建会话 |
| POST | `/api/sessions/pin` `/api/sessions/delete` | 批量置顶 / 批量删除 |
| GET / PATCH / DELETE | `/api/sessions/{id}` | 会话信息 / 重命名 / 删除 |
| GET / POST | `/api/sessions/{id}/messages` | 分页读消息 / 发消息 |
| POST | `/api/sessions/{id}/messages/edit` | 编辑最后一条用户消息 |
| POST | `/api/sessions/{id}/messages/regenerate` | 重新生成回复（上限 5 次） |
| GET | `/api/sessions/{id}/outline` | 每轮问答摘要（右侧导航用） |
| GET / POST | `/api/sessions/{id}/export` `/api/sessions/import` | 导出 / 导入会话 JSON |
| GET / PUT | `/api/settings` | 读 / 写模型配置（写回 `.env` 立即生效） |

对局相关接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/game/boards` | 可选板子及身份分布 |
| GET | `/api/game/models` | 模型配置清单（不带密钥） |
| POST | `/api/game/games` | 开新对局（板子、种子、天数上限、模型、每座位配置、人类座位） |
| GET | `/api/game/games` `/api/game/games/{id}` | 对局列表 / 某局快照（`?god=1` 上帝视角） |
| POST | `/api/game/games/{id}/stop` `/pause` `/resume` `/speed` | 停止 / 暂停 / 继续 / 倍速 |
| POST | `/api/game/games/{id}/seats/{seat}/takeover` `/release` `/input` | 人类接管 / 退出 / 提交输入 |
| GET | `/api/game/games/{id}/seats/{seat}/memory` | 查看某座位的私有记忆 |
| POST | `/api/game/games/{id}/seats/{seat}/advice` | 让顾问给该座位出主意 |
| GET | `/api/game/games/{id}/export` | 导出对局 JSON |
| DELETE | `/api/game/games/{id}` | 删除对局 |

## 可自定义项

想改提示词、温度、压缩阈值、重新生成上限、板子、角色规则、配色、头像等，都有一张「想改什么 -> 改哪个文件哪个符号」的对照表，见 [docs/customize.md](docs/customize.md)。常用几项：

| 想改什么 | 位置 |
| --- | --- |
| 聊天助手人设 | `agents/prompts.py` 的 `CHAT_SYSTEM_PROMPT` |
| 采样温度 | `core/conversation.py` 的 `TEMPERATURE` |
| 上下文压缩阈值 | `core/memory.py` 的 `COMPRESS_THRESHOLD` |
| 新板子 | `boards/` 下新建目录，写 `roles.py` + `board.py`，角色复用 `characters/` |
| 新角色 | `characters/` 下加一个 `Character` 子类，板子 `ROLES` 表登记即可 |
| 前端配色 / 列宽 | `app/static/style.css` 顶部 `:root` 变量 |

## 测试

```bash
uv run python -m unittest discover -s tests
```

覆盖法官 Agent 的夜间顺序、平票处理、空刀、昨夜名单、随机种子，以及玩家 Agent 的通用流程。

## 文档索引

- [docs/api.md](docs/api.md)：聊天相关 HTTP 接口的完整说明（字段、示例、错误码）。
- [docs/customize.md](docs/customize.md)：全部可自定义字段参考，含新增板子 / 角色的写法。
- `/help` 与 `/about`：运行中的服务自带的页面。
