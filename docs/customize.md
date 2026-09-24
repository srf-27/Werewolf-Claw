# 可自定义字段参考

这份文档列出常见的可调项在哪个文件、哪个符号上，改完怎么生效。路径都相对仓库根目录。

## 1. 对话行为

| 想改什么 | 位置 | 说明 |
| --- | --- | --- |
| 助手人设（网页版聊天 Agent） | `src/werewolf_claw/agents/prompts.py` 的 `CHAT_SYSTEM_PROMPT` | 聊天 Agent 拿它拼系统提示词，改完重启服务即可 |
| 助手人设（命令行等简单入口） | `src/werewolf_claw/core/conversation.py` 的 `SYSTEM_PROMPT` | `send()` / `edit_last()` / `regenerate()` 这几条不带工具的路径用它 |
| 「有哪些工具、什么时候该用」那一段 | `agents/prompts.py` 的 `TOOLS_SECTION` | 拼在聊天 Agent 的系统提示词后面 |
| 聊天 Agent 的流程（Node + Flow） | `agents/chat_agent.py` 的 `ChatAgent.build_flow()` | 输入 -> 推断要不要调工具 ->（需要就调工具）-> 回复；另有编辑、重新生成两条入口 |
| 聊天 Agent 能用的工具 | `src/werewolf_claw/tools/agent_tools.py` 的 `get_chat_tools()` | 默认是查板子（`list_boards` / `board_detail`）和查身份规则（`role_rule`），资料都在项目里，不联网 |
| 工具怎么声明 | 同一个文件里用 LangChain 的 `@tool` 装饰器（依赖 `langchain-core`） | 函数带类型标注 + Google 风格文档字符串，名字、说明、参数 schema 都由 `@tool` 推出来 |
| 采样温度 | `conversation.py` 的 `TEMPERATURE` | 默认 0.7，越高越随机 |
| 一轮问答拆成哪几步 | `conversation.py` 的 `open_turn()` / `ask()` / `answer_turn()` | 聊天 Agent 靠这三步把工具调用插在「写用户消息」和「写回回复」之间 |
| 一条回复最多重新生成几次 | `conversation.py` 的 `MAX_REGENERATE`（默认 5） | 前端会显示「重新生成 n/上限」 |
| 重新生成时要求模型先总结不足的提示词 | `conversation.py` 的 `REVISE_PROMPT` | 里面的 `{round}`、`{attempts}` 是占位符 |
| 重新生成结果的分段标记 | `conversation.py` 的 `split_revision()` | 默认按 `【不足】` / `【回答】` 拆分 |
| 领域错误 → HTTP 状态码的映射 | `src/werewolf_claw/app/server.py` 的 `to_http_error()` | 默认 422 / 409 / 502 |

## 2. 记忆与压缩

都在 `src/werewolf_claw/core/memory.py`：

| 想改什么 | 符号 | 默认值 |
| --- | --- | --- |
| 上下文上限（token） | `MAX_CONTEXT_TOKENS` | 128000 |
| 压缩触发比例 | `COMPRESS_THRESHOLD` | 0.9（到 90% 压缩） |
| 压缩后保留最近几条 | `KEEP_RECENT_MESSAGES` | 4 |
| 长期记忆条目上限（超过就合并） | `MAX_MEMORY_ENTRIES` | 20 |
| 「用户要求记住」的触发词 | `REMEMBER_MARKERS` | 记住 / 牢记 / 记下来 / 记一下 / 别忘了 / 永久记忆 / 长期记忆 / remember / keep in mind |
| 压缩摘要的提示词 | `SUMMARY_PROMPT` | — |
| 长期记忆合并的提示词 | `MEMORY_MERGE_PROMPT` | — |
| 会话标题的提示词 | `TITLE_PROMPT` | 只按用户发言总结，最多 12 字 |
| 导出文件格式标识 / 版本 | `EXPORT_FORMAT`、`EXPORT_VERSION` | `werewolf-claw-session` / 1 |
| 默认数据库路径 | `DEFAULT_DB_PATH` | `memory/chat.db`（相对当前工作目录） |
| 库路径环境变量 | `DB_PATH_ENV` + `default_db_path()` | `WEREWOLF_DB`；Web、命令行、脚本都用它解析，保证同一个库 |
| 库结构版本（改表结构时 +1） | `SCHEMA_VERSION` | 2 |
| SQLite 调优（日志模式、提交同步级别、等锁时间） | `Memory._tune()` | `journal_mode=WAL`、`synchronous=FULL`、`busy_timeout=5000` |
| 会话 id 规则 | `SESSION_ID_PATTERN`、`is_valid_session_id()` | 1-64 个非空白字符，不含 `/ \ ? # %`，不是 `.` / `..` |
| 新会话 id 格式 | `new_session_id()` | `chat-YYYYMMDD-HHMMSS-随机 4 位` |
| token 估算规则 | `estimate_tokens()` | 中文约 1.5 字一个 token |

