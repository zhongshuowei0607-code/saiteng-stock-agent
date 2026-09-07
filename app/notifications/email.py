from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

LOGGER = logging.getLogger("notification")


def send_email(subject: str, body: str, attachment: Path | None = None) -> bool:
    if os.getenv("EMAIL_ENABLED", "false").lower() != "true":
        return False
    host, user, password = os.getenv("SMTP_HOST", ""), os.getenv("SMTP_USER", ""), os.getenv("SMTP_PASSWORD", "")
    sender, recipient = os.getenv("SMTP_FROM", user), os.getenv("SMTP_TO", "")
    if not all((host, user, password, sender, recipient)):
        LOGGER.warning("Email 已启用但 SMTP 配置不完整")
        return False
    message = EmailMessage()
    message["Subject"], message["From"], message["To"] = subject, sender, recipient
    message.set_content(body)
    if attachment and attachment.is_file():
        message.add_attachment(attachment.read_bytes(), maintype="text", subtype="html", filename=attachment.name)
    try:
        port = int(os.getenv("SMTP_PORT", "465"))
        if os.getenv("SMTP_USE_SSL", "true").lower() == "true":
            client = smtplib.SMTP_SSL(host, port, timeout=10, context=ssl.create_default_context())
        else:
            client = smtplib.SMTP(host, port, timeout=10)
            client.starttls(context=ssl.create_default_context())
        with client:
            client.login(user, password)
            client.send_message(message)
        LOGGER.info("Email 发送成功 recipient=%s", recipient)
        return True
    except Exception as exc:
        LOGGER.warning("Email 发送失败：%s", type(exc).__name__)
        return False
