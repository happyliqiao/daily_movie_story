"""体检脚本：检查模型接口和邮件配置是否可用。

换模型、换邮箱授权码之后先跑这个，几秒就能看出问题，不用真跑一整部剧。

用法：
    python scripts/check_api.py                  # 用 .env 里的配置
    python scripts/check_api.py --skip-smtp      # 只查模型接口
    python scripts/check_api.py --api-key sk-xxx --api-base https://open.bigmodel.cn/api/paas/v4 --model glm-4-flash
"""

from __future__ import annotations

import argparse
import json
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def post(base: str, key: str, payload: dict, timeout: int = 60) -> tuple[int, dict | str, float]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base.rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        },
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), time.time() - started
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "ignore")[:500]
        except Exception:  # noqa: BLE001
            pass
        return exc.code, detail, time.time() - started
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}", time.time() - started


def check_api(base: str, key: str, model: str) -> bool:
    print(f"模型接口：{base}")
    print(f"模型名称：{model}")
    print(f"密钥：{key[:6]}…（共 {len(key)} 位）")
    print()

    # ---- 1. 最小可用请求 ----
    print("① 基础连通 …", end=" ", flush=True)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "只回复两个字：正常"}],
        "max_tokens": 20,
        "temperature": 0.1,
        "stream": False,
    }
    code, data, cost = post(base, key, payload)
    if code != 200:
        print("失败")
        print(f"   HTTP {code}：{data}")
        hint = ""
        text = str(data)
        if code == 402 or "insufficient" in text.lower():
            hint = "余额不足，需要充值，或换成免费的智谱 GLM-4-Flash。"
        elif code == 401 or "unauthorized" in text.lower() or "api key" in text.lower():
            hint = "密钥无效，检查是否复制完整、是否属于这个平台。"
        elif code == 404 or "model" in text.lower():
            hint = f"模型名可能不对，确认平台文档里的准确 ID（当前填的是 {model}）。"
        elif code == 429:
            hint = "被限流了，稍等一分钟再试。"
        if hint:
            print(f"   建议：{hint}")
        return False
    try:
        reply = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError):
        print("失败")
        print(f"   返回结构异常：{str(data)[:300]}")
        return False
    print(f"成功（{cost:.1f} 秒，回复：{reply[:20]}）")

    # ---- 2. JSON 模式 ----
    print("② JSON 模式 …", end=" ", flush=True)
    payload["response_format"] = {"type": "json_object"}
    payload["messages"] = [{"role": "user", "content": '输出 {"ok":true} 这个 JSON，不要别的'}]
    payload["max_tokens"] = 50
    code, data, cost = post(base, key, payload)
    if code == 200:
        print("支持（可直接用）")
    else:
        print("不支持 —— 不影响使用，程序会自动关掉它、靠提示词约束 JSON")
        print(f"   HTTP {code}：{str(data)[:200]}")

    # ---- 3. max_tokens 上限 ----
    print("③ 长输出能力 …", end=" ", flush=True)
    for size in (8000, 4096, 2048):
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "用中文写一段 200 字左右的文字，主题随意"}],
            "max_tokens": size,
            "temperature": 0.7,
            "stream": False,
        }
        code, data, cost = post(base, key, payload)
        if code == 200:
            print(f"可用 max_tokens={size}（{cost:.1f} 秒）")
            if size < 8000:
                print(f"   注意：该模型上限低于 8000，建议在 .env 里设 MOVIE_MAX_TOKENS={size}")
            break
        if size == 2048:
            print(f"失败（HTTP {code}）：{str(data)[:200]}")
            return False
    return True


def check_smtp(host: str, port: int, user: str, password: str, use_ssl: bool) -> bool:
    print(f"\n邮件服务：{host}:{port}（{'SSL' if use_ssl else 'STARTTLS'}）")
    print(f"账号：{user}")
    print("① 登录 …", end=" ", flush=True)
    try:
        ctx = ssl.create_default_context()
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=25, context=ctx) as server:
                server.login(user, password)
        else:
            with smtplib.SMTP(host, port, timeout=25) as server:
                server.ehlo()
                if server.has_extn("starttls"):
                    server.starttls(context=ctx)
                    server.ehlo()
                server.login(user, password)
    except smtplib.SMTPAuthenticationError:
        print("失败（535 认证失败）")
        print("   建议：163 邮箱要用『客户端授权码』，不是登录密码。")
        print("         到 mail.163.com → 设置 → POP3/SMTP/IMAP → 重新生成授权码。")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"失败（{type(exc).__name__}: {exc}）")
        return False
    print("成功")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="检查模型接口和邮件配置")
    parser.add_argument("--api-key")
    parser.add_argument("--api-base")
    parser.add_argument("--model")
    parser.add_argument("--skip-api", action="store_true")
    parser.add_argument("--skip-smtp", action="store_true")
    args = parser.parse_args()

    env = load_env()
    base = args.api_base or env.get("MOVIE_API_BASE") or "https://api.deepseek.com"
    key = args.api_key or env.get("MOVIE_API_KEY") or ""
    model = args.model or env.get("MOVIE_MODEL") or "deepseek-chat"

    print("=" * 60)
    print("每日影视故事梗概 · 配置体检")
    print("=" * 60)

    ok = True
    if not args.skip_api:
        if not key:
            print("\n未找到 API Key（.env 里的 MOVIE_API_KEY）")
            ok = False
        else:
            print()
            ok = check_api(base, key, model) and ok

    if not args.skip_smtp:
        host = env.get("MOVIE_SMTP_HOST", "")
        port = int(env.get("MOVIE_SMTP_PORT", "465") or 465)
        user = env.get("MOVIE_SMTP_USER", "")
        pw = env.get("MOVIE_SMTP_PASS", "")
        use_ssl = env.get("MOVIE_SMTP_SSL", "1") == "1"
        if not (host and user and pw):
            print("\n未配置 SMTP（.env 里的 MOVIE_SMTP_*）")
            ok = False
        else:
            ok = check_smtp(host, port, user, pw, use_ssl) and ok

    print()
    print("=" * 60)
    if ok:
        print("结论：配置可用，可以正常生成。")
        print("下一步：python run.py")
    else:
        print("结论：还有问题没解决，按上面的建议处理后再跑一次本脚本。")
    print("=" * 60)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