每个会话还可以在构造 `Memory(...)` 时单独覆盖：`max_context_tokens`、`compress_threshold`、`keep_recent`、`max_memory_entries`、`db_path`。

## 3. 模型配置（多套）

配置写在仓库根目录的 `.env`（不会提交），键名定义在 `src/werewolf_claw/core/llm.py`：

| 键 | 说明 |
| --- | --- |
| `LLM_ACTIVE_PROFILE` | 当前生效的配置序号 |
| `LLM_PROFILE_<n>_NAME` | 第 n 套配置的名字（默认「模型配置一」） |
| `LLM_PROFILE_<n>_API_KEY` | 第 n 套的密钥 |
| `LLM_PROFILE_<n>_BASE_URL` | 第 n 套的接口地址，留空表示 OpenAI 官方 |
| `LLM_PROFILE_<n>_MODEL` | 第 n 套的模型名 |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `LLM_MODEL` / `LLM_PROFILE_NAME` | 当前生效那套的镜像键，手写单套配置时也可以用 |

相关的可调项：

| 想改什么 | 位置 | 默认值 |
| --- | --- | --- |
| 最多几套配置 | `llm.py` 的 `MAX_PROFILES` | 8 |
| 兜底模型名 | `llm.py` 的 `FALLBACK_MODEL` | `gpt-4o-mini` |
| 默认配置名 | `llm.py` 的 `DEFAULT_PROFILE_NAME` | 模型配置一 |
| 密钥打码规则 | `llm.py` 的 `mask_secret()` | 前 6 位 + 8 个星 + 后 4 位 |
| `.env` 查找顺序 | `llm.py` 的 `env_candidates()` | 仓库根目录 → 当前工作目录 |

改 `.env` 后不用重启：页面「设置 API」保存时会自动重新加载；手工改文件则重启一次、或在页面里保存一次即可。

## 4. 服务与接口

都在 `src/werewolf_claw/app/server.py`：

| 想改什么 | 位置 | 默认值 |
| --- | --- | --- |
| 监听地址 / 端口 | `HOST`、`PORT`，读环境变量 `WEREWOLF_HOST`、`WEREWOLF_PORT` | `127.0.0.1` / `8000` |
| 数据库路径 | `DB_PATH`，读环境变量 `WEREWOLF_DB` | `memory/chat.db` |
| 每页消息条数（接口默认值） | `DEFAULT_PAGE_SIZE` | 30 |
| 交互式文档路径 | `FastAPI(docs_url=...)` | `/api-docs` |
| CORS | 目前没有开启（只监听本机） | — |

接口清单和字段含义见 [api.md](api.md)。

## 5. 前端界面

静态资源在 `src/werewolf_claw/app/static/`：

| 想改什么 | 位置 |
| --- | --- |
| 头像路径 | `app.js` 顶部的 `AVATARS`（文件放 `static/avatars/`） |
| 图标 | `app.js` 的 `ICONS`（内联 SVG） |
| 首屏最少加载几条 | `app.js` 的 `MIN_PAGE_SIZE`（默认 20，实际按窗口高度算） |
| 主题 / 字体本地存储键 | `app.js` 的 `THEME_KEY`、`FONT_KEY`、`FONT_SIZE_KEY` |
| 字体库（浏览器本地） | `app.js` 的 `FONT_DB`（IndexedDB） |
| 配色、圆角、对话列宽、图标大小 | `style.css` 顶部 `:root` 变量：`--bg`、`--panel`、`--border`、`--text`、`--muted`、`--accent`、`--accent-soft`、`--bubble`、`--danger`、`--radius`、`--thread-width`、`--icon-size`、`--chat-font`、`--chat-font-size` |
| 夜间模式配色 | `style.css` 的 `body.dark` 变量块 |
| 导航戳（右栏问答标记）的宽度与折叠阈值 | `style.css` 的 `.rail` 与 `@media (max-width: 1100px)` |
| 分享卡片尺寸、边距、块宽上限 | `app.js` 的 `renderShareCard()`（`width`、`padding`、`maxBlockWidth`） |
| 分享图片文件名 | `app.js` 的 `safeFileName()`、`fileStamp()` |

头像和图标直接替换文件或改常量即可，刷新页面生效；字号和字体可以在设置里改，存在浏览器本地。

## 6. 文档、帮助与版本

