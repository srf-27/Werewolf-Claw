# Werewolf-Claw 接口说明

聊天机器人的 HTTP 接口，由 FastAPI 提供（`src/werewolf_claw/app/server.py`），前端页面是同一进程托管的静态单页（`src/werewolf_claw/app/static/`）。

## 启动

```bash
uv sync                                            # 安装依赖
uv run uvicorn werewolf_claw.app.server:app --reload
# 或者
uv run python -m werewolf_claw.app.server
```

默认监听 `127.0.0.1:8000`：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `WEREWOLF_HOST` | `127.0.0.1` | 监听地址 |
| `WEREWOLF_PORT` | `8000` | 监听端口 |
| `WEREWOLF_DB` | `memory/chat.db` | SQLite 库路径，相对当前工作目录 |

| 路径 | 内容 |
| --- | --- |
| `/` | 首页，目前只有一个进聊天页的按钮 |
| `/chat` | 聊天页面（首页的按钮指向这里，聊天页左下角有回首页的按钮） |
| `/help` | 使用帮助页面（左下角问号按钮指向这里） |
| `/about` | 关于页面：版本号、当前模型、项目简介 |
| `/api-docs` | FastAPI 自动生成的交互式文档 |
| `/static/*` | 前端静态资源 |
| `/static/avatars/*.svg` | 对话头像 |

## 模型配置（多套）

配置统一由 `core.llm` 在导入时从**项目根目录的 `.env`** 读取，`.env` 的值覆盖同名系统环境变量，命令行 demo 和 Web 服务共用一份。

`.env` 里最多存 8 套配置（`MAX_PROFILES = 8`），命名规则：

```dotenv
LLM_ACTIVE_PROFILE=1

LLM_PROFILE_1_NAME=模型配置一
LLM_PROFILE_1_API_KEY=sk-xxxx
LLM_PROFILE_1_BASE_URL=https://api.deepseek.com/
LLM_PROFILE_1_MODEL=deepseek-flash

LLM_PROFILE_2_NAME=模型配置二
LLM_PROFILE_2_API_KEY=sk-yyyy
LLM_PROFILE_2_BASE_URL=https://api.openai.com/v1
LLM_PROFILE_2_MODEL=gpt-4o-mini
```

`LLM_ACTIVE_PROFILE` 指向当前生效的那套。服务启动时会把当前配置摊平到 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`LLM_MODEL` 这三个老键上，所以只想手写一套配置也能用，只写老键时会被当成「模型配置一」。

页面右上角「设置 API」可以新增、改名、切换、删除配置，保存即写回 `.env` 并立刻生效（不用重启）。密钥在页面上只显示打码结果。

## 通用约定

- 请求和响应都是 JSON。
- 时间字段是 ISO 8601 字符串，库里存 UTC，页面展示时转成本地时间。
- 会话数据存在 SQLite 的 `memory/chat.db`，按 `session_id` 隔离；会话 id 只在接口之间传递，页面上不显示。
- 接口无鉴权，只监听本机地址，不要直接暴露到公网。

错误响应统一是 FastAPI 的格式：

```json
{ "detail": "错误说明" }
```

| 状态码 | 含义 |
| --- | --- |
| 200 / 201 | 成功 / 创建成功 |
| 405 | 方法不对 |
| 409 | 状态不允许（没有可编辑的消息、没有可重新生成的回复、超过重新生成上限等） |
| 422 | 参数不合法（消息为空、标题为空、导入文件格式不对等） |
| 500 | 写 `.env` 失败 |
| 502 | 调用模型失败（密钥、网络、服务端报错等） |

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查，返回当前模型和配置名 |
| GET | `/api/sessions` | 会话列表（id 和标题） |
| POST | `/api/sessions` | 新建会话 |
| POST | `/api/sessions/pin` | 批量置顶 / 取消置顶 |
| POST | `/api/sessions/delete` | 批量删除会话 |
| GET | `/api/sessions/{id}` | 会话信息（标题、摘要、长期记忆、条数） |
| GET | `/api/sessions/{id}/messages` | 分页读消息，从最新往前翻 |
| GET | `/api/sessions/{id}/outline` | 每轮问答的摘要，给右侧导航用 |
| POST | `/api/sessions/{id}/messages` | 发一条消息 |
| POST | `/api/sessions/{id}/messages/edit` | 编辑最后一条消息（撤回这一轮后重发） |
| POST | `/api/sessions/{id}/messages/regenerate` | 重新生成最后一条回复 |
| PATCH | `/api/sessions/{id}` | 重命名会话（改过之后不再自动改名） |
| DELETE | `/api/sessions/{id}` | 删除会话 |
| GET | `/api/sessions/{id}/export` | 导出会话 JSON |
| POST | `/api/sessions/import` | 导入会话 JSON |
| GET | `/api/settings` | 读取全部模型配置（密钥打码） |
| PUT | `/api/settings` | 保存模型配置到 `.env` |

