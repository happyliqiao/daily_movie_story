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
    """常见问题修补：中文引号、结构位置的中文标点、尾随逗号。

    弱模型（免费的 GLM-4-Flash 尤其明显）经常把 JSON 的结构性标点写成中文：
        "title":"蝶衣受挫”，“summary":"..."
    只换引号不够，中间的「，」还是中文逗号，JSON 依然不认。
    但正文内容里的中文标点是正常的，不能全局替换，所以只修「紧邻引号/括号」的位置。
    """
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")
    # 结构位置的中文标点：引号或方括号之间的逗号、key 后面的冒号
    text = re.sub(r'(["\]])\s*，\s*(?=["\[])', r"\1,", text)
    text = re.sub(r'([\d}\]])\s*，\s*(?=["\[\{])', r"\1,", text)
    text = re.sub(r'"\s*：\s*', '":', text)
    # 尾随逗号
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


def _close_brackets(chunk: str) -> str:
    """把一段被截断的 JSON 补齐到语法完整。"""
    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in chunk:
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
        elif ch in "{[":
            stack.append(ch)
        elif ch == "}":
            if stack and stack[-1] == "{":
                stack.pop()
        elif ch == "]":
            if stack and stack[-1] == "[":
                stack.pop()
    if in_string:
        chunk += '"'
    return chunk + "".join("}" if c == "{" else "]" for c in reversed(stack))


def _repair_truncated(text: str, limit: int = 24) -> str | None:
    """模型输出被截断（常见于长 JSON、或触到审查边界）时，保住已完整的部分。

    从末尾往前找若干个 `}` / `]` 作为截断点，逐个尝试补齐括号后解析。
    """
    cuts = [m.start() + 1 for m in re.finditer(r"[}\]]", text)][-limit:]
    for cut in reversed(cuts):
        try:
            data = json.loads(_close_brackets(text[:cut]))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data:
            return data
    return None


def parse_json(text: str) -> dict:
    candidate = _strip_code_fence(text)
    # 注意：_extract_json_block 必须放在 try 里。
    # 之前写成 for attempt in (candidate, _extract_json_block(candidate))，
    # 参数会在循环开始前求值，它抛的异常直接让整个解析失败——
    # 哪怕原文只需修补中文引号就能解析。弱模型特别容易触发这个坑。
    attempts = [candidate]
    try:
        block = _extract_json_block(candidate)
        if block != candidate:
            attempts.append(block)
    except LLMError:
        pass
    for attempt in attempts:
        for payload in (attempt, _repair_json(attempt)):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
            if isinstance(data, list):
                return {"items": data}
    # 兜底：输出被截断时尽量保住已完整的部分
    truncated = _repair_truncated(candidate)
    if truncated is not None:
        return truncated
    raise LLMError(f"JSON 解析失败，原始输出片段：{candidate[:300]}")