| 想改什么 | 位置 |
| --- | --- |
| 接口文档 | `docs/api.md` |
| 页面里的使用帮助 | `src/werewolf_claw/app/static/help.html` |
| 关于页（版本、技术栈） | `src/werewolf_claw/app/static/about.html` |
| 版本号 | `src/werewolf_claw/__init__.py` 的 `__version__`（也会显示在 `/api/health` 和设置菜单里） |
| 项目元信息、依赖、入口 | `pyproject.toml` |

版本号两处要对齐：`__init__.py` 的 `__version__` 和 `pyproject.toml` 的 `project.version`。

## 7. 目录职责

| 目录 | 放什么 |
| --- | --- |
| `src/werewolf_claw/core/` | 基础实现：模型调用、记忆、一轮问答流程、节点、板子数据（`board.py`）、角色父类（`character.py`）、大屏、系统级、领域错误、可调默认值 |
| `src/werewolf_claw/boards/` | 具体板子：一个板子一个目录，里面是 `roles.py`（身份与阵营）和 `board.py`（具体板子类） |
| `src/werewolf_claw/characters/` | 角色实现：和 `boards/` 平级，一个身份一个类，可被多个板子复用 |
| `src/werewolf_claw/demos/` | 演示入口：网页版对局演示（跑真模型或纯规则） |
| `src/werewolf_claw/agents/` | Agent 层：每个 Agent 一条 Node + Flow（`chat_agent`、`judge_agent`、`player_agent`），只做编排；身份相关的实现不放这里 |
| `src/werewolf_claw/tools/` | Agent 的工具：用 LangChain `@tool` 声明（`get_chat_tools()` / `get_tools()`）、`ToolExecutor` 负责转格式和执行 |
| `src/werewolf_claw/app/` | 具体实现：HTTP 接口、请求响应模型、错误映射、前端静态资源 |
| `src/werewolf_claw/demo/` | 测试用样例（命令行版），正式代码不 import |
| `docs/` | 文档 |

新增功能时：能被多个入口复用的逻辑放 `core/`，把 `core/` 的能力串成一条 Node + Flow 的流程放 `agents/`，只服务某个入口的放 `app/`。

## 8. 对局的板子与组件

| 想改什么 | 位置 |
| --- | --- |
| 板子的数据：人数、身份分布、阵营分布、特殊身份技能、具体夜晚阶段 | `src/werewolf_claw/core/board.py` 的 `Board`，只有数据，没有实现 |
| 角色父类：`role` / `camp` / `skill` / `describe` 四个属性和一个技能方法 | `src/werewolf_claw/core/character.py` 的 `Character`（技能方法 `skill_action(player)`） |
| 默认板子（6 人标准板：2 狼 2 平民 1 预言家 1 守卫） | `src/werewolf_claw/boards/default_board/`：`roles.py` 的 `CAMP` 列表和 `ROLES` 表（身份 -> `RoleSpec(名字, 阵营, 技能)`，阵营分布从它派生）、`board.py` 具体板子类 |
| 角色实现（狼人 / 守卫 / 预言家 / 平民） | `src/werewolf_claw/characters/`，一个身份一个文件，例如 `wolf.py` 的 `WolfCharacter` |
| 新板子 | 在 `boards/` 下新建一个目录，照着 `default_board/` 写 `roles.py` 和 `board.py`，角色实现直接复用 `characters/` 里已有的类 |
| 发身份、夜间结算 | `src/werewolf_claw/agents/judge_agent.py` 的 `deal_roles()`、`JudgeAgent.resolve_night()` |
| 胜负判定（系统层） | `src/werewolf_claw/core/system.py` 的 `LocalSystem.check_winner()`：一方阵营全部出局才结束（狼人全死好人赢、好人全死狼人赢），不比人数；法官的 `check_finish()` 只是转调它 |
| 大屏与私聊通道 | `src/werewolf_claw/core/screen.py` 的 `Screen`；渲染待实现，在 `Screen.render()` |
| 昼夜、天数、存活数镜像、发言与投票的节奏 | `src/werewolf_claw/core/system.py` 的 `SystemProtocol` 与 `LocalSystem`（60s / 10s 计时待实现） |
| 玩家对外的接口 | `src/werewolf_claw/core/player.py` 的 `PlayerProtocol` |
| 法官的流程编排 | `src/werewolf_claw/agents/judge_agent.py` 的 `JudgeAgent` |
| 玩家的通用流程（所有身份共用） | `src/werewolf_claw/agents/player_agent.py` 的 `PlayerAgent` |

新增板子：在 `boards/` 下新建一个目录，里面只放 `roles.py` 和 `board.py`。