## GET /api/health

```json
{
  "status": "ok",
  "version": "0.1.0",
  "model": "deepseek-flash",
  "profile_name": "模型配置一"
}
```

`version` 来自 `werewolf_claw.__version__`，页面的「关于」页和左下角设置菜单里都显示它。

## GET /api/sessions

列出所有会话，最近更新过的排在前面。只有写过消息的会话才会出现。

```json
{
  "sessions": [
    {
      "id": "chat-20260920-101530-1a2b",
      "title": "首夜刀人策略",
      "pinned": true,
      "updated_at": "2026-09-20T02:30:00+00:00"
    }
  ]
}
```

`title` 一定不为空：自动总结过的用总结结果，还没总结过的用第一条用户消息兜底（最多 20 个字），一个字都没有的显示「空会话」。置顶的会话排在前面，其余按最近更新排序；页面用 `updated_at` 把会话分成「今天 / 昨天 / 7 天内 / 30 天内 / 年-月」几组。

## POST /api/sessions

新建会话，只生成 id，等第一条消息写进来才真正入库。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `session_id` | string | 否 | 指定会话 id；省略则按 `chat-YYYYMMDD-HHMMSS` 生成 |

会话 id 的规则：1-64 个字符，不能含空白和 `/ \ ? # %`，也不能是 `.` / `..`；不合规返回 422（带斜杠的 id 在 URL 里无法路由，建出来也打不开）。中文 id 允许。

```bash
curl -X POST http://127.0.0.1:8000/api/sessions -H "Content-Type: application/json" -d "{}"
```

响应（201）：

```json
{ "session_id": "chat-20260920-101530-1a2b" }
```

## POST /api/sessions/pin

批量置顶或取消置顶。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ids` | string[] | 要操作的会话 id，至少一个 |
| `pinned` | bool | `true` 置顶，`false` 取消置顶，默认 `true` |

```json
{ "updated": 2 }
```

## POST /api/sessions/delete

批量删除会话，消息、摘要、长期记忆一起删。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ids` | string[] | 要删除的会话 id，至少一个 |

```json
{ "deleted": 2, "requested": 2 }
```

`deleted` 是实际删掉的会话行数，`requested` 是请求里给的 id 数；从没写过消息的 id 本来就没入库，所以 `deleted` 可能小于 `requested`。

## GET /api/sessions/{id}

会话的元信息，不含消息正文。

```json
{
  "session_id": "game-1",
  "title": "第一晚该刀谁",
  "title_locked": false,
  "summary": "更早的对话摘要，没压缩过时为 null",
  "memories": ["请记住我喜欢用中文回答"],
  "message_count": 13,
  "compacted_count": 2
}
```

## GET /api/sessions/{id}/messages

分页读消息，从最新往前翻，返回的一页按时间正序排列。

| 查询参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `limit` | int | `30` | 这一页最多几条，1-200 |
| `before_seq` | int | 无 | 只取序号比它小的消息；不传就是最新的一页 |

```json
{
  "session_id": "game-1",
  "messages": [
    {
      "seq": 12,
      "role": "user",
      "content": "第一晚该刀谁",
      "compacted": false,
      "created_at": "2026-09-20T02:10:31+00:00",
      "regenerate_count": 0,
      "quote": null
    }
  ],
  "has_more": true,
  "message_count": 42
}
```

