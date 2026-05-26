"""Email service — sends verification OTP codes via SMTP.

Uses smtplib with SSL (port 465) for secure email delivery.
Generates 6-digit OTP codes stored in Redis with a 10-minute TTL.
"""

from __future__ import annotations

import random
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

from app.core.config import get_settings

logger = structlog.get_logger(__name__)

OTP_LENGTH = 6
OTP_TTL_SECONDS = 600  # 10 minutes


def generate_otp() -> str:
    """Generate a random 6-digit OTP code."""
    return "".join(str(random.randint(0, 9)) for _ in range(OTP_LENGTH))


def _build_verification_email(to_email: str, otp: str, username: str) -> MIMEMultipart:
    """Build the HTML verification email message with professional branding."""
    settings = get_settings()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🏝️ Xác thực tài khoản - Ham Ninh AI Guide"
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_USER}>"
    msg["To"] = to_email

    text_body = (
        f"Xin chào {username},\n\n"
        f"Chào mừng bạn đến với Ham Ninh AI Guide - Trợ lý du lịch thông minh cho làng chài Hàm Ninh, Phú Quốc!\n\n"
        f"Mã xác thực email của bạn là: {otp}\n\n"
        f"Mã này có hiệu lực trong 10 phút.\n"
        f"Nếu bạn không yêu cầu xác thực, vui lòng bỏ qua email này.\n\n"
        f"🌟 Khám phá vẻ đẹp làng chài Hàm Ninh với trợ lý AI thông minh!\n\n"
        f"— Đội ngũ Ham Ninh AI Guide\n"
        f"Liên hệ: hbnclubuit@gmail.com"
    )

    html_body = f"""
    <!DOCTYPE html>
    <html lang="vi">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin: 0; padding: 0; background-color: #f5f5f5;">
        <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 520px; margin: 0 auto; padding: 0;">
            <!-- Header -->
            <div style="background: linear-gradient(135deg, #0ea5e9 0%, #0369a1 100%); padding: 32px 24px; text-align: center;">
                <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 600;">
                    🏝️ Ham Ninh AI Guide
                </h1>
                <p style="color: #e0f2fe; margin: 8px 0 0 0; font-size: 14px;">
                    Trợ lý du lịch thông minh cho làng chài Hàm Ninh
                </p>
            </div>
            
            <!-- Main Content -->
            <div style="background: #ffffff; padding: 32px 24px;">
                <p style="color: #1a1a1a; font-size: 16px; margin: 0 0 8px 0;">
                    Xin chào <strong style="color: #0369a1;">{username}</strong>,
                </p>
                <p style="color: #4a4a4a; font-size: 15px; margin: 16px 0 24px 0; line-height: 1.6;">
                    Chào mừng bạn đến với <strong>Ham Ninh AI Guide</strong>! Để hoàn tất đăng ký tài khoản, 
                    vui lòng sử dụng mã xác thực bên dưới:
                </p>
                
                <!-- OTP Code Box -->
                <div style="background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%); 
                            border: 2px solid #0ea5e9; 
                            border-radius: 12px; 
                            padding: 24px; 
                            text-align: center; 
                            margin: 24px 0;">
                    <p style="color: #64748b; font-size: 13px; margin: 0 0 8px 0; text-transform: uppercase; letter-spacing: 1px;">
                        Mã xác thực của bạn
                    </p>
                    <span style="font-size: 36px; font-weight: 700; letter-spacing: 10px; color: #0369a1; font-family: 'Courier New', monospace;">
                        {otp}
                    </span>
                </div>
                
                <!-- Info Box -->
                <div style="background: #fefce8; border-left: 4px solid #eab308; padding: 16px; margin: 24px 0; border-radius: 0 8px 8px 0;">
                    <p style="color: #713f12; font-size: 14px; margin: 0;">
                        ⏰ <strong>Mã có hiệu lực trong 10 phút.</strong> Sau thời gian này, bạn cần yêu cầu mã mới.
                    </p>
                </div>
                
                <p style="color: #6b7280; font-size: 14px; margin: 16px 0; line-height: 1.6;">
                    Nếu bạn không thực hiện yêu cầu này, vui lòng bỏ qua email này. 
                    Tài khoản của bạn vẫn được bảo vệ an toàn.
                </p>
            </div>
            
            <!-- Feature Highlights -->
            <div style="background: #f8fafc; padding: 24px; border-top: 1px solid #e2e8f0;">
                <p style="color: #0369a1; font-size: 14px; font-weight: 600; margin: 0 0 16px 0; text-align: center;">
                    🌟 Khám phá làng chài Hàm Ninh cùng chúng tôi
                </p>
                <div style="display: flex; flex-wrap: wrap; gap: 12px; justify-content: center;">
                    <span style="background: #ffffff; border: 1px solid #e2e8f0; padding: 8px 16px; border-radius: 20px; font-size: 13px; color: #475569;">
                        🦀 Hải sản tươi sống
                    </span>
                    <span style="background: #ffffff; border: 1px solid #e2e8f0; padding: 8px 16px; border-radius: 20px; font-size: 13px; color: #475569;">
                        🏛️ Di sản văn hóa
                    </span>
                    <span style="background: #ffffff; border: 1px solid #e2e8f0; padding: 8px 16px; border-radius: 20px; font-size: 13px; color: #475569;">
                        🌊 Làng chài truyền thống
                    </span>
                </div>
            </div>
            
            <!-- Footer -->
            <div style="background: #1e293b; padding: 24px; text-align: center;">
                <p style="color: #94a3b8; font-size: 13px; margin: 0 0 8px 0;">
                    <strong style="color: #e2e8f0;">Ham Ninh AI Guide</strong> — Dự án du lịch bền vững
                </p>
                <p style="color: #64748b; font-size: 12px; margin: 0 0 16px 0;">
                    Hỗ trợ du khách khám phá văn hóa làng chài Hàm Ninh một cách có trách nhiệm
                </p>
                <p style="color: #64748b; font-size: 12px; margin: 0;">
                    📧 <a href="mailto:hbnclubuit@gmail.com" style="color: #38bdf8; text-decoration: none;">hbnclubuit@gmail.com</a>
                    &nbsp;|&nbsp;
                    🏫 UIT - ĐH QG TP.HCM
                </p>
            </div>
        </div>
    </body>
    </html>
    """

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def send_verification_email(to_email: str, otp: str, username: str) -> bool:
    """Send a verification OTP email via SMTP SSL.

    Args:
        to_email: Recipient email address.
        otp: The 6-digit OTP code.
        username: User's display name for the email greeting.

    Returns:
        True if sent successfully, False otherwise.
    """
    settings = get_settings()

    if not settings.SMTP_HOST or not settings.SMTP_USER:
        logger.error("email.smtp_not_configured")
        return False

    msg = _build_verification_email(to_email, otp, username)

    try:
        context = ssl.create_default_context()

        if settings.SMTP_USE_SSL:
            # Port 465 — SMTP over SSL
            with smtplib.SMTP_SSL(
                settings.SMTP_HOST,
                settings.SMTP_PORT,
                context=context,
                timeout=10,
            ) as server:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.SMTP_USER, to_email, msg.as_string())
        else:
            # Port 587 — STARTTLS
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                server.starttls(context=context)
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.SMTP_USER, to_email, msg.as_string())

        logger.info("email.sent", to=to_email, subject="verification_otp")
        return True

    except Exception as exc:
        logger.error("email.send_failed", to=to_email, error=str(exc))
        return False


class OTPStore:
    """In-memory OTP store with expiry tracking.

    For production, replace with Redis-backed store.
    Uses a simple dict with timestamp for TTL enforcement.
    """

    def __init__(self) -> None:
        import time
        self._store: dict[str, tuple[str, float]] = {}
        self._time = time

    def save(self, email: str, otp: str) -> None:
        """Store an OTP for an email with TTL."""
        self._store[email.lower()] = (otp, self._time.time() + OTP_TTL_SECONDS)

    def verify(self, email: str, otp: str) -> bool:
        """Verify an OTP. Returns True and removes it if valid."""
        key = email.lower()
        entry = self._store.get(key)
        if entry is None:
            return False

        stored_otp, expires_at = entry
        if self._time.time() > expires_at:
            del self._store[key]
            return False

        if stored_otp != otp:
            return False

        del self._store[key]
        return True

    def remove(self, email: str) -> None:
        """Remove an OTP entry."""
        self._store.pop(email.lower(), None)


# Global OTP store instance
otp_store = OTPStore()
