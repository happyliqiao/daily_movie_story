"""邮件发送：把当天生成的故事梗概发到指定邮箱。

用标准库 smtplib，支持 465 隐式 SSL 和 587 STARTTLS 两种方式。
邮件正文是内联样式的 HTML（邮件客户端兼容性好），同时附上 .md 和 .html 两个文件。
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from pathlib import Path

log = logging.getLogger("moviestory.mailer")


class MailError(RuntimeError):
    pass


def _build_message(*, subject: str, html_body: str, text_body: str,
                   sender: str, recipient: str, attachments: list[Path]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("每日影视故事梗概", sender))
    msg["To"] = recipient
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    for path in attachments:
        if path and path.exists():
            data = path.read_bytes()
            subtype = "html" if path.suffix.lower() == ".html" else "markdown"
            msg.add_attachment(data, maintype="text", subtype=subtype, filename=path.name)
    return msg


def send_email(*, smtp_host: str, smtp_port: int, smtp_user: str, smtp_pass: str,
               recipient: str, subject: str, html_body: str, text_body: str,
               attachments: list[Path] | None = None,
               use_ssl: bool | None = None, timeout: int = 30) -> None:
    """发送一封邮件。失败时抛 MailError。"""
    if not smtp_host or not smtp_user or not smtp_pass:
        raise MailError("SMTP 配置不完整（host/user/pass）")
    recipient = recipient or smtp_user
    if not recipient:
        raise MailError("未配置收件人")

    if use_ssl is None:
        use_ssl = smtp_port == 465

    msg = _build_message(
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        sender=smtp_user,
        recipient=recipient,
        attachments=attachments or [],
    )

    context = ssl.create_default_context()
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout, context=context) as server:
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=timeout) as server:
                server.ehlo()
                if server.has_extn("starttls"):
                    server.starttls(context=context)
                    server.ehlo()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(f"SMTP 认证失败：{exc}（163 邮箱需用『客户端授权码』而非登录密码）") from exc
    except smtplib.SMTPException as exc:
        raise MailError(f"SMTP 发送失败：{exc}") from exc
    except OSError as exc:
        raise MailError(f"网络错误，无法连接 {smtp_host}:{smtp_port} —— {exc}") from exc

    log.info("邮件已发送至 %s（主题：%s）", recipient, subject)