`regenerate_count` 是这条回复被重新生成过几次（用户消息恒为 0）；`quote` 是这条消息引用了谁，结构见发消息接口，没有引用时为 `null`。页面顶部的「更多历史」按钮会带上这一页最早那条的 `seq` 再请求一次，直到 `has_more` 为 false；页面上不再用滚动自动触发加载。

## POST /api/sessions/{id}/messages

发一条用户消息。服务端依次：写入用户消息、取该会话的上下文、调用模型、把回复写回记忆（顺便判断是否需要压缩）、第一轮结束后自动总结标题。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `text` | string | 是 | 用户这一轮说的话，不能为空 |
| `quote` | object | 否 | 引用某条消息，见下 |
| `quote.session_id` | string | 是 | 被引用消息所属的会话，必须等于路径里的 `session_id` |
| `quote.seq` | int | 是 | 被引用消息的序号 |

引用是**会话内**的：服务端会同时校验会话 id 和序号，号对不上或来自别的会话都返回 422，避免把别的会话的内容引用过来。

引用信息单独存在消息的 `extra` 里（正文仍然是用户自己说的话），返回时的结构是：

```json
{
  "seq": 5,
  "role": "user",
  "content": "用户这次的问题",
  "quote": { "session_id": "game-1", "seq": 2, "excerpt": "助手：更早那条回复的开头…" }
}
```

只有拼成发给模型的上下文时才把引用加回正文，形如：

```
> 引用 助手：更早那条回复的开头…

用户这次的问题
```

响应（201）：

```json
{
  "session_id": "game-1",
  "reply": "好的，我记住了。",
  "remembered": true,
  "compressed": false,
  "title": "第一晚该刀谁",
  "message_count": 15,
  "max_regenerate": 5,
  "messages": [
    { "seq": 14, "role": "user", "content": "请记住我习惯用中文回答", "compacted": false, "created_at": "...", "regenerate_count": 0 },
    { "seq": 15, "role": "assistant", "content": "好的，我记住了。", "compacted": false, "created_at": "...", "regenerate_count": 0 }
  ]
}
```

- `remembered`：是否命中长期记忆触发词（记住、牢记、记下来、记一下、别忘了、永久记忆、长期记忆、remember、keep in mind）。
- `compressed`：这一轮是否触发上下文压缩（上下文达到 `max_context_tokens` 的 90%）。
- `messages`：这一轮新增的两条消息，前端直接拿来替换掉临时显示的消息。

模型调用失败返回 502；如果等待期间这条消息被 `/messages/edit` 撤回，服务端会把这次回复丢掉并返回 409（页面此时已经不再等这个响应）。

## POST /api/sessions/{id}/messages/edit

编辑最后一条用户消息：服务端先删掉这条用户消息和它后面的助手回复（上下文和记忆里都不再保留），再用新内容重新提问，返回结构和发消息接口一致。

页面上点用户消息下的「编辑」（只有最近一条用户消息有这个按钮），保存时会先中断正在进行的思考请求，再调用这个接口。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `text` | string | 是 | 编辑后的内容 |

没有可编辑的消息时返回 409，内容为空返回 422。

## GET /api/sessions/{id}/outline

每轮问答的摘要，右侧导航条用它画标记；不带正文，所以整段会话都能覆盖（默认最多 500 轮、每条摘要 60 字）。

```json
{
  "session_id": "game-1",
  "rounds": [
    { "seq": 1, "user": "第一晚该刀谁", "assistant": "看发言和票型，优先刀…" }
  ]
}
```

页面点导航标记会跳到对应消息；那条还没加载时，页面会自动往上翻页去找。

## POST /api/sessions/{id}/messages/regenerate

重新生成最后一条助手回复，一条回复最多 5 次（`MAX_REGENERATE = 5`，响应里的 `max_regenerate`）。

每次都会把之前几次的回答交给模型，要求它先总结这些回答的不足，再给出改进后的回答；旧回答只留在数据库的 `extra` 字段里，**不会作为消息显示在对话中**，页面只显示「重新生成 n/5」。

```json
{
  "session_id": "game-1",
  "reply": "这次的回答更具体",
  "regenerate_count": 2,
  "max_regenerate": 5,
  "message": { "seq": 15, "role": "assistant", "content": "这次的回答更具体", "regenerate_count": 2, "...": "..." }
}
```

