"""玩家 Agent 的最小单测：信息隔离、泄露校验、言行不一、净压力、票型、工具轮数。

跑法（仓库根目录）：`python -m unittest discover -s tests`
"""

from __future__ import annotations

import unittest
from collections.abc import Sequence
from typing import Any

from werewolf_claw.agents.player_agent import Decision, PlayerAgent
from werewolf_claw.boards import DEFAULT_BOARD, STANDARD12_BOARD
from werewolf_claw.core.screen import Screen

ALIVE = (1, 2, 3, 4, 5, 6)


def make_player(
    seat: int = 1,
    role: str = "Villager",
    *,
    chat: Any = None,
    board: Any = None,
) -> PlayerAgent:
    return PlayerAgent(seat, role, board=board or DEFAULT_BOARD, chat=chat)


def feed(player: PlayerAgent, screen: Screen) -> None:
    """把大屏上这个座位能看到的消息推进它的收件箱。"""
    player.receive(screen.read(player.seat))


class TranscriptChannelTest(unittest.TestCase):
    """P0-2：transcript 按通道过滤，公开发言的 prompt 里不能有私聊。"""

    def test_transcript_filters_channel(self) -> None:
        screen = Screen()
        screen.publish(1, "3 号：我觉得 5 号可疑。", kind="statement", facts={"seat": 3})
        screen.send([1], 1, "3 号查验了 5 号，结果是好人阵营。", kind="receipt")
        screen.send([2], 1, "只给 2 号的悄悄话。", kind="receipt")
        player = make_player(1, "Seer")
        feed(player, screen)

        everything = player.transcript()
        self.assertIn("我觉得 5 号可疑", everything)
        self.assertIn("结果是好人阵营", everything)
        self.assertNotIn("悄悄话", everything)  # 投给别人的私聊根本没收进来
        self.assertNotIn("结果是好人阵营", player.transcript(channel="public"))
        self.assertNotIn("我觉得 5 号可疑", player.transcript(channel="private"))

    def test_statement_prompt_hides_private_receipt(self) -> None:
        screen = Screen()
        screen.send([1], 1, "3 号查验了 5 号，结果是好人阵营。", kind="receipt")
        screen.publish(1, "3 号：我觉得 5 号可疑。", kind="statement", facts={"seat": 3})
        seer = make_player(1, "Seer")
        feed(seer, screen)
        seer.open_private_chat()
        seer.sync_board()

        prompt = seer.statement_prompt(ALIVE)
        self.assertNotIn("结果是好人阵营", prompt)
        self.assertIn("我觉得 5 号可疑", prompt)
        self.assertTrue(any("我觉得 5 号可疑" in line for line in seer.public_notes))

    def test_statement_prompt_hides_team_channel(self) -> None:
        screen = Screen()
        screen.send([1, 4], 1, "今晚的目标 → 5 号。", kind="phase_target")
        screen.publish(1, "2 号：大家报一下自己的怀疑对象。", kind="statement", facts={"seat": 2})
        wolf = make_player(1, "Werewolf")
        feed(wolf, screen)
        wolf.open_private_chat()
        wolf.sync_board()

        prompt = wolf.statement_prompt((1, 2, 4))
        self.assertNotIn("今晚的目标", prompt)
        self.assertIn("大家报一下", prompt)

        team = wolf._team_prompt("Werewolf", (1, 4), 1)
        self.assertIn("今晚的目标", team)  # 队伍频道照旧能看到
        self.assertIn("大家报一下", team)  # 公开大屏也照常给
        self.assertNotIn("你看到的大屏", team)

    def test_night_and_death_prompts_relabel_inbox(self) -> None:
        screen = Screen()
        screen.send(
            [1], 1, "今晚被袭击的是 5 号。", kind="phase", facts={"phase": "Witch", "seats": [1]}
        )
        witch = make_player(1, "Witch", board=STANDARD12_BOARD)
        feed(witch, screen)

        night = witch._night_prompt("Witch", (1, 2, 3), (2, 3))
        self.assertIn("今晚被袭击的是 5 号", night)
        self.assertNotIn("大屏", night)
        death = witch._death_prompt("attack", (1, 2, 3))
        self.assertIn("今晚被袭击的是 5 号", death)
        self.assertNotIn("大屏", death)


