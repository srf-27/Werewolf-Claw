"""对局页面的 HTTP 层：`/game` 页面和 `/api/game/*` 接口。

对局怎么跑在 `werewolf_claw.game` 里；这一层只管接口、参数校验，以及把模型配置的
增删透给 `core.llm`。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from werewolf_claw.boards import board_options
from werewolf_claw.core import llm
from werewolf_claw.core.vector_retriever import get_retriever
from werewolf_claw.game.game import GAMES, GameOptions

STATIC_DIR = Path(__file__).parent / "static" / "game"

router = APIRouter(tags=["game"])


class NewGame(BaseModel):
    """开一局的参数。"""

    board: str = "default_board"
    seed: int | None = None
    max_days: int = Field(default=6, ge=1, le=12)
    model: bool = True
    profile: str = ""  # 用哪一套模型配置（空着用当前生效的）
    profiles: dict[str, str] = {}  # 每个座位（"1".."12"）、"judge" 单独指定
    humans: list[int] = []  # 开局就交给人类的座位
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)


class Speed(BaseModel):
    """倍速。"""

    speed: float = Field(default=1.0, ge=0.5, le=8.0)


class HumanInput(BaseModel):
    """人类接管时提交的内容。"""

    text: str = ""
    target: int | None = None
    effect: str = ""  # 女巫可指定 save/poison/空（不用）


class NewProfile(BaseModel):
    """新增一套模型配置。"""

    name: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""


class AdviceIn(BaseModel):
    """助手求助的参数：问题可空，空着就按当前形势检索。"""

    query: str = ""


@router.get("/game")
def game_page() -> FileResponse:
    """对局看板页面。"""
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/api/game/boards")
def list_boards() -> list[dict[str, object]]:
    """能选的板子。"""
    return board_options()


@router.get("/api/game/live")
def live_game() -> dict[str, object]:
    """当前真正在跑的那一局（网页靠它自动跟随；历史/中断的对局不算）。"""
    game = GAMES.live()
    return {"latest": game.id if game else ""}


@router.get("/api/game/models")
def list_models() -> dict[str, object]:
    """`.env` 里的模型配置清单（不返回密钥），外加当前生效的那套。"""
    return {
        "active": llm.active_profile_id(),
        "profiles": [
            {"id": profile["id"], "name": profile["name"], "model": profile["model"]}
            for profile in llm.list_profiles()
        ],
    }


@router.post("/api/game/models")
def add_model(body: NewProfile) -> dict[str, object]:
    """新增一套模型配置，写回 `.env`。"""
    if not body.name.strip() or not body.api_key.strip():
        raise HTTPException(status_code=422, detail="配置名和 API Key 不能为空")
    profiles = [
        {
            "name": profile["name"],
            "api_key": profile["api_key"],
            "base_url": profile["base_url"],
            "model": profile["model"],
        }
        for profile in llm.list_profiles()
    ]
    if len(profiles) >= llm.MAX_PROFILES:
        raise HTTPException(status_code=409, detail=f"最多 {llm.MAX_PROFILES} 套配置，已达配置数上限")
    profiles.append(
        {
            "name": body.name.strip(),
            "api_key": body.api_key.strip(),
            "base_url": body.base_url.strip(),
            "model": body.model.strip(),
        }
    )
    llm.save_profiles(profiles, active_id=llm.active_profile_id())
    return list_models()


@router.get("/api/game/games")
def list_games() -> list[dict[str, object]]:
    """对局栏：新的排前面。"""
    return GAMES.list()


@router.post("/api/game/games")
def create_game(body: NewGame) -> dict[str, object]:
    """开一局；同一时间只留一局在跑，老局会被停掉（状态保留）。"""
    GAMES.stop_running()
    game = GAMES.create(GameOptions(**body.model_dump()))
    return game.snapshot()


def _game(game_id: str):
    game = GAMES.get(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="没有这一局")
    return game


@router.get("/api/game/games/{game_id}/export")
def export_game(game_id: str) -> dict[str, object]:
    """导出一局的完整数据（身份、私聊、法官台账全包含），给聊天机器人分析用。"""
    snapshot = GAMES.snapshot(game_id, god=True)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="没有这一局")
    return {
        "type": "werewolf-game-export",
        "version": 1,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "game": snapshot,
    }


@router.get("/api/game/games/{game_id}")
def get_game(game_id: str, god: bool = False) -> dict[str, object]:
    """取某一局的快照；`god=1` 时带上身份和私聊。历史对局从库里还原。"""
    snapshot = GAMES.snapshot(game_id, god=god)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="没有这一局")
    return snapshot


@router.get("/api/game/games/{game_id}/seats/{seat}/memory")
def seat_memory(game_id: str, seat: int, after: int = 0) -> list[dict[str, object]]:
    """按对局 id + 座位 id 读这个座位的私人记忆（隔离在存储层）。"""
    if GAMES.get(game_id) is None and GAMES.matches.get_match(game_id) is None:
        raise HTTPException(status_code=404, detail="没有这一局")
    return GAMES.matches.read_private(game_id, seat, after_seq=after)


# 助手检索时带上的上下文条数：大屏末尾 + 私人记忆末尾
ADVICE_CONTEXT_ROWS = 8


@router.post("/api/game/games/{game_id}/seats/{seat}/advice")
def seat_advice(game_id: str, seat: int, body: AdviceIn) -> dict[str, object]:
    """玩家助手：按这个座位能掌握的信息（大屏 + 自己的私聊）检索相似历史对局。

    只读存储层里该座位自己的私聊，拿不到别人的；向量库不可用时返回 `status` 说明，
    前端据此降级提示，不影响对局。
    """
    if GAMES.get(game_id) is None and GAMES.matches.get_match(game_id) is None:
        raise HTTPException(status_code=404, detail="没有这一局")
    question = body.query.strip()
    pub = GAMES.matches.read_public(game_id, after_seq=0)[-ADVICE_CONTEXT_ROWS:]
    priv = GAMES.matches.read_private(game_id, seat, after_seq=0)[-ADVICE_CONTEXT_ROWS:]
    board_text = "\n".join(f"- {row['text']}" for row in pub) or "（大屏还没有内容）"
    secret_text = "\n".join(f"- {row['text']}" for row in priv) or "（暂无私聊情报）"
    query = question or "当前局势下一步怎么走"
    query = f"{query}\n当前大屏：\n{board_text}\n我的私密情报：\n{secret_text}"

    retriever = get_retriever()
    status = retriever.status() if retriever else "检索客户端不可用"
    if status:
        return {"advice": "", "hits": 0, "status": status}
    hits = retriever.retrieve(query, top_k=8)
    return {"advice": retriever.format(hits), "hits": len(hits), "status": ""}


@router.get("/api/game/games/{game_id}/board")
def board_log(game_id: str, after: int = 0) -> list[dict[str, object]]:
    """按对局 id 读大屏。"""
    if GAMES.get(game_id) is None and GAMES.matches.get_match(game_id) is None:
        raise HTTPException(status_code=404, detail="没有这一局")
    return GAMES.matches.read_public(game_id, after_seq=after)


@router.delete("/api/game/games/{game_id}")
def delete_game(game_id: str) -> dict[str, object]:
    """删掉一局（连同它的记录）。"""
    if not GAMES.delete(game_id):
        raise HTTPException(status_code=404, detail="没有这一局")
    return {"ok": True, "games": GAMES.list()}


@router.post("/api/game/games/{game_id}/stop")
def stop_game(game_id: str) -> dict[str, object]:
    """结束一局：不再调用模型，剩下的按规则跑完，状态保留。"""
    game = _game(game_id)
    game.stop()
    return game.snapshot()


@router.post("/api/game/games/{game_id}/pause")
def pause_game(game_id: str) -> dict[str, object]:
    """暂停：对局停在当前步骤，计时器也停。"""
    game = _game(game_id)
    game.pause()
    return game.snapshot()


@router.post("/api/game/games/{game_id}/resume")
def resume_game(game_id: str) -> dict[str, object]:
    game = _game(game_id)
    game.resume()
    return game.snapshot()


@router.post("/api/game/games/{game_id}/speed")
def set_speed(game_id: str, body: Speed) -> dict[str, object]:
    """倍速：压缩播报和步骤之间的等待。"""
    game = _game(game_id)
    game.set_speed(body.speed)
    return game.snapshot()


@router.post("/api/game/games/{game_id}/seats/{seat}/takeover")
def takeover_seat(game_id: str, seat: int) -> dict[str, object]:
    """人类接管某个座位；同时只能接管一个。"""
    game = _game(game_id)
    game.takeover(seat)
    return game.snapshot()


@router.post("/api/game/games/{game_id}/seats/{seat}/release")
def release_seat(game_id: str, seat: int) -> dict[str, object]:
    """退出接管，Agent 重连继续玩。"""
    game = _game(game_id)
    game.release(seat)
    return game.snapshot()


@router.post("/api/game/games/{game_id}/seats/{seat}/input")
def human_input(game_id: str, seat: int, body: HumanInput) -> dict[str, object]:
    """人类提交这一步的回答：网页给文本或选中的座位号，这里拼成 Agent 要的格式。"""
    game = _game(game_id)
    pending = game.pending_human() or {}
    kind = str(pending.get("kind") or "")
    role = game.players[seat].role if seat in game.players else ""
    if kind in ("投票", "技能", "出局技能") and body.target is not None:
        payload: dict[str, object] = {"target": int(body.target)}
        if kind in ("技能", "出局技能"):
            payload = {"phase": role, **payload}
            # 女巫可以指定效果（save/poison），其他角色效果由角色类定
            if body.effect:
                payload["effect"] = body.effect
        answer = json.dumps(payload, ensure_ascii=False)
    elif kind == "技能" and body.target is None and not (body.text or "").strip():
        # 明确的「不用技能」（女巫捏着药）：必须给结构化弃权，
        # 不能落进纯文本分支——解析失败会被兜底成自动用药
        payload_skip: dict[str, object] = {"phase": role, "target": None}
        if body.effect is not None:
            payload_skip["effect"] = body.effect
        answer = json.dumps(payload_skip, ensure_ascii=False)
    elif kind == "发言":
        answer = json.dumps(
            {"text": body.text, "target": None if body.target is None else int(body.target)},
            ensure_ascii=False,
        )
    else:
        answer = body.text
    accepted = game.submit_human(seat, answer)
    snapshot = game.snapshot()
    snapshot["accepted"] = accepted
    return snapshot
