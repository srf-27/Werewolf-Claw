"""Web 后端：把 core 的记忆、节点和 LLM 能力包成 HTTP 接口，给 app/static 的前端用。

启动：

    uv run uvicorn werewolf_claw.app.server:app --reload
    uv run python -m werewolf_claw.app.server

页面在 http://127.0.0.1:8000/ ，交互式接口文档在 http://127.0.0.1:8000/api-docs ，
接口的文字说明见 docs/api.md。会话数据存在 memory/chat.db，和命令行 demo 共用；
模型配置统一由 core.llm 从项目根目录的 .env 读取，设置页保存的也是那个文件。

环境变量：`WEREWOLF_DB`（库文件路径）、`WEREWOLF_HOST`、`WEREWOLF_PORT`。
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from werewolf_claw.core import conversation
from werewolf_claw.core.llm import (
    MAX_PROFILES,
    active_profile_id,
    default_model,
    env_path,
    list_profiles,
    mask_secret,
    profile_name,
    save_profiles,
)
from werewolf_claw.core.memory import (
    Memory,
    default_db_path,
    is_valid_session_id,
    new_session_id,
)
from werewolf_claw import __version__

STATIC_DIR = Path(__file__).parent / "static"

DB_PATH = default_db_path()
HOST = os.environ.get("WEREWOLF_HOST", "127.0.0.1")
PORT = int(os.environ.get("WEREWOLF_PORT", "8000"))

# 只用来打开库、列会话，不写消息，所以不会出现在会话列表里。
LIST_ONLY_SESSION_ID = "__list_sessions__"

# 每次加载的消息条数，前端会按窗口高度给出具体值。
DEFAULT_PAGE_SIZE = 30


class NewSession(BaseModel):
    """新建会话的请求体。"""

    session_id: str | None = Field(
        default=None,
        description="指定会话 id；省略则自动生成",
    )


class QuoteRef(BaseModel):
    """引用某条消息：会话 id + 消息序号，两者都要对得上才允许。"""

    session_id: str = Field(description="被引用消息所属的会话 id")
    seq: int = Field(ge=1, description="被引用消息的序号")


class NewMessage(BaseModel):
    """发消息的请求体。"""

    text: str = Field(min_length=1, description="用户这一轮说的话")
    quote: QuoteRef | None = Field(
        default=None,
        description="引用哪条消息；必须是当前会话里的消息，跨会话引用会被拒绝",
    )


class SessionIds(BaseModel):
    """批量操作会话的请求体。"""

    ids: list[str] = Field(min_length=1, description="要操作的会话 id 列表")
    pinned: bool = Field(default=True, description="置顶还是取消置顶")


class RenameSession(BaseModel):
    """重命名会话的请求体。"""

    title: str = Field(min_length=1, max_length=50, description="新的会话标题")


class ProfileIn(BaseModel):
    """一套模型配置。"""

    id: str | None = Field(default=None, description="配置 id；新增的配置可以不填")
    name: str = Field(default="", description="配置名称，例如「模型配置一」")
    api_key: str = Field(default="", description="新的密钥；留空表示沿用这套配置原来的密钥")
    base_url: str = Field(default="", description="OpenAI 兼容接口地址，留空表示用官方地址")
    model: str = Field(default="", description="模型名")


class SettingsIn(BaseModel):
    """保存多套模型配置的请求体。"""

    active: str | None = Field(default=None, description="当前生效的配置 id")
    profiles: list[ProfileIn] = Field(default_factory=list, description="全部配置，至少一套")


app = FastAPI(
    title="Werewolf-Claw Chatbot",
    version="0.1.0",
    description="带记忆和会话隔离的聊天机器人接口，说明见仓库 docs/api.md。",
    docs_url="/api-docs",
    redoc_url=None,
)


@contextmanager
def session_memory(session_id: str) -> Iterator[Memory]:
    """每个请求开一个连接，用完就关，避免长连接带来的锁问题。"""
    if not is_valid_session_id(session_id):
        raise HTTPException(
            status_code=422,
            detail="会话 id 只能包含 1-64 个非空白字符，且不能有 / \\ ? # %",
        )
    memory = Memory(session_id, db_path=DB_PATH)
    try:
        yield memory
    finally:
        memory.close()


def to_quote(quote: QuoteRef | None) -> conversation.Quote | None:
    """请求模型转成 core 的引用对象。"""
    return conversation.Quote(session_id=quote.session_id, seq=quote.seq) if quote else None


def turn_payload(memory: Memory, result: conversation.TurnResult) -> dict[str, Any]:
    """把 core 的一轮结果拼成接口响应。"""
    return {
        "session_id": memory.session_id,
        "reply": result.reply,
        "remembered": result.remembered,
        "compressed": result.compressed,
        "title": result.title,
        "message_count": memory.message_count(),
        "messages": result.messages,
        "regenerate_count": result.regenerate_count,
        "max_regenerate": result.max_regenerate,
    }


def to_http_error(exc: conversation.ChatError) -> HTTPException:
    """领域错误映射成 HTTP 状态码。"""
    if isinstance(exc, conversation.InvalidRequest):
        status = 422
    elif isinstance(exc, conversation.ConflictError):
        status = 409
    elif isinstance(exc, conversation.ModelError):
        status = 502
    else:
        status = 400
    return HTTPException(status_code=status, detail=str(exc))


@app.get("/api/health", summary="健康检查")
def health() -> dict[str, str]:
    """返回服务状态、版本号、当前模型和配置名。"""
    return {
        "status": "ok",
        "version": __version__,
        "model": default_model(),
        "profile_name": profile_name(),
    }


@app.get("/api/sessions", summary="会话列表")
def list_sessions() -> dict[str, list[dict[str, Any]]]:
    """返回所有会话的 id、标题和置顶状态，置顶的排前面。"""
    with session_memory(LIST_ONLY_SESSION_ID) as memory:
        return {"sessions": memory.list_session_entries()}


@app.post("/api/sessions", status_code=201, summary="新建会话")
def create_session(body: NewSession | None = None) -> dict[str, str]:
    """新建会话，只生成 id，等第一条消息写进来才真正入库。"""
    requested = (body.session_id or "").strip() if body else ""
    if requested and not is_valid_session_id(requested):
        raise HTTPException(
            status_code=422,
            detail="会话 id 只能包含 1-64 个非空白字符，且不能有 / \\ ? # %",
        )
    return {"session_id": requested or new_session_id()}


@app.post("/api/sessions/pin", summary="批量置顶会话")
def pin_sessions(body: SessionIds) -> dict[str, int]:
    """一次给多个会话置顶或取消置顶。"""
    with session_memory(LIST_ONLY_SESSION_ID) as memory:
        updated = memory.pin_sessions(body.ids, body.pinned)
    return {"updated": updated}


@app.post("/api/sessions/delete", summary="批量删除会话")
def delete_sessions(body: SessionIds) -> dict[str, int]:
    """一次删除多个会话，消息、摘要、长期记忆一起删。"""
    with session_memory(LIST_ONLY_SESSION_ID) as memory:
        deleted = memory.delete_sessions(body.ids)
    return {"deleted": deleted, "requested": len(body.ids)}


@app.get("/api/sessions/{session_id}", summary="会话信息")
def get_session(session_id: str) -> dict[str, Any]:
    """会话的元信息：标题、摘要、长期记忆、消息条数，不含消息正文。"""
    with session_memory(session_id) as memory:
        return memory.overview()


@app.get("/api/sessions/{session_id}/messages", summary="分页读历史")
def get_messages(
    session_id: str,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=200, description="这一页最多几条"),
    before_seq: int | None = Query(
        default=None,
        ge=1,
        description="只取序号比它小的消息，用于往上翻页；不传就是最新的一页",
    ),
) -> dict[str, Any]:
    """从最新往前翻页，返回的一页按时间正序排列。"""
    with session_memory(session_id) as memory:
        messages, has_more = memory.message_page(limit=limit, before_seq=before_seq)
        return {
            "session_id": session_id,
            "messages": messages,
            "has_more": has_more,
            "message_count": memory.message_count(),
        }


@app.get("/api/sessions/{session_id}/outline", summary="问答导航")
def get_outline(session_id: str) -> dict[str, Any]:
    """每轮问答的摘要，给右侧导航用；不带正文，所以整段会话都能覆盖。"""
    with session_memory(session_id) as memory:
        return {"session_id": session_id, "rounds": memory.outline()}


@app.post("/api/sessions/{session_id}/messages", status_code=201, summary="发一条消息")
def post_message(session_id: str, body: NewMessage) -> dict[str, Any]:
    """写入用户消息、调用模型、写回回复；第一轮结束后自动总结一个标题。"""
    with session_memory(session_id) as memory:
        try:
            result = conversation.send(memory, body.text, to_quote(body.quote))
        except conversation.ChatError as exc:
            raise to_http_error(exc) from exc
        return turn_payload(memory, result)


@app.post("/api/sessions/{session_id}/messages/edit", status_code=201, summary="编辑最后一条消息")
def edit_last_message(session_id: str, body: NewMessage) -> dict[str, Any]:
    """撤掉最后一轮问答，用编辑后的内容重新提问。"""
    with session_memory(session_id) as memory:
        try:
            result = conversation.edit_last(memory, body.text)
        except conversation.ChatError as exc:
            raise to_http_error(exc) from exc
        return turn_payload(memory, result)


@app.post(
    "/api/sessions/{session_id}/messages/regenerate",
    status_code=201,
    summary="重新生成回复",
)
def regenerate_reply(session_id: str) -> dict[str, Any]:
    """重新生成最后一条回复，一条回复最多重新生成几次见 core.conversation.MAX_REGENERATE。"""
    with session_memory(session_id) as memory:
        try:
            result = conversation.regenerate(memory)
        except conversation.ChatError as exc:
            raise to_http_error(exc) from exc
        return {
            "session_id": session_id,
            "reply": result.reply,
            "regenerate_count": result.regenerate_count,
            "max_regenerate": result.max_regenerate,
            "message": result.messages[-1],
        }


@app.patch("/api/sessions/{session_id}", summary="重命名会话")
def rename_session(session_id: str, body: RenameSession) -> dict[str, Any]:
    """手工重命名会话；改过之后不再自动生成标题。"""
    try:
        with session_memory(session_id) as memory:
            title = memory.rename(body.title)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"session_id": session_id, "title": title, "title_locked": True}


@app.delete("/api/sessions/{session_id}", summary="删除会话")
def delete_session(session_id: str) -> dict[str, Any]:
    """删除这个会话的消息、摘要、长期记忆和标题，其他会话不受影响。"""
    with session_memory(session_id) as memory:
        memory.clear()
    return {"session_id": session_id, "deleted": True}


@app.get("/api/sessions/{session_id}/export", summary="导出会话")
def export_session(session_id: str) -> JSONResponse:
    """下载这个会话的完整数据，在别的机器上用导入接口可以完全还原。"""
    with session_memory(session_id) as memory:
        data = memory.export_session()
    title = re.sub(r'[\\/:*?"<>|\s]+', "-", str(data.get("title") or "会话"))[:40] or "会话"
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    # HTTP 头只能是 latin-1，中文文件名走 RFC 5987 的 filename*，同时给一个 ASCII 兜底
    ascii_name = f"werewolf-claw-{stamp}.json"
    utf8_name = quote(f"{title}-{stamp}.json")
    return JSONResponse(
        content=data,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{utf8_name}'
            )
        },
    )


@app.post("/api/sessions/import", status_code=201, summary="导入会话")
def import_session(data: dict[str, Any]) -> dict[str, Any]:
    """把导出的 JSON 写进库还原成一个会话。

    原会话 id 没被占用就沿用，被占用了换一个新 id，不影响已有会话。
    """
    try:
        session_id = Memory.import_session(data, db_path=DB_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    with session_memory(session_id) as memory:
        return {"session_id": session_id, "title": memory.display_title()}


@app.get("/api/settings", summary="读取模型配置")
def get_settings() -> dict[str, Any]:
    """返回所有模型配置，密钥只返回打码结果。"""
    return {
        "active": active_profile_id(),
        "profiles": [
            {
                "id": profile["id"],
                "name": profile["name"],
                "api_key": mask_secret(profile["api_key"]),
                "has_api_key": bool(profile["api_key"]),
                "base_url": profile["base_url"],
                "model": profile["model"],
            }
            for profile in list_profiles()
        ],
        "max_profiles": MAX_PROFILES,
        "env_file": str(env_path()),
    }


@app.put("/api/settings", summary="保存模型配置")
def update_settings(body: SettingsIn) -> dict[str, Any]:
    """把多套配置写进 .env 并立即生效；`api_key` 留空表示沿用这套配置原来的密钥。"""
    if not body.profiles:
        raise HTTPException(status_code=422, detail="至少要有一套模型配置")
    if len(body.profiles) > MAX_PROFILES:
        raise HTTPException(status_code=422, detail=f"最多只能保存 {MAX_PROFILES} 套配置")

    existing = {profile["id"]: profile for profile in list_profiles()}
    payload: list[dict[str, str]] = []
    active_index = 1
    for index, profile in enumerate(body.profiles, start=1):
        old = existing.get(profile.id or "", {})
        if profile.id and profile.id == body.active:
            active_index = index
        payload.append(
            {
                "id": str(index),
                "name": profile.name.strip() or old.get("name") or f"模型配置{index}",
                "api_key": profile.api_key.strip() or old.get("api_key", ""),
                "base_url": profile.base_url.strip(),
                "model": profile.model.strip(),
            }
        )

    try:
        save_profiles(payload, active_id=str(active_index))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"写入 .env 失败：{exc}") from exc
    return get_settings()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """前端页面。"""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/help", include_in_schema=False)
def help_page() -> FileResponse:
    """帮助文档页面，左下角的问号按钮指向这里。"""
    return FileResponse(STATIC_DIR / "help.html")


@app.get("/about", include_in_schema=False)
def about_page() -> FileResponse:
    """关于页面：版本号和项目简介。"""
    return FileResponse(STATIC_DIR / "about.html")


def main() -> None:
    """命令行启动服务。"""
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
