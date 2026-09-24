"""LLM 调用封装，基于 openai SDK。

对外提供两个入口：

- `chat()`: 简单调用。给一句提示词，直接拿回回复文本。
- `chat_full()`: 全参数调用。透传 SDK 的生成参数，拿回原始 `ChatCompletion` 对象，
  可以继续读 `usage`、`tool_calls`、`finish_reason` 等字段。

配置从环境变量读取：

- `OPENAI_API_KEY`: 必填，API 密钥。
- `OPENAI_BASE_URL`: 可选，兼容 OpenAI 协议的服务地址。
- `LLM_MODEL` 或 `OPENAI_MODEL`: 可选，模型名。
- `LLM_PROFILE_NAME`: 可选，这套配置的名字，在设置页里可以改。

模块导入时会加载 `.env`（先找仓库根目录，再找当前工作目录），`.env` 里的值覆盖同名的
系统环境变量，所以命令行 demos、FastAPI 服务都用同一份配置。密钥、地址、模型名都在调用时
读取，改完用 `save_env()` 或 `reload_env()` 就能立即生效，不用重启。
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import NOT_GIVEN, NotGiven, OpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam

FALLBACK_MODEL = "deepseek-flash"
DEFAULT_PROFILE_NAME = "default"

# 多套模型配置：LLM_PROFILE_<序号>_NAME / _API_KEY / _BASE_URL / _MODEL
PROFILE_PREFIX = "LLM_PROFILE_"
PROFILE_FIELDS = ("NAME", "API_KEY", "BASE_URL", "MODEL")
MAX_PROFILES = 8

_env_path: Path | None = None
_client: OpenAI | None = None


def project_root() -> Path | None:
    """源码布局下的仓库根目录，找不到返回 None。"""
    candidate = Path(__file__).resolve().parents[3]
    return candidate if (candidate / "pyproject.toml").is_file() else None


def env_candidates() -> list[Path]:
    """`.env` 的查找顺序：仓库根目录 -> 当前工作目录。"""
    paths: list[Path] = []
    root = project_root()
    if root is not None:
        paths.append(root / ".env")
    current = Path.cwd() / ".env"
    if current not in paths:
        paths.append(current)
    return paths


def load_env() -> Path | None:
    """加载 `.env`（覆盖同名环境变量），返回实际加载的文件。"""
    global _env_path
    for path in env_candidates():
        if path.is_file():
            load_dotenv(path, override=True)
            _env_path = path
            apply_active_profile()
            return path
    return None


def env_path() -> Path:
    """设置要写回的文件：已经加载的 `.env`，没有就用仓库根目录下的。"""
    if _env_path is not None:
        return _env_path
    root = project_root()
    return root / ".env" if root is not None else Path.cwd() / ".env"


def reload_env() -> None:
    """重新读 `.env` 并丢掉缓存的客户端，改完配置立即生效。"""
    global _client
    load_env()
    _client = None


def profile_name() -> str:
    """当前生效的配置名。"""
    return active_profile()["name"] or DEFAULT_PROFILE_NAME


def profile_env_key(profile_id: str, field: str) -> str:
    """某一套配置在 `.env` 里的键名，例如 LLM_PROFILE_2_API_KEY。"""
    return f"{PROFILE_PREFIX}{profile_id}_{field}"


def list_profiles() -> list[dict[str, str]]:
    """读出 `.env` 里的多套配置；一个都没有时按单套配置的老键兜底。"""
    profiles: list[dict[str, str]] = []
    for index in range(1, MAX_PROFILES + 1):
        profile_id = str(index)
        fields = {
            field: os.environ.get(profile_env_key(profile_id, field), "")
            for field in PROFILE_FIELDS
        }
        if not any(fields.values()):
            continue
        profiles.append(
            {
                "id": profile_id,
                "name": fields["NAME"] or f"模型配置{index}",
                "api_key": fields["API_KEY"],
                "base_url": fields["BASE_URL"],
                "model": fields["MODEL"],
            }
        )

    if not profiles:
        profiles.append(
            {
                "id": "1",
                "name": os.environ.get("LLM_PROFILE_NAME") or DEFAULT_PROFILE_NAME,
                "api_key": os.environ.get("OPENAI_API_KEY", ""),
                "base_url": os.environ.get("OPENAI_BASE_URL", ""),
                "model": os.environ.get("LLM_MODEL") or os.environ.get("OPENAI_MODEL", ""),
            }
        )
    return profiles


def active_profile_id() -> str:
    """当前生效的配置 id，取不到就用第一套。"""
    ids = [profile["id"] for profile in list_profiles()]
    value = os.environ.get("LLM_ACTIVE_PROFILE", "").strip()
    return value if value in ids else ids[0]


def active_profile() -> dict[str, str]:
    """当前生效的那套配置。"""
    current = active_profile_id()
    for profile in list_profiles():
        if profile["id"] == current:
            return profile
    return list_profiles()[0]


def apply_active_profile() -> None:
    """把当前配置摊平到进程环境变量里，`get_client()` 和 `default_model()` 直接用。"""
    profile = active_profile()
    if profile["api_key"]:
        os.environ["OPENAI_API_KEY"] = profile["api_key"]
    if profile["base_url"]:
        os.environ["OPENAI_BASE_URL"] = profile["base_url"]
    else:
        os.environ.pop("OPENAI_BASE_URL", None)
    if profile["model"]:
        os.environ["LLM_MODEL"] = profile["model"]


def env_file_keys(path: Path) -> list[str]:
    """`.env` 文件里出现过的键名。"""
    if not path.is_file():
        return []
    keys: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if match:
            keys.append(match.group(1))
    return keys


def mask_secret(value: str) -> str:
    """给密钥打码，只留前 6 位和后 4 位。"""
    if not value:
        return ""
    if len(value) <= 12:
        return "*" * len(value)
    return f"{value[:6]}{'*' * 8}{value[-4:]}"


def _format_env_value(value: str) -> str:
    """含空格、引号或 # 的值要加引号，否则 dotenv 会解析错。"""
    if value == "" or re.search(r'[\s#"\']', value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def save_env(values: Mapping[str, str], remove: Iterable[str] = ()) -> Path:
    """把配置写进 `.env`：保留注释和其他键，删掉 `remove` 里的键，写完自动重新加载。"""
    path = env_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    if not lines:
        lines = ["本地私有配置，已被 .gitignore 忽略，不要提交到仓库。", "# 换成自己的密钥。", ""]

    dropped = set(remove)
    kept: list[str] = []
    for line in lines:
        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if match and match.group(1) in dropped:
            continue
        kept.append(line)
    lines = kept

    pending = dict(values)
    for index, line in enumerate(lines):
        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if match and match.group(1) in pending:
            key = match.group(1)
            lines[index] = f"{key}={_format_env_value(pending.pop(key))}"
    for key, value in pending.items():
        lines.append(f"{key}={_format_env_value(value)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    for key in dropped:
        os.environ.pop(key, None)
    reload_env()
    return path


def save_profiles(profiles: Sequence[Mapping[str, str]], active_id: str = "") -> Path:
    """把多套配置写进 `.env`，并把当前生效的那套摊平到老键上。"""
    normalized: list[dict[str, str]] = []
    for index, profile in enumerate(list(profiles)[:MAX_PROFILES], start=1):
        normalized.append(
            {
                "id": str(index),
                "name": (profile.get("name") or f"模型配置{index}").strip(),
                "api_key": (profile.get("api_key") or "").strip(),
                "base_url": (profile.get("base_url") or "").strip(),
                "model": (profile.get("model") or "").strip(),
            }
        )
    if not normalized:
        raise ValueError("至少要有一套模型配置")

    ids = {profile["id"] for profile in normalized}
    current = active_id if active_id in ids else normalized[0]["id"]

    values: dict[str, str] = {"LLM_ACTIVE_PROFILE": current}
    for profile in normalized:
        values[profile_env_key(profile["id"], "NAME")] = profile["name"]
        values[profile_env_key(profile["id"], "API_KEY")] = profile["api_key"]
        values[profile_env_key(profile["id"], "BASE_URL")] = profile["base_url"]
        values[profile_env_key(profile["id"], "MODEL")] = profile["model"]

    active = next(profile for profile in normalized if profile["id"] == current)
    values["LLM_PROFILE_NAME"] = active["name"]
    values["OPENAI_API_KEY"] = active["api_key"]
    values["OPENAI_BASE_URL"] = active["base_url"]
    values["LLM_MODEL"] = active["model"]

    stale = [
        key
        for key in env_file_keys(env_path())
        if key.startswith(PROFILE_PREFIX) and key not in values
    ]
    return save_env(values, remove=stale)


# 导入模块就读一次 .env，命令行、Web 服务、脚本都用同一份配置。
load_env()


def default_model() -> str:
    """当前默认模型名，每次调用都重新读环境变量。
    顺序：`LLM_MODEL` -> `OPENAI_MODEL` -> `FALLBACK_MODEL`。
    """
    return os.environ.get("LLM_MODEL") or os.environ.get("OPENAI_MODEL") or FALLBACK_MODEL


def get_client() -> OpenAI:
    """返回全局客户端，首次调用时根据环境变量创建。"""
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("未设置环境变量 OPENAI_API_KEY")
        _client = OpenAI(api_key=api_key, base_url=os.environ.get("OPENAI_BASE_URL") or None)
    return _client


def set_client(client: OpenAI | None) -> None:
    """替换全局客户端；传 None 表示清除缓存。

    用于测试注入假客户端，或接入 AzureOpenAI 等自定义实例。
    """
    global _client
    _client = client


def build_messages(
    prompt: str,
    system: str | None = None,
    history: Iterable[ChatCompletionMessageParam] | None = None,
) -> list[ChatCompletionMessageParam]:
    """拼装消息列表，顺序为：system、history、当前 user 提示词。"""
    messages: list[ChatCompletionMessageParam] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.extend(history or [])
    messages.append({"role": "user", "content": prompt})
    return messages


def chat(
    prompt: str,
    *,
    system: str | None = None,
    history: Iterable[ChatCompletionMessageParam] | None = None,
    model: str | None = None,
    temperature: float | None = None,
) -> str:
    """简单调用，返回模型回复的纯文本。

    `model` 省略时用 `default_model()` 的结果。
    """
    completion = chat_full(
        build_messages(prompt, system=system, history=history),
        model=model,
        temperature=NOT_GIVEN if temperature is None else temperature,
    )
    return completion.choices[0].message.content or ""


def chat_full(
    messages: Iterable[ChatCompletionMessageParam],
    *,
    model: str | None = None,
    temperature: float | NotGiven = NOT_GIVEN,
    top_p: float | NotGiven = NOT_GIVEN,
    max_tokens: int | NotGiven = NOT_GIVEN,
    max_completion_tokens: int | NotGiven = NOT_GIVEN,
    n: int | NotGiven = NOT_GIVEN,
    stop: str | Sequence[str] | NotGiven = NOT_GIVEN,
    presence_penalty: float | NotGiven = NOT_GIVEN,
    frequency_penalty: float | NotGiven = NOT_GIVEN,
    logit_bias: Mapping[str, int] | NotGiven = NOT_GIVEN,
    seed: int | NotGiven = NOT_GIVEN,
    response_format: Mapping[str, Any] | NotGiven = NOT_GIVEN,
    tools: Iterable[Mapping[str, Any]] | NotGiven = NOT_GIVEN,
    tool_choice: str | Mapping[str, Any] | NotGiven = NOT_GIVEN,
    parallel_tool_calls: bool | NotGiven = NOT_GIVEN,
    reasoning_effort: str | NotGiven = NOT_GIVEN,
    service_tier: str | NotGiven = NOT_GIVEN,
    store: bool | NotGiven = NOT_GIVEN,
    metadata: Mapping[str, str] | NotGiven = NOT_GIVEN,
    user: str | NotGiven = NOT_GIVEN,
    timeout: float | None = None,
    extra_body: Mapping[str, Any] | None = None,
) -> ChatCompletion:
    """全参数调用，返回原始 `ChatCompletion` 对象。

    `model` 省略时用 `default_model()` 的结果。
    参数默认值是 `NOT_GIVEN`，表示不发送该字段，交给服务端取默认值。
    要显式传空值时用 `None`，例如 `stop=None`。
    流式输出未封装，需要时用 `get_client().chat.completions.create(..., stream=True)`。
    """
    optional: dict[str, Any] = {
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "max_completion_tokens": max_completion_tokens,
        "n": n,
        "stop": stop,
        "presence_penalty": presence_penalty,
        "frequency_penalty": frequency_penalty,
        "logit_bias": logit_bias,
        "seed": seed,
        "response_format": response_format,
        "tools": tools,
        "tool_choice": tool_choice,
        "parallel_tool_calls": parallel_tool_calls,
        "reasoning_effort": reasoning_effort,
        "service_tier": service_tier,
        "store": store,
        "metadata": metadata,
        "user": user,
        "timeout": timeout,
        "extra_body": extra_body,
    }
    kwargs = {name: value for name, value in optional.items() if not isinstance(value, NotGiven)}
    resolved_model = model or default_model()
    return get_client().chat.completions.create(messages=list(messages), model=resolved_model, **kwargs)
