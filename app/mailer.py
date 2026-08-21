"""验证码邮件发送：未配置 SMTP 时验证码输出到服务端日志。"""

from __future__ import annotations

import logging
import smtplib
from email.header import Header
from email.mime.text import MIMEText

from app.config import get_settings

logger = logging.getLogger("ai-travel-agent.mailer")


def send_code_email(to_email: str, code: str, purpose: str = "verify") -> bool:
    settings = get_settings()
    if not settings.mail_enabled:
        logger.info(
            "[mailer] 邮件发送未启用，%s 验证码 %s 已打印到日志（发往 %s）",
            purpose,
            code,
            to_email,
        )
        return False
    body = f"您的验证码是 {code}，30 分钟内有效。"
    subject = "星旅 Agent 邮箱验证" if purpose == "verify" else "星旅 Agent 密码重置"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to_email
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.sendmail(msg["From"], [to_email], msg.as_string())
        return True
    except Exception as exc:
        logger.warning("[mailer] 邮件发送失败: %s", exc)
        logger.info("[mailer] 验证码 %s 已打印到日志（发送失败回退）", code)
        return False
