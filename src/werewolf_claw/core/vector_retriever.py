"""向量检索客户端：从 Werewolf-VectorDB 那边建好的 Chroma 向量库里，
按当前对局形势检索相似的历史对局片段。

设计要点：

- **懒加载**：`chromadb` 和 `sentence-transformers` 是 Werewolf-VectorDB 项目的依赖，
  不强制 Claw 项目装这俩包。只有真正调用检索时才 import，导入失败就返回友好提示，
  不打断 Agent 流程（参考脚本的「三次失败则暂停」精神，这里直接降级）。
- **配置来源**：Chroma Cloud 凭证和 embedding 模型名从环境变量读，查找顺序和
  `core.llm` 一致——仓库根目录的 `.env` 优先，再找当前工作目录；都没有就去隔壁
  `Werewolf-VectorDB/.env` 找（两个项目通常挨着放）。找不到就降级。
- **检索逻辑**：复用 `build_db.py` 的父子召回——先在 utterance / skill_action 两个
  子集合里查相似 chunk，再回溯到 phase、game，把整局的关键片段聚拢起来。
- **单例**：embedding 模型加载很慢（首次下载几十秒到几分钟），客户端只建一次，
  之后整个进程复用。
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

# Chroma 四个 collection 的名字，和 build_db.py 里写死的一致。
GAME_COLLECTION = "game"
PHASE_COLLECTION = "phase"
UTTERANCE_COLLECTION = "utterance"
SKILL_COLLECTION = "skill_action"

CHILD_COLLECTIONS = (UTTERANCE_COLLECTION, SKILL_COLLECTION)

# 默认检索参数：和 build_db.py 的演示一致。
DEFAULT_TOP_K = 10
DEFAULT_MAX_PHASES = 3
DEFAULT_MAX_GAMES = 2

_lock = threading.Lock()
_client: Optional["VectorRetriever"] = None


# ------------------------------------------------------------------ 配置


def _env_candidates() -> list[Path]:
    """`.env` 的查找顺序：仓库根目录 -> 当前工作目录 -> 隔壁 Werewolf-VectorDB。

    和 `core.llm.env_candidates()` 对齐，但多一条：Chroma 凭证本来就在 VectorDB
    项目里，两个 repo 通常挨着放，找不到时也去那边看看。
    """
    paths: list[Path] = []
    # Claw 仓库根目录
    claw_root = Path(__file__).resolve().parents[3]
    if (claw_root / "pyproject.toml").is_file():
        paths.append(claw_root / ".env")
    # 当前工作目录
    cwd_env = Path.cwd() / ".env"
    if cwd_env not in paths:
        paths.append(cwd_env)
    # 隔壁 Werewolf-VectorDB：和 Claw 同级目录下的兄弟项目
    sibling = claw_root.parent / "Werewolf-VectorDB" / ".env"
    if sibling not in paths:
        paths.append(sibling)
    return paths


def _load_env() -> None:
    """把第一个找到的 .env 加载进来。已有同名系统变量不覆盖。"""
    for path in _env_candidates():
        if path.is_file():
            load_dotenv(path, override=False)
            return


_load_env()

# 读配置：Chroma Cloud 凭证 + embedding 模型。
CHROMA_API_KEY = os.getenv("CHROMA_API_KEY", "")
CHROMA_TENANT = os.getenv("CHROMA_TENANT", "")
CHROMA_DATABASE = os.getenv("CHROMA_DATABASE", "")
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
EMBED_DEVICE = os.getenv("EMBED_DEVICE", "cpu")
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "32"))


# ------------------------------------------------------------------ 客户端


@dataclass
class RetrievalHit:
    """一条检索结果：相似对局的一个片段。"""

    game_id: str
    game_doc: str
    game_result: str
    phase: str
    phase_doc: str
    # 这一个 phase 下命中的 utterance / skill_action 片段
    utterances: list[dict[str, Any]]
    skills: list[dict[str, Any]]
    # 这局在召回里排第几（0 最相似）
    rank: int


class VectorRetriever:
    """向量检索客户端：单例，懒加载 chromadb 和 embedding 模型。

    用法::

        client = get_retriever()
        if client is not None:
            hits = client.retrieve("阶段：Day 2 Night\\n行动：狼人刀人")
            print(client.format(hits))
    """

    def __init__(self) -> None:
        self._embed: Any = None  # LocalEmbeddingClient 实例
        self._chroma: Any = None  # chromadb CloudClient / PersistentClient
        self._collections: dict[str, Any] = {}
        self._error: str = ""  # 初始化失败的说明，给上层降级用

    # ------------------------------------------------------------------ 初始化

    def status(self) -> str:
        """检索可用性说明："" 表示可用，否则是不可用的原因（给上层降级提示）。"""
        return self._ensure_ready()

    def _ensure_ready(self) -> str:
        """首次调用时加载模型和连接 Chroma，成功返回 ""，失败返回原因。"""
        if self._chroma is not None:
            return ""
        if self._error:
            return self._error

        try:
            import chromadb  # noqa: F401  懒加载
        except ImportError as exc:
            self._error = (
                f"没装 chromadb，无法检索向量库：{exc}。"
                "在 Werewolf-VectorDB 项目里 `pip install chromadb sentence-transformers`。"
            )
            return self._error

        if not CHROMA_API_KEY or not CHROMA_TENANT or not CHROMA_DATABASE:
            self._error = (
                "Chroma Cloud 凭证不全（CHROMA_API_KEY / CHROMA_TENANT / CHROMA_DATABASE），"
                "请在 .env 里配好，或先跑 Werewolf-VectorDB/scripts/build_db.py 建库。"
            )
            return self._error

        try:
            self._embed = _LocalEmbedding(
                model_name=EMBED_MODEL,
                device=EMBED_DEVICE,
                batch_size=EMBED_BATCH_SIZE,
            )
        except Exception as exc:  # 模型加载失败最常见：没网下不下来
            self._error = f"加载 embedding 模型失败：{exc}"
            return self._error

        try:
            self._chroma = chromadb.CloudClient(
                api_key=CHROMA_API_KEY,
                tenant=CHROMA_TENANT,
                database=CHROMA_DATABASE,
            )
            # 提前把四个 collection 拿到手，省得每次检索都 get_collection
            for name in (GAME_COLLECTION, PHASE_COLLECTION,
                         UTTERANCE_COLLECTION, SKILL_COLLECTION):
                try:
                    self._collections[name] = self._chroma.get_collection(
                        name, embedding_function=None
                    )
                except Exception:
                    # 某个 collection 还没建（库是空的），跳过；检索时再判空
                    pass
        except Exception as exc:
            self._error = f"连接 Chroma Cloud 失败：{exc}"
            self._chroma = None
            return self._error

        return ""

    # ------------------------------------------------------------------ 检索

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        max_phases: int = DEFAULT_MAX_PHASES,
        max_games: int = DEFAULT_MAX_GAMES,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[RetrievalHit]:
        """按查询文本检索相似历史对局片段。

        逻辑复用 `build_db.retrieve`：先在 utterance / skill_action 两个子集合里查相似
        chunk，按 parent_id 聚到 phase，再回溯到 game。返回打平后的命中列表。
        """
        err = self._ensure_ready()
        if err:
            return []

        query = (query or "").strip()
        if not query:
            return []

        q_emb = self._embed.encode([query])
        if not q_emb:
            return []

        # 1. 子集合里查相似 chunk，按 parent_id 聚到 phase
        by_phase: dict[str, list[dict[str, Any]]] = {}
        for name in CHILD_COLLECTIONS:
            col = self._collections.get(name)
            if col is None or col.count() == 0:
                continue
            kwargs: dict[str, Any] = {
                "query_embeddings": q_emb,
                "n_results": top_k,
                "include": ["documents", "metadatas", "distances"],
            }
            if filters:
                kwargs["where"] = filters
            try:
                res = col.query(**kwargs)
            except Exception:
                continue
            ids = res.get("ids", [[]])[0]
            docs = res.get("documents", [[]])[0]
            mds = res.get("metadatas", [[]])[0]
            dists = res.get("distances", [[]])[0]
            for cid, doc, md, dist in zip(ids, docs, mds, dists):
                pid = (md or {}).get("parent_id", "")
                if not pid:
                    continue
                by_phase.setdefault(pid, []).append({
                    "id": cid,
                    "doc": doc,
                    "md": md or {},
                    "dist": dist,
                    "collection": name,
                })

        if not by_phase:
            return []

        # 2. 按 phase 的最近距离排序，取前 max_phases 个
        sorted_phases = sorted(
            by_phase.items(),
            key=lambda kv: min(h["dist"] for h in kv[1]),
        )
        phase_ids = [pid for pid, _ in sorted_phases[:max_phases]]

        phase_col = self._collections.get(PHASE_COLLECTION)
        if phase_col is None:
            return []
        phases = phase_col.get(
            ids=phase_ids, include=["documents", "metadatas"]
        )

        by_game: dict[str, list[str]] = {}
        phase_info: dict[str, dict[str, Any]] = {}
        pids = phases.get("ids", []) or []
        pdocs = phases.get("documents", []) or []
        pmds = phases.get("metadatas", []) or []
        for pid, pdoc, pmd in zip(pids, pdocs, pmds):
            gid = (pmd or {}).get("parent_id", "")
            by_game.setdefault(gid, []).append(pid)
            phase_info[pid] = {"doc": pdoc, "meta": pmd or {}}

        # 3. 回溯到 game，取前 max_games 局
        game_ids = list(by_game.keys())[:max_games]
        game_col = self._collections.get(GAME_COLLECTION)
        if game_col is None or not game_ids:
            return []
        games = game_col.get(
            ids=game_ids, include=["documents", "metadatas"]
        )
        game_info: dict[str, dict[str, Any]] = {}
        gids = games.get("ids", []) or []
        gdocs = games.get("documents", []) or []
        gmds = games.get("metadatas", []) or []
        for gid, gdoc, gmd in zip(gids, gdocs, gmds):
            game_info[gid] = {"doc": gdoc, "meta": gmd or {}}

        # 4. 打平成 RetrievalHit 列表
        hits: list[RetrievalHit] = []
        for rank, (gid, pid_list) in enumerate(by_game.items()):
            if gid not in game_info:
                continue
            ginfo = game_info[gid]
            for pid in pid_list:
                pinfo = phase_info.get(pid, {})
                phase_hits = by_phase.get(pid, [])
                grouped: dict[str, list[dict[str, Any]]] = {
                    UTTERANCE_COLLECTION: [],
                    SKILL_COLLECTION: [],
                }
                for h in phase_hits:
                    grouped.setdefault(h["collection"], []).append(h)
                for k in grouped:
                    grouped[k].sort(key=lambda x: x["dist"])
                hits.append(RetrievalHit(
                    game_id=gid,
                    game_doc=ginfo["doc"],
                    game_result=str(ginfo["meta"].get("game_result", "Unknown")),
                    phase=str(pinfo.get("meta", {}).get("phase", pid)),
                    phase_doc=str(pinfo.get("doc", "")),
                    utterances=grouped[UTTERANCE_COLLECTION],
                    skills=grouped[SKILL_COLLECTION],
                    rank=rank,
                ))
        return hits

    # ------------------------------------------------------------------ 格式化

    def format(self, hits: list[RetrievalHit], *, max_per_kind: int = 3) -> str:
        """把检索结果格式化成给模型看的文本。

        每局一段：先报结局和阶段，再列最相似的几条发言片段和技能动作。
        控制长度：每局每类最多列 `max_per_kind` 条，避免 prompt 太长。
        """
        if not hits:
            return "没有检索到相似的历史对局。"
        # 按 game_id 分组，同局的多段挨在一起
        by_game: dict[str, list[RetrievalHit]] = {}
        for h in hits:
            by_game.setdefault(h.game_id, []).append(h)

        lines: list[str] = []
        for gid, group in by_game.items():
            first = group[0]
            lines.append(
                f"【相似对局 {gid}（相似度排名第 {first.rank + 1}）】"
                f"结果：{first.game_result}"
            )
            lines.append(f"对局概览：{first.game_doc}")
            for h in group:
                lines.append(f"\n— 阶段：{h.phase}")
                if h.phase_doc:
                    # phase_doc 已经是多行结构，压一下空行
                    lines.append(h.phase_doc)
                if h.utterances:
                    lines.append("  相似发言片段：")
                    for u in h.utterances[:max_per_kind]:
                        md = u.get("md", {})
                        speaker = md.get("speaker", "?")
                        role = md.get("offline_true_role", "未知")
                        dist = u.get("dist", 0.0)
                        lines.append(
                            f"    [{speaker} 号·视角 {role}·距离 {dist:.3f}] "
                            f"{u.get('doc', '')}"
                        )
                if h.skills:
                    lines.append("  相似技能动作：")
                    for s in h.skills[:max_per_kind]:
                        md = s.get("md", {})
                        action = md.get("action", "?")
                        actor = md.get("actor_role", "?")
                        target = md.get("target", "?")
                        dist = s.get("dist", 0.0)
                        lines.append(
                            f"    [{actor} {action} {target} 号·距离 {dist:.3f}] "
                            f"{s.get('doc', '')}"
                        )
            lines.append("")  # 局与局之间空一行
        return "\n".join(lines).strip()


# ------------------------------------------------------------------ embedding 包装


class _LocalEmbedding:
    """sentence-transformers 的薄包装：和 build_db.LocalEmbeddingClient 一个意思，
    但放进 Claw 自己的模块里，不依赖 VectorDB 项目的代码。

    用 `sentence_transformers.SentenceTransformer` 本地编码，不联网。
    """

    def __init__(self, model_name: str, device: str = "cpu",
                 batch_size: int = 32, normalize: bool = True) -> None:
        from sentence_transformers import SentenceTransformer
        try:
            self.model = SentenceTransformer(
                model_name, device=device, local_files_only=True
            )
        except Exception:
            self.model = SentenceTransformer(model_name, device=device)
        self.batch_size = batch_size
        self.normalize = normalize

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # 按长度排序编码，长文本后处理，和 build_db 一致
        order = sorted(range(len(texts)), key=lambda k: len(texts[k]))
        out: list[list[float] | None] = [None] * len(texts)
        for i in range(0, len(order), self.batch_size):
            pos = order[i : i + self.batch_size]
            vecs = self.model.encode(
                [texts[k] for k in pos],
                batch_size=self.batch_size,
                normalize_embeddings=self.normalize,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            for j, k in enumerate(pos):
                out[k] = vecs[j].tolist()
        return [v for v in out if v is not None]


# ------------------------------------------------------------------ 单例


def get_retriever() -> Optional[VectorRetriever]:
    """拿单例。首次调用时初始化；初始化失败也返回一个对象，后续 retrieve 会降级。"""
    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is not None:
            return _client
        _client = VectorRetriever()
        return _client


def retrieve_similar(
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    max_phases: int = DEFAULT_MAX_PHASES,
    max_games: int = DEFAULT_MAX_GAMES,
) -> tuple[str, list[RetrievalHit]]:
    """便捷入口：检索 + 格式化。

    返回 (给模型看的文本, 原始命中列表)。检索不可用时空文本 + 空列表，
    调用方按「没有参考资料」处理，不打断 Agent 流程。
    """
    client = get_retriever()
    if client is None:
        return "向量检索不可用。", []
    hits = client.retrieve(
        query, top_k=top_k, max_phases=max_phases, max_games=max_games
    )
    return client.format(hits), hits
