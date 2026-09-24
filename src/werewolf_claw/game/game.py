"""一局对局的运行器：7 个 Agent（1 法官 + 6 玩家）共用一个 Screen。

对局跑在后台线程里，网页线程只读快照，所以 Screen 加锁、快照只给数据不给对象。
`model=False` 时玩家不带模型入口，纯规则跑完一局，方便在不联网时验证流程。
"""

from __future__ import annotations

import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from werewolf_claw.agents import judge_agent, player_agent
from werewolf_claw.core import llm
from werewolf_claw.boards import BOARD_LABELS, DEFAULT_BOARD, board_by_id, board_id_of
from werewolf_claw.core.board import Board
from werewolf_claw.core.match import MatchStore
from werewolf_claw.core.screen import PRIVATE, Message, Screen
from werewolf_claw.core.system import LocalSystem
from werewolf_claw.game.human import HumanSeat
from werewolf_claw.game.llm_agents import AgentStats, agent_chat, judge_narrate
from werewolf_claw.game.pace import Pace

# 快照里单条消息、单条记忆的截断长度，避免一次返回太多
MAX_TEXT_CHARS = 600

# 玩家昵称池：每局随机发，不重复
NAME_POOL = (
    "阿狸", "老周", "白露", "青禾", "小满", "阿岩", "拾一", "南风",
    "山鬼", "木鱼", "灯下", "半夏", "司命", "听风", "阿橘", "常安",
    "砚台", "雪饼", "长明", "远山", "阿砚", "九思", "拂晓", "空青",
)


