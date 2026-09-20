# 可自定义字段参考

这份文档列出常见的可调项在哪个文件、哪个符号上，改完怎么生效。路径都相对仓库根目录。

## 1. 对话行为

| 想改什么 | 位置 | 说明 |
| --- | --- | --- |
| 系统提示词（助手人设） | `src/werewolf_claw/core/conversation.py` 的 `SYSTEM_PROMPT` | 所有入口共用，改完重启服务即可 |
| 采样温度 | `conversation.py` 的 `_complete()` 里 `temperature=0.7` | 越高越随机 |
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
| `src/werewolf_claw/core/` | 基础实现：模型调用、记忆、一轮问答流程、节点、领域错误、可调默认值 |
| `src/werewolf_claw/app/` | 具体实现：HTTP 接口、请求响应模型、错误映射、前端静态资源 |
| `src/werewolf_claw/demo/` | 测试用样例（命令行版），正式代码不 import |
| `docs/` | 文档 |

新增功能时：能被多个入口复用的逻辑放 `core/`，只服务某个入口的放 `app/`。
