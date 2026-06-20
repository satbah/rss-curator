import asyncio
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

_OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
_TIMEOUT = 60.0


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
) -> tuple[dict, str] | None:
    user_message = f"タイトル: {entry.get('title', '')}\n要約: {entry.get('summary', '')}"
    payload = {
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_predict": 128},
    }
    try:
        resp = await client.post(
            f"{_OLLAMA_BASE}/api/chat",
            json=payload,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json()["message"]["content"].strip()
        data = json.loads(raw)
        if data.get("match"):
            return (entry, data.get("reason", ""))
    except Exception as exc:
        logger.error("ai_filter: skipping entry %r — %s", entry.get("title"), exc)
    return None


async def filter_articles(
    entries: list[dict],
    interests: list[str],
) -> list[tuple[dict, str]]:
    system_text = _build_system_prompt(interests)
    # Ollama はシングルプロセスなので並列リクエストを絞る
    sem = asyncio.Semaphore(int(os.getenv("OLLAMA_CONCURRENCY", "2")))

    async with httpx.AsyncClient() as client:
        async def _limited(entry: dict) -> tuple[dict, str] | None:
            async with sem:
                return await _check_entry(entry, system_text, client)

        results = await asyncio.gather(*[_limited(e) for e in entries])

    return [r for r in results if r is not None]
