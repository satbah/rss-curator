import asyncio
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

_OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
# ローカル LLM はリクエストが混むとキュー待ちが長くなるため余裕を持たせる
_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "180"))

# 同時推論リクエスト数の上限。複数フィードが同時にポーリングされても Ollama に
# リクエストが殺到しないよう、プロセス全体で 1 つのセマフォを共有する。
# （呼び出しごとに生成するとフィード数ぶん多重化してしまうため module レベルに置く）
_sem: "asyncio.Semaphore | None" = None


def _get_semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(int(os.getenv("OLLAMA_CONCURRENCY", "2")))
    return _sem


def _build_system_prompt(interests: list[str]) -> str:
    items = "\n".join(f"{i + 1}. {interest}" for i, interest in enumerate(interests))
    return (
        "あなたはニュース記事の関連性を判定するアシスタントです。\n"
        f"ユーザーの興味は以下の通りです：\n{items}\n"
        "記事のタイトルと要約を受け取り、次のJSONのみを返してください（他のテキストは不要）：\n"
        '{"match": true, "reason": "判定理由（日本語・1文）"}\n'
        "または\n"
        '{"match": false, "reason": "判定理由（日本語・1文）"}'
    )


async def _check_entry(
    entry: dict,
    system_text: str,
    client: httpx.AsyncClient,
) -> tuple[str, dict, str | None]:
    """記事を判定し ("match"|"nomatch"|"error", entry, reason) を返す。

    "error" は LLM 呼び出し自体が失敗したケース（タイムアウト等）。呼び出し側で
    SeenGuid 登録から除外し、次回ポーリングでリトライできるようにする。
    """
    user_message = f"タイトル: {entry.get('title', '')}\n要約: {entry.get('summary', '')}"
    payload = {
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "format": "json",
        # reason（日本語1文）が途中で切れると JSON が壊れるため余裕を持たせる
        "options": {"temperature": 0, "num_predict": 256},
    }
    # 通信/タイムアウト/サーバエラーは一時的とみなしリトライさせる（"error"）。
    try:
        resp = await client.post(
            f"{_OLLAMA_BASE}/api/chat",
            json=payload,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
    except (httpx.TransportError, httpx.HTTPStatusError) as exc:
        # タイムアウト系は str(exc) が空になるため型名も出す
        logger.error(
            "ai_filter: transient error on entry %r — %s: %s",
            entry.get("title"),
            type(exc).__name__,
            exc,
        )
        return ("error", entry, None)

    # モデル出力の解析失敗は再試行しても直りにくいので no-match 扱い（seen 登録）。
    try:
        data = json.loads(resp.json()["message"]["content"].strip())
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning(
            "ai_filter: unparseable response for %r — %s; treating as no-match",
            entry.get("title"),
            exc,
        )
        return ("nomatch", entry, None)

    if data.get("match"):
        return ("match", entry, data.get("reason", ""))
    return ("nomatch", entry, None)


async def filter_articles(
    entries: list[dict],
    interests: list[str],
) -> tuple[list[tuple[dict, str]], list[dict]]:
    """(matched, errored) を返す。

    matched: 興味に合致した (entry, reason) のリスト。
    errored: LLM 呼び出しに失敗した entry のリスト（SeenGuid に登録しないでリトライ）。
    """
    system_text = _build_system_prompt(interests)
    # プロセス全体で共有するセマフォ（複数フィードの同時ポーリングをまとめて制限）
    sem = _get_semaphore()

    async with httpx.AsyncClient() as client:
        async def _limited(entry: dict) -> tuple[str, dict, str | None]:
            async with sem:
                return await _check_entry(entry, system_text, client)

        results = await asyncio.gather(*[_limited(e) for e in entries])

    matched = [(entry, reason) for status, entry, reason in results if status == "match"]
    errored = [entry for status, entry, _ in results if status == "error"]
    return matched, errored