没有可重新生成的回复、或者已经用满 5 次时返回 409。

## PATCH /api/sessions/{id}

重命名会话。改过之后 `title_locked` 变成 `true`，服务端不会再自动覆盖这个标题。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 是 | 新标题，1-50 个字符 |

```json
{ "session_id": "game-1", "title": "我的狼人杀笔记", "title_locked": true }
```

## DELETE /api/sessions/{id}

删除会话的消息、摘要、长期记忆和标题。删完该会话会因为「没有消息」而从列表里消失。

```json
{ "session_id": "game-1", "deleted": true }
```

## GET /api/sessions/{id}/export

下载这个会话的完整 JSON（带 `Content-Disposition: attachment`）。

```json
{
  "format": "werewolf-claw-session",
  "version": 1,
  "exported_at": "2026-09-20T02:30:00+00:00",
  "session_id": "game-1",
  "title": "第一晚该刀谁",
  "title_locked": true,
  "summary": "更早对话的摘要",
  "memories": ["请记住我喜欢用中文回答"],
  "messages": [
    { "seq": 1, "role": "user", "content": "你好", "compacted": false, "created_at": "..." }
  ]
}
```

## POST /api/sessions/import

把导出文件的内容原样 POST 进来（请求体就是上面的 JSON），还原成一个会话。

- 原会话 id 在库里不存在时直接沿用，做到完全还原。
- 原会话 id 已存在时换一个新 id（原 id 加随机后缀），不会覆盖已有会话。

```bash
curl -X POST http://127.0.0.1:8000/api/sessions/import \
  -H "Content-Type: application/json" --data-binary @session.json
```

响应（201）：`{ "session_id": "game-1", "title": "第一晚该刀谁" }`

文件不是导出文件或没有消息时返回 422。

## GET /api/settings

```json
{
  "active": "1",
  "max_profiles": 8,
  "env_file": "D:\\repo-REPO\\Werewolf-Claw\\.env",
  "profiles": [
    {
      "id": "1",
      "name": "模型配置一",
      "api_key": "sk-013********c4a1",
      "has_api_key": true,
      "base_url": "https://api.deepseek.com/",
      "model": "deepseek-flash"
    }
  ]
}
```

## PUT /api/settings

保存全部配置并指定当前生效的一套，写回 `.env` 后立即生效。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `active` | string | 当前生效的配置 id，取列表里的 `id` |
| `profiles` | array | 全部配置，至少一套，最多 8 套 |
| `profiles[].id` | string \| null | 已有配置的 id；新增的传 null 或省略 |
| `profiles[].name` | string | 配置名称，空值回落成「模型配置N」 |
| `profiles[].api_key` | string | 新密钥；**留空表示沿用这套配置原来的密钥** |
| `profiles[].base_url` | string | 接口地址，留空表示用 OpenAI 官方地址 |
| `profiles[].model` | string | 模型名 |

```bash
curl -X PUT http://127.0.0.1:8000/api/settings -H "Content-Type: application/json" \
  -d "{\"active\":\"2\",\"profiles\":[{\"id\":\"1\",\"name\":\"模型配置一\",\"api_key\":\"\",\"base_url\":\"https://api.deepseek.com/\",\"model\":\"deepseek-flash\"},{\"id\":null,\"name\":\"模型配置二\",\"api_key\":\"sk-yyyy\",\"base_url\":\"https://api.openai.com/v1\",\"model\":\"gpt-4o-mini\"}]}"
```

响应和 `GET /api/settings` 相同。写入时会保留 `.env` 里其他键和注释，删掉被删除那套配置残留的 `LLM_PROFILE_n_*` 键。

## 头像与静态资源

头像放在 `src/werewolf_claw/app/static/avatars/`，页面通过下面的路径引用（`src/werewolf_claw/app/static/app.js` 顶部的 `AVATARS` 常量就是这份映射，改路径改这里即可）：

