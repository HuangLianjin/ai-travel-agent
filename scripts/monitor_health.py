"""线上健康检查：失败时推送企业微信机器人告警。"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

ENV_FILE = Path(os.getenv("MONITOR_ENV_FILE", "/root/ai-travel-agent/.env"))
HEALTH_URL = os.getenv("HEALTH_CHECK_URL", "http://127.0.0.1:8000/api/health")


def _load_env(name: str) -> str:
    value = os.getenv(name, "")
    if value:
        return value
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def load_webhook() -> str:
    return _load_env("WECHAT_WEBHOOK")


def load_pushplus_token() -> str:
    return _load_env("PUSHPLUS_TOKEN")


def send_message(webhook: str, content: str) -> None:
    if not webhook:
        return
    payload = json.dumps(
        {"msgtype": "text", "text": {"content": content[:1800]}}
    ).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def send_pushplus(token: str, content: str) -> None:
    if not token:
        return
    payload = json.dumps(
        {
            "token": token,
            "title": "星旅 Agent 监控告警",
            "content": content[:1800],
            "template": "txt",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://www.pushplus.plus/send",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def main() -> None:
    webhook = load_webhook()
    pushplus = load_pushplus_token()
    error = ""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=10) as resp:
            if resp.status != 200:
                error = f"HTTP {resp.status}"
    except Exception as exc:
        error = str(exc)
    if not error:
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    message = (
        "\u3010\u661f\u65c5 Agent \u76d1\u63a7\u544a\u8b66\u3011\n"
        f"\u5065\u5eb7\u68c0\u67e5\u5931\u8d25\uff1a{HEALTH_URL}\n"
        f"\u65f6\u95f4\uff1a{now}\n"
        f"\u539f\u56e0\uff1a{error}"
    )
    print(message)
    send_message(webhook, message)
    send_pushplus(pushplus, message)


if __name__ == "__main__":
    main()