```
boards/my_board/
├── __init__.py         # 板子实例
├── roles.py            # ROLES 表（身份、阵营、技能），阵营分布从它派生
└── board.py            # 具体板子类

characters/             # 和 boards/ 平级，角色实现可被多个板子复用
├── __init__.py
├── wolf.py
├── guard.py
├── seer.py
└── villager.py
```

身份和阵营都在 `roles.py` 的一张表里：

```python
CAMP: list[str] = [
    "狼人阵营",
    "好人阵营",
]


@dataclass(frozen=True)
class RoleSpec:
    """一个身份的说明：名字、阵营、特殊技（普通身份没有技能）。"""

    # 名称
    name: str
    # 阵营
    camp: str
    # 技能
    skill: str | None = None


# 身份 -> 说明
ROLES: dict[str, RoleSpec] = {
    WOLF: RoleSpec("狼人", "狼人阵营", "袭击"),
    VILLAGER: RoleSpec("平民", "好人阵营"),
}

# 阵营分布：身份 -> 阵营，从 ROLES 派生，板子直接用它
ROLE_CAMP: dict[str, str] = {name: spec.camp for name, spec in ROLES.items()}
```

角色实现继承 `Character`，父类只有 `role` / `camp` / `skill` / `describe` 四个属性和
一个技能方法 `skill_action`；其余（什么时候问、怎么校验模型给的输出、回执、结算、发言、
投票）都在 `agents/` 里：

```python
class WolfCharacter(Character):
    """狼人：狼队共同决定袭击目标，可以刀好人、刀队友，也可以自刀。"""

    role = "狼人"
    camp = "狼人阵营"
    skill = "袭击"
    describe = "你是狼人，夜里和队友一起行动……"

    def skill_action(self, player: Any) -> dict[str, Any] | None:
        # 狼人可以自刀，所以候选里连自己和队友都在
        candidates = [player.seat, *player.others()]
        enemies = [seat for seat in player.others() if seat not in player.allies]
        return {
            "phase": self.role,
            "target": (enemies or candidates or [None])[0],
            "effect": "kill",
            "candidates": tuple(candidates),
        }
```

`describe` 是这个角色的规则说明（照着通行规则写），玩家会把它读进 prompt，模型和规则版
都照它走。技能方法拿到的 `player` 就是当前这位玩家，可以直接读它的 `seat` / `others()` /
`allies` / `checks()` / `last_target(效果)`；返回值是动作字典 `{"phase", "target",
"effect"}`，`effect` 说明效果算哪一类，法官按它结算（`kill` 是刀、`protect` 是保护、
`check` 是查验），模型只能选目标、不能改效果。想限住模型能选谁，就在返回值里多给一个
`candidates`（这一夜允许选的目标），玩家会用它校验模型输出，且不会写进对局记录。
没有技能的身份（平民）什么都不用覆盖：夜里不被叫醒，白天按通用说法发言。加身份就是
在 `characters/` 里加一个类，再在板子的 `ROLES` 里加一行、在 `night_phases` 里排进
夜晚阶段。

已实现的两个特殊规则可以照着抄：

- 守卫（`characters/guard.py`）：每晚守一个人，不能连着两晚守同一个人。做法是用
  `player.last_target("protect")` 读上一晚守了谁，把他从 `candidates` 里去掉。
- 狼人（`characters/wolf.py`）：可以自刀。做法是把 `player.seat` 也放进 `candidates`，
  规则版仍然优先挑队友之外的人。

## 9. 网页演示（demos/）

`src/werewolf_claw/demos/` 是一个能跑完整对局的网页演示：7 个 Agent（1 名法官 + 6 名玩家）
都用 `.env` 里的模型，跑在后台线程里，页面轮询显示大屏。

```bash
uv run uvicorn werewolf_claw.demos.web:app --port 8020
```

打开 <http://127.0.0.1:8020/> 就能开新对局；勾掉「用模型」是纯规则跑，不联网也能看流程。

| 文件 | 作用 |
| --- | --- |
| `demos/web.py` | FastAPI 应用：`POST /api/games` 开一局，`GET /api/games/{id}` 取快照（`?god=1` 带身份和私聊），`/` 是看板页面 |
| `demos/game.py` | 一局的运行器：发身份、发随机昵称、按板子建 `PlayerAgent`、建 `JudgeAgent`、后台线程跑完，给网页出快照 |
| `demos/llm_agents.py` | 把 `.env` 的模型接成 Agent 的入口：玩家的 `agent_chat()`、法官的 `judge_narrate()`，各自统计调用次数/耗时/失败 |
| `demos/static/` | 看板页面：左边对局栏、左右两列座位、中间大屏（含狼频道）、底部法官条，配色沿用聊天机器人（含深色模式） |