def deal_names(count: int, *, seed: int | None = None) -> dict[int, str]:
    """给每个座位发一个不重复的昵称；座位比昵称多时就加序号。"""
    rng = random.Random(seed)
    pool = list(NAME_POOL)
    rng.shuffle(pool)
    names: list[str] = []
    while len(names) < count:
        base = pool[len(names) % len(pool)]
        suffix = "" if len(names) < len(pool) else str(len(names) // len(pool) + 1)
        names.append(f"{base}{suffix}")
    return dict(zip(range(1, count + 1), names))


def _find_profile(profile_id: str) -> dict[str, Any]:
    """从 `.env` 的多套模型配置里挑一套：给了 id 用它，没给用当前生效的。"""
    profiles = llm.list_profiles()
    if not profiles:
        return {}
    if profile_id:
        for profile in profiles:
            if profile["id"] == profile_id:
                return profile
    active = llm.active_profile_id()
    for profile in profiles:
        if profile["id"] == active:
            return profile
    return profiles[0]


@dataclass
class GameOptions:
    """一局的开局参数。"""

    board: str = "default_board"
    seed: int | None = None
    max_days: int = 6
    model: bool = True
    profile: str = ""  # 用 .env 里的哪一套模型配置，空着就用当前生效的
    profiles: dict[str, str] = field(default_factory=dict)  # 每个座位/法官单独指定配置
    humans: list[int] = field(default_factory=list)  # 开局就交给人类的座位
    temperature: float = 0.8


class Game:
    """一局对局：发身份、建 Agent、跑法官的 Flow，随时给网页快照。"""

    def __init__(
        self,
        options: GameOptions,
        board: Board | None = None,
        store: MatchStore | None = None,
    ) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.options = options
        self.board = board or board_by_id(options.board)
        self.board_id = board_id_of(self.board) or options.board
        self.store = store or MatchStore()
        self.screen = Screen(recorder=self._record)
        self.pace = Pace()
        self.system = LocalSystem(self.screen, pace=self.pace.sleep)
        self.roles = judge_agent.deal_roles(self.board, seed=options.seed)
        self.names = deal_names(len(self.roles), seed=options.seed)
        self.created = time.time()
        self.stop_event = threading.Event()
        self.stopped = False
        self.deleted = False  # 删掉的对局不再回写库
        self.humans: dict[int, HumanSeat] = {}
        self.model_chats: dict[int, Any] = {}
        self.profile = _find_profile(options.profile) if options.model else {}
        self.seat_profiles: dict[int, dict[str, Any]] = {}
        # 法官配置：显式选了 "rules" 就不调模型（用模板播报）；没单独选就用全局默认。
        judge_id = options.profiles.get("judge", "") if options.model else "rules"
        if options.model and judge_id != "rules":
            self.judge_profile: dict[str, Any] = _find_profile(judge_id) or self.profile
        else:
            self.judge_profile: dict[str, Any] = {}

        self.stats: list[AgentStats] = []
        self.players: dict[int, player_agent.PlayerAgent] = {}
        for seat, role in self.roles.items():
            chat = None
            profile = self.profile
            if options.model:
                seat_id = options.profiles.get(str(seat), "")
                if seat_id == "rules":
                    # 显式选了纯规则：这个座位不调模型，发言/投票/技能都退回规则版
                    profile = {}
                else:
                    profile = _find_profile(seat_id) or self.profile
                    stats = AgentStats(f"{seat} 号 {role}")
                    self.stats.append(stats)
                    chat = agent_chat(
                        stats,
                        temperature=options.temperature,
                        stop=self.stop_event,
                        profile=profile or None,
                    )
            self.seat_profiles[seat] = profile
            self.players[seat] = player_agent.PlayerAgent(
                seat, role, board=self.board, chat=chat
            )

        self.judge = judge_agent.JudgeAgent(
            self.roles,
            board=self.board,
            system=self.system,
            pace=self.pace.sleep,
            seed=options.seed,
            max_days=options.max_days,
        )
        # 法官选了模型配置才调模型润色播报；选了纯规则就 narrate=None，用模板，不建 stats
        if options.model and self.judge_profile:
            judge_stats = AgentStats("法官")
            self.stats.insert(0, judge_stats)
            self.judge.narrate = judge_narrate(
                judge_stats,
                self.judge.template,
                stop=self.stop_event,
                speed=lambda: self.pace.speed,
                profile=self.judge_profile or None,
            )

        self.status = "ready"
        self.winner = ""
        self.error = ""
        self._saved_signature: tuple[Any, ...] | None = None
        self.started = 0.0
        self.finished = 0.0
        self._thread: threading.Thread | None = None
        for seat in options.humans:
            if int(seat) in self.players:
                self.takeover(int(seat))
        self._save_match()

    # ------------------------------------------------------------------ 落库

    def _record(self, message: Message) -> None:
        """每条消息落库：大屏进 pub，私聊按收件人一人一行进 priv。"""
        if self.deleted:
            return
        if message.channel == PRIVATE:
            self.store.append_private(
                self.id,
                message.audience,
                seq=message.seq,
                day=message.day,
                kind=message.kind,
                text=message.text,
                facts=message.facts,
            )
        else:
            self.store.append_public(
                self.id,
                seq=message.seq,
                day=message.day,
                kind=message.kind,
                text=message.text,
                facts=message.facts,
            )
        self._save_match()

    def _save_match(self) -> None:
        """把对局档案写进库里：对局栏和快照都靠它。"""
        if self.deleted:
            return
        # 只有状态真的变了才写：原来每条消息都 upsert 一次，库里全是重复写
        signature = (
            self.status,
            self.judge.day,
            self.system.phase,
            self.winner,
            self.stopped,
            len(self.humans),
        )
        if signature == self._saved_signature:
            return
        self._saved_signature = signature
        self.store.save_match(
            {
                "id": self.id,
                "board": self.board_id,
                "board_name": BOARD_LABELS.get(self.board_id, self.board_id),
                "status": self.status,
                "winner": self.winner,
                "day": self.judge.day,
                "phase": self.system.phase,
                "stopped": self.stopped,
                "created": self.created,
                "started": self.started,
                "finished": self.finished,
                "elapsed": self._elapsed(),
                "options": {
                    "board": {
                        "id": self.board_id,
                        "name": BOARD_LABELS.get(self.board_id, self.board_id),
                        "size": self.board.size,
                        "distribution": list(self.board.distribution),
                        "night_phases": list(self.board.night_phases),
                    },
                    "model": self.options.model,
                    "max_days": self.options.max_days,
                    "profile_name": self.profile.get("name", "") if self.profile else "",
                    "judge_model": self.judge_profile.get("name", "") if self.judge_profile else "",
                },
                "seats": [self._seat(seat, True, []) for seat in sorted(self.roles)],
                "agents": [stats.snapshot() for stats in self.stats],
                "updated": time.time(),
            }
        )

    def stop(self) -> None:
        """结束这一局：不再调用模型，剩下的步骤用规则版快速跑完，状态保留。"""
        self.stopped = True
        self.stop_event.set()
        self.pace.resume()
        self._save_match()

    def mark_deleted(self) -> None:
        """被删掉：先停下，再禁止一切回写，否则游戏线程会把记录又写回来。"""
        self.deleted = True
        self.stopped = True
        self.stop_event.set()
        self.pace.resume()

    def pause(self) -> None:
        """暂停：等待和计时都停住。"""
        self.pace.pause()

    def resume(self) -> None:
        self.pace.resume()

    def set_speed(self, speed: float) -> None:
        self.pace.set_speed(speed)

    # ------------------------------------------------------------------ 人类接管

    def takeover(self, seat: int) -> HumanSeat:
        """人类接管一个座位：这个玩家之后的“模型调用”改成问人。"""
        human = self.humans.get(seat)
        if human is not None:
            return human
        # 同时只能接管一个座位：先把手里的那个放回给 Agent
        for other in list(self.humans):
            if other != seat:
                self.release(other)
        player = self.players[seat]
        human = HumanSeat(player, self.names[seat])
        self.humans[seat] = human
        self.model_chats[seat] = player.chat
        player.chat = human.ask
        return human

    def release(self, seat: int) -> None:
        """退出接管：Agent 换回原来的模型入口，接着往下走。"""
        human = self.humans.pop(seat, None)
        if human is None:
            return
        human.cancel()
        self.players[seat].chat = self.model_chats.pop(seat, None)

    def submit_human(self, seat: int, text: str) -> bool:
        human = self.humans.get(seat)
        return bool(human and human.submit(text))

    def pending_human(self) -> dict[str, object] | None:
        for seat in sorted(self.humans):
            pending = self.humans[seat].pending()
            if pending is not None:
                return pending
        return None

    # ------------------------------------------------------------------ 运行

    def start(self) -> None:
        """起一个后台线程跑完这一局；重复调用只跑一次。"""
        if self._thread is not None:
            return
        self.status = "running"
        # 计时用单调时钟：和 Pace 内部的 time.monotonic() 对齐，否则算出来恒为 0
        self.started = time.monotonic()
        self._thread = threading.Thread(target=self._run, name=f"game-{self.id}", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self.winner = self.judge.play(self.players)
            self.status = "finished"
        except Exception as exc:  # 一局里的意外不该把网页带崩
            self.error = f"{type(exc).__name__}: {exc}"
            self.status = "failed"
        finally:
            self.finished = time.monotonic()
            self._save_match()  # 收尾状态（胜负、用时）也要落库

    def wait(self, timeout: float | None = None) -> None:
        """等这一局跑完（给测试和命令行用）。"""
        if self._thread is not None:
            self._thread.join(timeout)

    # ------------------------------------------------------------------ 快照

    def snapshot(self, *, god: bool = False) -> dict[str, Any]:
        """给网页看板的数据。`god=True` 或对局结束时才公开身份和私聊。"""
        # 身份只在上帝视角下公开，对局结束也不自动公布
        reveal = god
        messages = [self._message(message) for message in self.screen.snapshot()]
        return {
            "id": self.id,
            "summary": self.summary(),
            "status": self.status,
            "winner": self.winner,
            "error": self.error,
            "day": self.judge.day,
            "phase": self.system.phase,
            "alive": list(self.judge.alive_seats()),
            "elapsed": self._elapsed(),
            "options": {
                "seed": self.options.seed,
                "max_days": self.options.max_days,
                "model": self.options.model,
                "temperature": self.options.temperature,
            },
            "model": llm.default_model() if self.options.model else "",
            "judge_model": self.judge_profile.get("name", "") if self.judge_profile else "",
            "profile": self.profile.get("name", "") if self.profile else "",
            "paused": self.pace.paused,
            "speed": self.pace.speed,
            "humans": sorted(self.humans),
            "pending": self.pending_human(),
            "board": {
                "id": self.board_id,
                "name": BOARD_LABELS.get(self.board_id, self.board_id),
                "size": self.board.size,
                "distribution": list(self.board.distribution),
                "night_phases": list(self.board.night_phases),
            },
            "agents": [stats.snapshot() for stats in self.stats],
            "messages": messages,
            "seats": [self._seat(seat, reveal, messages) for seat in sorted(self.roles)],
            "ledger": (
                [self._message(message) for message in self.judge.ledger] if reveal else []
            ),
        }

    def _elapsed(self) -> float:
        if not self.started:
            return 0.0
        return round(self.pace.elapsed(self.started, self.finished), 1)

    def summary(self) -> dict[str, Any]:
        """对局栏里的一行。"""
        return {
            "id": self.id,
            "board": self.board_id,
            "board_name": BOARD_LABELS.get(self.board_id, self.board_id),
            "created": round(self.created, 3),
            "status": self.status,
            "stopped": self.stopped,
            "day": self.judge.day,
            "winner": self.winner,
            "model": self.options.model,
        }

    def _message(self, message: Message) -> dict[str, Any]:
        return {
            "seq": message.seq,
            "day": message.day,
            "kind": message.kind,
            "channel": message.channel,
            "audience": list(message.audience),
            "text": message.text[:MAX_TEXT_CHARS],
        }

    def _seat(self, seat: int, reveal: bool, messages: list[dict[str, Any]]) -> dict[str, Any]:
        player = self.players[seat]
        # 模型名：座位单独选了配置用配置名；选了「纯规则」（或没开模型）显示「无模型」，
        # 不能退回全局默认模型名——那会让纯规则座位误标成 deepseek-flash 之类的名字
        seat_profile = self.seat_profiles.get(seat) or {}
        data: dict[str, Any] = {
            "seat": seat,
            "name": self.names[seat],
            "alive": player.alive,
            "is_special": player.is_special,
            "human": seat in self.humans,
            "model": seat_profile.get("name") or "无模型",
            "private": [],
        }
        if not reveal:
            if seat in self.humans:
                # 人类接管者知道自己座位的身份：座位卡名字下方要显示
                data["role"] = player.role
                data["camp"] = player.camp
            return data
        data["role"] = player.role
        data["camp"] = player.camp
        data["skill"] = player.skill
        data["describe"] = player.character.describe
        data["private"] = [
            message
            for message in messages
            if message["channel"] == PRIVATE and seat in message["audience"]
        ]
        return data


class GameStore:
    """进程内的对局表；网页刷新后还能接着看。"""

    def __init__(self) -> None:
        self._games: dict[str, Game] = {}
        self._lock = threading.Lock()
        # 历史对局（进程重启后）从库里读
        self.matches = MatchStore()

    def create(self, options: GameOptions, board: Board | None = None) -> Game:
        game = Game(options, board, self.matches)
        with self._lock:
            self._games[game.id] = game
        game.start()
        return game

    def get(self, game_id: str) -> Game | None:
        with self._lock:
            return self._games.get(game_id)

    def latest(self) -> Game | None:
        with self._lock:
            if not self._games:
                return None
            return self._games[next(reversed(self._games))]

    def live(self) -> Game | None:
        """还在跑的那一局（没有就返回 None）。"""
        with self._lock:
            for game in reversed(list(self._games.values())):
                if game.status == "running":
                    return game
        return None

    def list(self) -> list[dict[str, Any]]:
        """对局栏：新的排前面；还在跑的用内存里的状态，历史对局从库里读。"""
        with self._lock:
            games = list(self._games.values())
        live = [
            game.summary() for game in sorted(games, key=lambda item: item.created, reverse=True)
        ]
        seen = {item["id"] for item in live}
        history = [
            {
                "id": row["id"],
                "board": row["board"],
                "board_name": row["board_name"],
                "created": row["created"],
                "status": row["status"],
                "stopped": row["stopped"],
                "day": row["day"],
                "winner": row["winner"],
                "model": (row.get("options") or {}).get("model", False),
            }
            for row in self.matches.list_matches()
            if row["id"] not in seen
        ]
        return sorted(live + history, key=lambda item: item["created"], reverse=True)

    def stop_running(self, keep: str = "") -> list[str]:
        """把还在跑的其它对局停掉（算作结束），返回被停掉的 id。"""
        with self._lock:
            games = list(self._games.values())
        stopped: list[str] = []
        for game in games:
            if game.status == "running" and game.id != keep:
                game.stop()
                stopped.append(game.id)
        return stopped

    def delete(self, game_id: str) -> bool:
        """删掉一局：先标记删除（禁止回写）并停掉，再清掉库里的记录。"""
        with self._lock:
            game = self._games.pop(game_id, None)
        if game is not None:
            game.mark_deleted()  # 否则还在跑的游戏线程会把记录写回来
        return self.matches.delete_match(game_id) or game is not None

    def snapshot(self, game_id: str, *, god: bool = False) -> dict[str, Any] | None:
        """快照：优先用还在跑的那一局，否则从库里还原。"""
        game = self.get(game_id)
        if game is not None:
            return game.snapshot(god=god)
        return self.matches.snapshot(game_id, god=god)


GAMES = GameStore()
