"""短信验证码发送：未配置短信服务商时验证码输出到服务端日志。"""

from __future__ import annotations

import logging

from app.config import get_settings

logger = logging.getLogger("ai-travel-agent.sms")


def send_sms_code(phone: str, code: str, purpose: str = "register") -> bool:
    settings = get_settings()
    if settings.sms_provider in ("", "log"):
        logger.info(
            "[sms] 未配置短信服务商，%s 验证码 %s 已打印到日志（发送至 %s）",
            purpose,
            code,
            phone,
        )
        return False
    # 预留阿里云/腾讯云短信接入点：填入 SMS_ACCESS_KEY / SMS_SECRET_KEY / 模板后实现
    logger.info("[sms] provider=%s phone=%s purpose=%s code=%s", settings.sms_provider, phone, purpose, code)
    return False