接口：

| 接口 | 作用 |
| --- | --- |
| `GET /api/boards` | 能选的板子：6 人标准板、12 人标准板（id、名字、人数、身份分布、夜晚阶段） |
| `GET /api/models` | `.env` 里的模型配置清单（不带密钥）+ 当前生效的那套 |
| `POST /api/games` | 开一局（`board`、`seed`、`max_days`、`model`、`profile`）；会把还在跑的老局停掉 |
| `GET /api/games` | 对局栏：id、板子、状态、天数、获胜方、是否被停 |
| `GET /api/games/{id}?god=1` | 某一局的快照；`god=1` 才带身份、私聊和法官私人库 |
| `POST /api/games/{id}/stop` | 把这一局算作结束：不再调模型，剩下的按规则跑完，状态保留 |
| `POST /api/games/{id}/pause`、`/resume` | 暂停 / 继续；暂停时计时器也停 |
| `POST /api/games/{id}/speed` | 倍速（0.5~8），压缩步骤之间的等待；2 倍以上连法官播报也不再叫模型 |
| `POST /api/games/{id}/seats/{seat}/takeover`、`/release`、`/input` | 人类接管一个座位：接管后这个 Agent 的“模型调用”改成等人输入，退出后换回模型继续玩 |

界面行为：

- 每个座位有一个随机昵称（同一局内不重复），座位卡只显示昵称、座位号和出局状态；身份徽章只在
  「上帝视角」或对局结束后出现，**技能不显示**，避免从技能反推身份。
- 天数和昼夜只在左上角的指示里显示，不再作为大屏播报发出去（法官只报「谁睁眼/闭眼」和结果）。
- 开局前有「房间」设置：选板子（6 人 / 12 人）和选模型（`.env` 里的哪一套配置，或纯规则）。
- 顶栏有暂停和倍速；座位卡上的「接管」由人来替这个 Agent 行动，输入框会显示当前被问到的
  问题和角色规则，「退出」后 Agent 换回模型入口、凭原来的收件箱和记忆接着玩。
- 法官播报渲染成居中的公告条，和玩家的聊天气泡分开；玩家发言、票型、狼频道各自一套样式。
- 左边对局栏列出所有对局，点一下切换；切走的那一局会被 `stop()`（算作结束），状态留在栏里，
  再点回来就是原来的进度。地址栏会记下当前对局（`#<id>`），刷新也回到同一局。
- 顶栏可切板子（6 人标准板 / 8 人板 / 5 人快板），座位、夜晚阶段、身份分布都跟着板子走。

要点：

- 法官只对 `opening`/`dawn`/`result`/`vote`/`elimination`/`continue`/`game_over` 这些正经播报
  调模型换说法，机械的「天黑请闭眼」直接用模板，省调用也省时间。
- 狼频道：法官把「狼人请睁眼，你们是 3 号、4 号」「X 号提议袭击 Y 号」和收尾的
  `今晚的目标 → Y 号` 都发给狼队（多人私聊），看板用虚线气泡把它标成狼频道；狼队因此在
  自己阶段结束时就知道了最终刀口，和 `resolve_night()` 用的是同一个判定（`decide_effect`）。
- 狼人先商量再投票：多人同夜的阶段里，法官先让每个人说一句意见（`PlayerAgent.team_talk`，
  一句话、进队伍频道），大家商量完再各自 `night_action` 投刀；轮数由 `judge_agent.TEAM_TALK_ROUNDS`
  控制，默认 1 轮。
- 12 人标准板多了两个角色：女巫（一瓶解药一瓶毒药，各一次；法官会在她的阶段把今晚的刀口
  私下告诉她，靠 `Board.informed` 声明）和猎人（被刀、被票出局时可以开枪，被毒死不能开枪）。
  相关 effect：`save`（救人）、`poison`（毒人）、`shoot`（开枪），法官统一在
  `JudgeAgent.resolve_night()` / `apply_deaths()` 里结算。
- 模型出错或返回不合格时，玩家退回规则版、法官退回模板，对局不会因为一次调用失败而中断，
  错误记在看板的 Agent 统计里。
- 大屏（`core.screen.Screen`）对局线程写、网页线程读，内部的加锁保证序号和列表不会读坏。
- 静态资源带 `Cache-Control: no-store`，改完看板刷新就能看到，不用清浏览器缓存；页面还会
  自动跟着最新一局切过去。
- 一局 6 人局大约 20 次模型调用、1 分钟左右（`deepseek-flash`，视网络而定）。
