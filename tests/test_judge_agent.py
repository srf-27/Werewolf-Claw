"""法官 Agent 的最小单测：夜间顺序校验、平票、空刀、昨夜名单、随机种子。

跑法（仓库根目录）：`python -m unittest discover -s tests`
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping, Sequence
from typing import Any

from werewolf_claw.agents.judge_agent import JudgeAgent, deal_roles
from werewolf_claw.boards import DEFAULT_BOARD, STANDARD12_BOARD
from werewolf_claw.core.board import Board
from werewolf_claw.core.screen import Message


def roles_for(board: Board) -> dict[int, str]:
    """按板子的身份分布发满座位（测试用，座位从 1 开始）。"""
    return dict(zip(range(1, board.size + 1), board.distribution))


def board_with(source: Board, **overrides: Any) -> Board:
    """照着已有板子改几个字段造一个板子，用来构造非法夜间顺序。"""
    fields: dict[str, Any] = {
        "distribution": source.distribution,
        "camps": source.camps,
        "characters": source.characters,
        "night_phases": source.night_phases,
        "informed": source.informed,
    }
    fields.update(overrides)
    return Board(**fields)


class ScriptedPlayer:
    """最小玩家替身：满足 PlayerProtocol，动作脚本化，收消息只为断言用。"""

    is_special = True

    def __init__(
        self,
        seat: int,
        role: str,
        *,
        night: Mapping[str, Any] | None = None,
        statement: Mapping[str, Any] | None = None,
        ballot: Mapping[str, Any] | None = None,
        death: Mapping[str, Any] | None = None,
    ) -> None:
        self.seat = seat
        self.role = role
        self.night = dict(night) if night is not None else None
        self.statement_payload = dict(statement) if statement is not None else None
        self.ballot_payload = dict(ballot) if ballot is not None else None
        self.death_payload = dict(death) if death is not None else None
        self.inbox: list[Message] = []
        self._seen = 0

    def receive(self, messages: Sequence[Message]) -> int:
        fresh = [
            message
            for message in messages
            if message.seq > self._seen and message.visible_to(self.seat)
        ]
        if not fresh:
            return 0
        self._seen = max(message.seq for message in fresh)
        self.inbox.extend(fresh)
        return len(fresh)

    def night_action(self, phase: str, alive: Sequence[int]) -> dict[str, Any]:
        if self.night is not None:
            return dict(self.night)
        return {"phase": phase, "target": None, "effect": ""}

    def statement(self, alive: Sequence[int]) -> dict[str, Any]:
        return dict(self.statement_payload or {"text": f"我是 {self.seat} 号，先过。", "target": None})

    def ballot(self, alive: Sequence[int]) -> dict[str, Any]:
        return dict(self.ballot_payload or {"target": None})

    def team_talk(self, phase: str, alive: Sequence[int], round_no: int) -> str:
        return "我没意见。"

    def death_action(self, cause: str, alive: Sequence[int]) -> dict[str, Any] | None:
        return dict(self.death_payload) if self.death_payload is not None else None

    def watch(self) -> None:
        return None


class NightOrderTest(unittest.TestCase):
    """P0-1：板子的夜间顺序约束。"""

    def test_informed_phase_before_kill_is_rejected(self) -> None:
        board = board_with(
            STANDARD12_BOARD,
            night_phases=("Witch", "Guard", "Werewolf", "Seer"),
            informed=("Witch",),
        )
        with self.assertRaises(ValueError) as ctx:
            JudgeAgent(roles_for(board), board=board)
        message = str(ctx.exception)
        self.assertIn("Witch", message)
        self.assertIn("Werewolf", message)
        self.assertIn("夜间顺序不合法", message)

    def test_duplicate_phase_is_rejected(self) -> None:
        board = board_with(STANDARD12_BOARD, night_phases=("Guard", "Werewolf", "Werewolf", "Witch", "Seer"))
        with self.assertRaises(ValueError) as ctx:
            JudgeAgent(roles_for(board), board=board)
        self.assertIn("夜间阶段重复", str(ctx.exception))

    def test_normal_board_passes_and_witch_sees_kill(self) -> None:
        board = STANDARD12_BOARD
        roles = roles_for(board)
        judge = JudgeAgent(roles, board=board, seed=4)
        players = {seat: ScriptedPlayer(seat, role) for seat, role in roles.items()}
        wolf_seat = next(seat for seat, role in roles.items() if role == "Werewolf")
        players[wolf_seat] = ScriptedPlayer(
            wolf_seat, "Werewolf", night={"phase": "Werewolf", "target": 5, "effect": "kill"}
        )
        judge.players = players
        judge.begin_night()
        for phase in ("Guard", "Werewolf", "Witch"):
            judge.open_phase(phase)
        judge.close_phase("Werewolf")

        witch_seat = next(seat for seat, role in roles.items() if role == "Witch")
        witch_text = "\n".join(message.text for message in players[witch_seat].inbox)
        self.assertIn("今晚被袭击的是 5 号。", witch_text)

        judge.resolve_night()
        self.assertEqual(judge.day_deaths, (5,))


class TieBreakTest(unittest.TestCase):
    """P3-2：平票不再固定取最小座位号。"""

    def test_tie_picks_randomly(self) -> None:
        board = DEFAULT_BOARD
        picks = set()
        for seed in range(20):
            judge = JudgeAgent(roles_for(board), board=board, seed=seed)
            judge.night.put("Werewolf", 1, {"phase": "Werewolf", "target": 3, "effect": "kill"})
            judge.night.put("Werewolf", 2, {"phase": "Werewolf", "target": 5, "effect": "kill"})
            picks.add(judge.decide_effect("kill"))
        self.assertEqual(picks, {3, 5})


class KillerMarkTest(unittest.TestCase):
    """P3-3：空刀不标记「夜里杀过人」。"""

    def test_abstain_does_not_mark_killer(self) -> None:
        judge = JudgeAgent(roles_for(DEFAULT_BOARD), board=DEFAULT_BOARD, seed=1)
        judge.night.put("Werewolf", 1, {"phase": "Werewolf", "target": None, "effect": "kill"})
        judge.close_phase("Werewolf")
        self.assertEqual(judge.system.killers, set())

        judge.begin_night()
        judge.night.put("Werewolf", 1, {"phase": "Werewolf", "target": 4, "effect": "kill"})
        judge.close_phase("Werewolf")
        self.assertEqual(judge.system.killers, {"Werewolf 阵营"})


class DeathLedgerTest(unittest.TestCase):
    """P4-4：day_deaths 是昨夜名单，last_deaths 会被白天放逐改写。"""

    def test_day_deaths_survives_day_vote(self) -> None:
        judge = JudgeAgent(roles_for(DEFAULT_BOARD), board=DEFAULT_BOARD, seed=2)
        judge.begin_night()
        judge.night.put("Werewolf", 1, {"phase": "Werewolf", "target": 3, "effect": "kill"})
        judge.resolve_night()
        self.assertEqual(judge.day_deaths, (3,))
        self.assertEqual(judge.last_deaths, (3,))

        judge.ballots = {1: 5, 2: 5, 4: 5}
        judge.resolve_vote()
        self.assertEqual(judge.last_eliminated, 5)
        self.assertEqual(judge.last_deaths, (5,))
        self.assertEqual(judge.day_deaths, (3,))


class WitchSaveResolutionTest(unittest.TestCase):
    """女巫救与不救的结算对照：不救时狼刀必须生效。

    回归：修复前女巫「不用药」的空动作会被玩家层兜底成自动用解药，
    狼刀永远无效，夜夜平安。
    """

    def _roles_and_judge(self) -> tuple[JudgeAgent, dict[int, ScriptedPlayer], dict[int, str]]:
        board = DEFAULT_BOARD
        roles = roles_for(board)
        judge = JudgeAgent(roles, board=board, seed=7)
        players = {seat: ScriptedPlayer(seat, role) for seat, role in roles.items()}
        judge.players = players
        return judge, players, roles

    def _wolf_kill(self, judge: JudgeAgent, roles: dict[int, str], target: int) -> None:
        for seat, role in roles.items():
            if role == "Werewolf":
                judge.night.put(
                    "Werewolf", seat, {"phase": "Werewolf", "target": target, "effect": "kill"}
                )

    def test_witch_passing_lets_kill_land(self) -> None:
        judge, _players, roles = self._roles_and_judge()
        self._wolf_kill(judge, roles, 5)
        witch_seat = next(seat for seat, role in roles.items() if role == "Witch")
        judge.night.put(
            "Witch", witch_seat, {"phase": "Witch", "target": None, "effect": ""}
        )

        judge.resolve_night()

        self.assertIn(5, judge.day_deaths)
        self.assertNotIn(5, judge.alive)

    def test_witch_save_blocks_kill(self) -> None:
        judge, _players, roles = self._roles_and_judge()
        self._wolf_kill(judge, roles, 5)
        witch_seat = next(seat for seat, role in roles.items() if role == "Witch")
        judge.night.put(
            "Witch", witch_seat, {"phase": "Witch", "target": 5, "effect": "save"}
        )

        judge.resolve_night()

        self.assertNotIn(5, judge.day_deaths)
        self.assertIn(5, judge.alive)

    def test_save_and_poison_receipts_are_explicit(self) -> None:
        judge, _players, _roles = self._roles_and_judge()
        save_text, save_facts = judge.receipt(6, {"phase": "Witch", "target": 5, "effect": "save"})
        self.assertIn("救下", save_text)
        self.assertEqual(save_facts["save"], 5)
        poison_text, poison_facts = judge.receipt(6, {"phase": "Witch", "target": 3, "effect": "poison"})
        self.assertIn("毒", poison_text)
        self.assertEqual(poison_facts["poison"], 3)
        pass_text, _ = judge.receipt(6, {"phase": "Witch", "target": None, "effect": ""})
        self.assertIn("没有动作", pass_text)


class SeedTest(unittest.TestCase):
    """P4-5：发言顺序用派生 seed，和发牌解耦。"""

    def test_speaking_order_is_deterministic_and_varied(self) -> None:
        board = DEFAULT_BOARD
        roles = roles_for(board)
        orders = [
            JudgeAgent(roles, board=board, seed=seed).speaking_order() for seed in range(8)
        ]
        self.assertGreater(len(set(orders)), 1)
        self.assertEqual(orders[3], JudgeAgent(roles, board=board, seed=3).speaking_order())
        # 发牌仍然只由 deal_roles 的 seed 决定
        self.assertEqual(deal_roles(board, seed=3), deal_roles(board, seed=3))


class TemplateTest(unittest.TestCase):
    """P3-1：Hunter开枪的模板。"""

    def test_hunter_shot_template(self) -> None:
        judge = JudgeAgent(roles_for(DEFAULT_BOARD), board=DEFAULT_BOARD, seed=1)
        message = judge.say("hunter_shot", {"seat": 3, "target": 5})
        self.assertEqual(message.text, "3 号（Hunter）开枪带走了 5 号。")


if __name__ == "__main__":
    unittest.main()