| 角色 | 文件路径 | 页面路径 |
| --- | --- | --- |
| 用户 | `src/werewolf_claw/app/static/avatars/user.svg` | `/static/avatars/user.svg` |
| 助手 | `src/werewolf_claw/app/static/avatars/assistant.svg` | `/static/avatars/assistant.svg` |
| 系统 | `src/werewolf_claw/app/static/avatars/system.svg` | `/static/avatars/system.svg` |
| 工具 | `src/werewolf_claw/app/static/avatars/tool.svg` | `/static/avatars/tool.svg` |

换头像直接替换同名 SVG 文件（建议 64×64），或者改 `AVATARS` 里的路径指向别的图片。

## 前端说明

页面在 `/chat`，纯静态资源，没有构建步骤，改 `src/werewolf_claw/app/static/` 下的文件刷新即可。
首页在 `/`，用的是同一份 `style.css`，并沿用聊天页存在浏览器里的夜间模式和字体设置。

- 整页不滚动，只有消息区滚动，输入框固定在底部；首次打开（当前会话没有消息）时，欢迎语和输入框作为一组居于页面中间，发出第一条消息后输入框回到页面底部。
- 发送后用户消息立刻显示在右侧，助手一侧先出现「正在思考…」，拿到回复后自动替换。
- 助手消息左侧有头像、不带气泡，用户消息是右侧浅色气泡；时间默认隐藏，鼠标悬浮到某条消息上时显示在该条消息上方。
- 消息操作是图标按钮，放在消息**下方**，大小约一个中文字符：用户消息下有复制、引用、编辑（编辑只出现在最近一条用户消息上）；助手消息下有复制、引用、重新生成，重新生成过会显示「重新生成 n/5」。
- 「引用」不会写进输入框，而是在输入框上方显示一条引用条（可点叉取消）；引用只在当前会话内有效，切换会话会自动清掉。
- 左侧只显示会话标题，不显示会话 id；按「置顶 / 今天 / 昨天 / 7 天内 / 30 天内 / 年-月」分组，置顶的带图钉标记排在最上面；右键呼出「重命名 / 置顶 / 取消置顶 / 删除会话」。
- 点左侧标题栏的多选图标才进入多选模式并出现操作条（图标按钮：置顶 / 取消置顶 / 删除 / 完成），平时整条操作栏隐藏。
- 对话正文限制在 860px 的居中栏里（`--thread-width`），右侧留出的空白正好给提示卡片用，提示不会压住对话内容。
- 各种提示（已复制、已置顶、已重新生成等）以右上角弹出消息的形式显示，顶栏下面开始向下排列，每条都带关闭按钮，也可以等它自动消失。
- 「引用」条只在真正引用后出现，输入框上方显示被引用内容的摘要，右侧叉号可以随时取消；发出后该条消息上方也会带一条可点击的引用条，点一下跳到被引用的原文并高亮（原文在更早的分页里时会自动再翻几页找）。
- 打开页面默认**新建一个对话**，历史会话都在左侧列表里，不会自动进到上一次的会话。
- 顶栏的「分享」会把当前对话渲染成 PNG 图片下载（本地用 canvas 画，不依赖任何外部服务）。
- 左下角设置菜单里的「字体设置」可以改字体族和字号，并支持导入 ttf / otf / woff 字体文件；导入的字体会存在浏览器本地（IndexedDB），下次打开还在。
- 历史消息先显示能填满窗口的一页，想看更早的点顶部「更多历史」。
- 顶部右侧按钮：设置 API、导出（下载当前会话 JSON）、导入（选择 JSON 还原会话）。
- 设置 API 是多套配置的卡片列表：每张卡片显示配置名首字母圆标、名称、接口地址、模型名和操作图标（使用 / 编辑 / 复制 / 删除），可以直接拖动卡片排序；点「编辑」在卡片里展开字段，改完点对勾收起。
- 左下角是设置入口：齿轮按钮显示当前配置名，点开有「模型配置 / 夜间模式 / 使用帮助 / 关于（带版本号）」；右侧问号按钮直接打开 `/help`。夜间模式记在浏览器本地，刷新后仍然生效。

## 和命令行 demo 的关系

`src/werewolf_claw/demo/chatbot.py` 是命令行版，页面是它的 Web 版，两者共用 `core/memory.py` 的存储和 `core/llm.py` 的配置，所以同一个会话先用命令行聊、再用页面接着聊也没问题。