class LLMClient:
    def __init__(self, api_key: str, api_base: str, model: str,
                 timeout: int = 180, max_retries: int = 4,
                 temperature: float = 0.65, max_tokens: int = 8000) -> None:
        if not api_key:
            raise LLMError("未配置 API Key，请检查 .env 里的 MOVIE_API_KEY")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        # 支持逗号分隔的模型列表，例如 glm-4-air,glm-4-flash
        # 前一个额度用尽/不可用时自动降级到下一个，云端无人值守也不会停摆。
        self.models = [m.strip() for m in str(model).split(",") if m.strip()]
        if not self.models:
            raise LLMError("未配置模型名，请检查 .env 里的 MOVIE_MODEL")
        self._model_idx = 0
        self.timeout = timeout
        self.max_retries = max_retries
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    def model(self) -> str:
        return self.models[self._model_idx]

    def _fallback_model(self) -> bool:
        """切换到下一个备用模型。已到最后一个则返回 False。"""
        if self._model_idx + 1 >= len(self.models):
            return False
        self._model_idx += 1
        log.warning("模型降级：切换到备用模型 %s", self.model)
        return True

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
        # 免费/第三方接口常常不支持 response_format，或对 max_tokens 卡得更死。
        # 这里维护可变状态，遇到兼容性报错就降级重试，而不是直接失败。
        cur_json = json_mode
        cur_max = max_tokens or self.max_tokens
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": cur_max,
            "stream": False,
        }
        if cur_json:
            payload["response_format"] = {"type": "json_object"}

        last_error: Exception | None = None
        attempt = 1
        downgrades = 0  # 兼容性降级次数，避免降级本身造成死循环
        while attempt <= self.max_retries:
            payload["model"] = self.model  # 可能已降级到备用模型
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
                low = detail.lower()

                # 余额不足重试没有意义：有备用模型就切，没有就给出可执行的提示
                if exc.code == 402 or "insufficient_balance" in low:
                    if self._fallback_model():
                        attempt = 1  # 换模型后重新计重试次数
                        continue
                    raise LLMError(
                        "账户余额不足，模型接口拒绝请求（HTTP 402）。"
                        "请到服务商后台充值，或改用免费的智谱 GLM-4-Flash（见 README『免费模型』）。"
                        f"原始返回：{detail}"
                    ) from exc

                # 额度用尽 / 模型不可用，同样尝试降级
                if ("1305" in detail or "访问量过大" in detail or "额度" in detail
                        or "余额" in detail or "not available" in low or "no available" in low):
                    if self._fallback_model():
                        attempt = 1
                        continue

                # 兼容性降级 1：接口不认 response_format，关掉它靠提示词约束
                if cur_json and downgrades < 2 and (
                        "response_format" in low or "json_object" in low
                        or "json mode" in low or "不支持" in detail and "格式" in detail):
                    cur_json = False
                    payload.pop("response_format", None)
                    downgrades += 1
                    log.warning("接口不支持 response_format，改为纯提示词约束 JSON（不消耗重试次数）")
                    continue

                # 兼容性降级 2：max_tokens 超出该模型上限，逐级调小
                if downgrades < 3 and ("max_tokens" in low or "max tokens" in low
                                       or "too large" in low or "超出" in detail):
                    new_max = 4096 if cur_max > 4096 else max(1024, cur_max // 2)
                    if new_max < cur_max:
                        cur_max = new_max
                        payload["max_tokens"] = cur_max
                        downgrades += 1
                        log.warning("max_tokens 超出模型上限，自动降到 %s 重试", cur_max)
                        continue

                # 4xx 里只有 429 值得重试
                if exc.code not in (429, 500, 502, 503, 504):
                    raise LLMError(f"HTTP {exc.code}：{detail}") from exc
                # 429 一直不缓解，说明这个模型当前就是过载，换备用的
                if exc.code == 429 and attempt >= self.max_retries and self._fallback_model():
                    attempt = 1
                    continue
                log.warning("HTTP %s，第 %s 次重试：%s", exc.code, attempt, detail)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, LLMError) as exc:
                last_error = exc
                log.warning("请求异常，第 %s 次重试：%s", attempt, exc)

            attempt += 1
            if attempt <= self.max_retries:
                wait = min(60, 2 ** attempt) + random.uniform(0, 1.5)
                log.info("等待 %.1f 秒后重试…", wait)
                time.sleep(wait)

        raise LLMError(f"请求失败，已重试 {self.max_retries} 次：{last_error}")

    def chat_json(self, system: str, user: str, **kwargs) -> dict:
        """请求并解析 JSON。解析失败时重新生成，而不是直接把错误抛给上层。

        弱模型（免费的 GLM 系列尤其明显）经常把 JSON 写坏或写一半，
        这类问题重生成一次大多能好，比整批失败再降级划算得多。
        """
        last_error: Exception | None = None
        for round_no in range(1, 4):
            content = self.chat(system, user, **kwargs)
            try:
                return parse_json(content)
            except LLMError as exc:
                last_error = exc
                if round_no < 3:
                    log.warning("JSON 解析失败（第 %s 次），重新生成：%s", round_no, str(exc)[:120])
                    time.sleep(1.5 * round_no)
        raise LLMError(f"连续 3 次都没拿到合法 JSON：{last_error}")