class StatementPrivacyTest(unittest.TestCase):
    """P1-1：复述私聊原文、点名两个队友都要被打回。"""

    def test_copying_private_receipt_is_rejected(self) -> None:
        screen = Screen()
        receipt = "3 号查验了 5 号，结果是好人阵营。"
        screen.send([1], 1, receipt, kind="receipt")
        player = make_player(1, "Seer")
        feed(player, screen)

        copied = {"text": f"我是 1 号，{receipt}", "target": 5, "action": "accuse"}
        problems = player._check_statement(copied, ALIVE)
        self.assertTrue(any("疑似泄露私聊内容" in item for item in problems), problems)

        # 报自己的查验是Seer的本职，这时公开查验结果不算泄露
        reported = {"text": f"我是 1 号，{receipt}", "target": 5, "action": "report"}
        self.assertFalse(
            [item for item in player._check_statement(reported, ALIVE) if "泄露" in item]
        )

    def test_naming_two_allies_is_rejected(self) -> None:
        wolf = make_player(1, "Werewolf")
        wolf.allies = {3, 4}
        problems = wolf._check_statement(
            {"text": "我觉得 3 号、4 号都不像狼。", "target": 2, "action": "accuse"}, ALIVE
        )
        self.assertTrue(any("疑似暴露队友" in item for item in problems), problems)

    def test_seat_number_boundary(self) -> None:
        wolf = make_player(1, "Werewolf")
        wolf.allies = {3}
        problems = wolf._check_statement(
            {"text": "13 号挺可疑的，先投他。", "target": None, "action": "accuse"}, ALIVE
        )
        self.assertFalse([item for item in problems if "队友" in item], problems)


class BallotConsistencyTest(unittest.TestCase):
    """P1-2：投票和公开发言对不上要记一笔。"""

    def test_statement_gap_is_recorded(self) -> None:
        screen = Screen()
        screen.publish(
            1,
            "1 号：我觉得 3 号最可疑。",
            kind="statement",
            facts={"seat": 1, "target": 3, "action": "accuse"},
        )
        player = make_player(1, "Villager", chat=lambda prompt, system=None: '{"target": 5}')
        feed(player, screen)

        self.assertEqual(player.cast_ballot(ALIVE, Decision(target=3)), {"target": 5})
        self.assertTrue(
            any("言行不一：发言指认 3 号，实际投了 5 号" in note for note in player.notes),
            player.notes,
        )

    def test_same_target_records_nothing(self) -> None:
        screen = Screen()
        screen.publish(
            1,
            "1 号：我觉得 3 号最可疑。",
            kind="statement",
            facts={"seat": 1, "target": 3, "action": "accuse"},
        )
        player = make_player(1, "Villager", chat=lambda prompt, system=None: '{"target": 3}')
        feed(player, screen)

        player.cast_ballot(ALIVE, Decision(target=3))
        self.assertFalse([note for note in player.notes if "言行不一" in note], player.notes)


class PressureTest(unittest.TestCase):
    """P2-1：指认 +1、保人 -1、报查验不计。"""

    def test_pressures_are_net(self) -> None:
        screen = Screen()
        screen.publish(1, "1 号：3 号可疑。", kind="statement", facts={"seat": 1, "target": 3, "action": "accuse"})
        screen.publish(1, "2 号：我保 3 号。", kind="statement", facts={"seat": 2, "target": 3, "action": "defend"})
        screen.publish(1, "4 号：我查验 5 号，是好人阵营。", kind="statement", facts={"seat": 4, "target": 5, "action": "report"})
        player = make_player(1, "Villager")
        feed(player, screen)

        pressures = player._pressures()
        self.assertEqual(pressures[3], 0)
        self.assertNotIn(5, pressures)

        belief = player.reason(ALIVE)
        self.assertAlmostEqual(belief.guess(3).confidence, belief.guess(6).confidence)

    def test_old_message_without_action_counts_as_accuse(self) -> None:
        screen = Screen()
        screen.publish(1, "1 号：3 号可疑。", kind="statement", facts={"seat": 1, "target": 3})
        player = make_player(1, "Villager")
        feed(player, screen)
        self.assertEqual(player._pressures()[3], 1)


class VoteSignalTest(unittest.TestCase):
    """P2-2：给被票出局的人投过票 → 好人面微升。"""

    def test_voting_out_the_eliminated_raises_confidence(self) -> None:
        screen = Screen()
        screen.publish(1, "1 号投给 5 号。", kind="ballot", facts={"seat": 1, "target": 5})
        screen.publish(1, "2 号投给 3 号。", kind="ballot", facts={"seat": 2, "target": 3})
        screen.publish(
            1,
            "投票结果：5 号 3 票。",
            kind="vote",
            facts={"counts": {"5": 3}, "top": [5], "eliminated": 5},
        )
        player = make_player(6, "Villager")
        feed(player, screen)

        self.assertEqual(player._vote_pressure()[1], 1)
        belief = player.reason(ALIVE)
        self.assertGreater(belief.guess(1).confidence, belief.guess(2).confidence)
        self.assertGreater(belief.guess(2).confidence, 0.0)


