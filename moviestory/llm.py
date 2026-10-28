"""LLM 调用封装：标准库 urllib 实现，自带重试与 JSON 容错解析。"""

from __future__ import annotations

import json
import logging
import random
import re
import time
import urllib.error
import urllib.request

log = logging.getLogger("moviestory.llm")


class LLMError(RuntimeError):
    pass


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```[a-zA-Z]*\s*\n(.*?)\n?```$", text, re.S)
    if fence:
        return fence.group(1).strip()
    return text


def _extract_json_block(text: str) -> str:
    """从混杂文本中截取第一个完整的 JSON 对象。"""
    start = text.find("{")
    if start == -1:
        raise LLMError("模型输出中找不到 JSON 对象")
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    raise LLMError("JSON 对象没有正常闭合")


def _repair_json(text: str) -> str:
    """常见问题修补：中文引号、尾随逗号。"""
    text = text.replace("“", '"').replace("”", '"')
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


def parse_json(text: str) -> dict:
    candidate = _strip_code_fence(text)
    for attempt in (candidate, _extract_json_block(candidate)):
        for payload in (attempt, _repair_json(attempt)):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
            if isinstance(data, list):
                return {"items": data}
    raise LLMError(f"JSON 解析失败，原始输出片段：{candidate[:300]}")


class LLMClient:
    def __init__(self, api_key: str, api_base: str, model: str,
                 timeout: int = 180, max_retries: int = 4,
                 temperature: float = 0.65, max_tokens: int = 8000) -> None:
        if not api_key:
            raise LLMError("未配置 API Key，请检查 .env 里的 MOVIE_API_KEY")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.temperature = temperature
        self.max_tokens = max_tokens

    # ---- 底层 HTTP ----
    def _post(self, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def chat(self, system: str, user: str, *, json_mode: bool = True,
             temperature: float | None = None, max_tokens: int | None = None) -> str:
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                data = self._post(payload)
                choices = data.get("choices") or []
                if not choices:
                    raise LLMError(f"接口未返回 choices：{str(data)[:200]}")
                content = (choices[0].get("message") or {}).get("content") or ""
                if not content.strip():
                    raise LLMError("接口返回空内容")
                return content
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", "ignore")[:300]
                except Exception:  # noqa: BLE001
                    pass
                last_error = exc
                # 余额不足重试没有意义，直接给出可执行的提示
                if exc.code == 402 or "insufficient_balance" in detail:
                    raise LLMError(
                        "账户余额不足，模型接口拒绝请求（HTTP 402）。"
                        "请到服务商后台充值后重试（DeepSeek：platform.deepseek.com → 充值）。"
                        f"原始返回：{detail}"
                    ) from exc
                # 4xx 里只有 429 值得重试
                if exc.code not in (429, 500, 502, 503, 504):
                    raise LLMError(f"HTTP {exc.code}：{detail}") from exc
                log.warning("HTTP %s，第 %s 次重试：%s", exc.code, attempt, detail)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, LLMError) as exc:
                last_error = exc
                log.warning("请求异常，第 %s 次重试：%s", attempt, exc)

            if attempt < self.max_retries:
                wait = min(60, 2 ** attempt) + random.uniform(0, 1.5)
                log.info("等待 %.1f 秒后重试…", wait)
                time.sleep(wait)

        raise LLMError(f"请求失败，已重试 {self.max_retries} 次：{last_error}")

    def chat_json(self, system: str, user: str, **kwargs) -> dict:
        return parse_json(self.chat(system, user, **kwargs))