class WitchPassTest(unittest.TestCase):
    """女巫可以捏着药不用：空目标是明确弃权，不能兜底成自动救人。

    回归：修复前模型/人类返回 target=null 会被判「缺少目标」退回规则建议，
    规则建议是自动用解药 → 狼刀永远打不死人（平安夜 bug）。
    """

    def test_witch_pass_is_accepted(self) -> None:
        witch = make_player(6, "Witch", chat=lambda prompt, system=None: '{"phase": "Witch", "target": null}')
        witch.attacked = 5

        action = witch.night_action("Witch", ALIVE)

        self.assertEqual(action["effect"], "")
        self.assertIsNone(action["target"])
        self.assertFalse(witch.used("save"))  # 弃权不烧药

    def test_witch_save_still_works(self) -> None:
        witch = make_player(6, "Witch", chat=lambda prompt, system=None: '{"phase": "Witch", "target": 5}')
        witch.attacked = 5

        action = witch.night_action("Witch", ALIVE)

        self.assertEqual(action["effect"], "save")
        self.assertEqual(action["target"], 5)
        self.assertTrue(witch.used("save"))

    def test_witch_poison_still_works(self) -> None:
        """解药已用完时，毒药目标照常可用。"""
        witch = make_player(6, "Witch", chat=lambda prompt, system=None: '{"phase": "Witch", "target": 3}')
        witch.attacked = 5
        witch.skill_history.append({"phase": "Witch", "target": 5, "effect": "save"})

        action = witch.night_action("Witch", ALIVE)

        self.assertEqual(action["effect"], "poison")
        self.assertEqual(action["target"], 3)

    def test_seer_null_target_still_falls_back(self) -> None:
        """不能弃权的角色（预言家）空目标依旧退回规则建议。"""
        seer = make_player(6, "Seer", chat=lambda prompt, system=None: '{"phase": "Seer", "target": null}')

        action = seer.night_action("Seer", ALIVE)

        self.assertEqual(action["effect"], "check")
        self.assertIsNotNone(action["target"])


class FlowTest(unittest.TestCase):
    """P3-4 / P4-1 / P4-2：夜间不算决策、工具能跑满轮数、解析失败也重试。"""

    def test_night_request_skips_decision(self) -> None:
        player = make_player(1, "Werewolf")
        calls: list[tuple[int, ...]] = []
        original = player.decide

        def spy(alive: Sequence[int]) -> Decision:
            calls.append(tuple(alive))
            return original(alive)

        player.decide = spy  # type: ignore[method-assign]
        player.night_action("Werewolf", (1, 2, 3))
        self.assertEqual(calls, [])

        player.statement((1, 2, 3))
        self.assertEqual(len(calls), 1)

    def test_ask_runs_tool_rounds_up_to_limit(self) -> None:
        tool_prompts: list[str] = []
        final_prompts: list[str] = []

        def chat(prompt: str, *, system: str | None = None) -> str:
            final_prompts.append(prompt)
            return "最终正文"

        def chat_with_tools(prompt: str, *, system: str | None = None, tools: Any = ()) -> Any:
            tool_prompts.append(prompt)
            round_no = len(tool_prompts)
            return "", [
                {
                    "id": f"call_{round_no}",
                    "function": {
                        "name": "note",
                        "arguments": '{"text": "第 %d 轮工具"}' % round_no,
                    },
                }
            ]

        chat.with_tools = chat_with_tools  # type: ignore[attr-defined]
        player = make_player(1, "Villager", chat=chat)

        self.assertEqual(player._ask("问题", "系统提示", with_tools=True), "最终正文")
        self.assertEqual(len(tool_prompts), 2)  # 两轮工具都跑了
        # 两轮的工具结果都拼进了最后那次 prompt
        self.assertEqual(final_prompts[0].count("[工具 note]"), 2)
        self.assertEqual(player.notes.count("工具 note：已记下。"), 2)

    def test_express_retries_after_parse_failure(self) -> None:
        replies = [
            "这不是 JSON",
            "还是不是 JSON",
            '{"text": "我是 1 号，我这边没有新的信息。", "target": null, "action": "accuse"}',
        ]
        player = make_player(1, "Villager", chat=lambda prompt, system=None: replies.pop(0))

        result = player.express(ALIVE)
        self.assertEqual(result["text"], "我是 1 号，我这边没有新的信息。")
        self.assertEqual(replies, [])


if __name__ == "__main__":
    unittest.main()
