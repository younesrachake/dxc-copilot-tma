"""
Email service using aiosmtplib for async SMTP.
Gracefully degrades when SMTP is not configured.
"""
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self):
        from app.core.config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
        self._host = SMTP_HOST
        self._port = SMTP_PORT
        self._user = SMTP_USER
        self._password = SMTP_PASSWORD
        self._from = SMTP_FROM
        self._enabled = bool(SMTP_HOST and SMTP_USER)

    async def send_email(self, to: str, subject: str, body_html: str) -> bool:
        """Send an HTML email. Returns True on success, False if SMTP not configured."""
        if not self._enabled:
            logger.warning("SMTP not configured — skipping email to %s (subject: %s)", to, subject)
            return False

        try:
            import aiosmtplib
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = self._from
            message["To"] = to
            message.attach(MIMEText(body_html, "html", "utf-8"))

            await aiosmtplib.send(
                message,
                hostname=self._host,
                port=self._port,
                username=self._user,
                password=self._password,
                use_tls=False,
                start_tls=True,
            )
            logger.info("Email sent to %s: %s", to, subject)
            return True
        except Exception as exc:
            logger.error("Failed to send email to %s: %s", to, exc)
            return False

    async def send_password_reset(self, to: str, token: str) -> bool:
        """Send password reset email with reset link."""
        from app.core.config import SSO_REDIRECT_URI
        # Build reset URL from the app's base URL
        base_url = SSO_REDIRECT_URI.rsplit("/api", 1)[0] if "/api" in SSO_REDIRECT_URI else "http://localhost"
        reset_url = f"{base_url}/reset-password?token={token}"

        subject = "Réinitialisation de votre mot de passe DXC Copilot"
        body_html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #0065A1;">DXC Copilot — Réinitialisation du mot de passe</h2>
            <p>Vous avez demandé la réinitialisation de votre mot de passe.</p>
            <p>Cliquez sur le lien ci-dessous pour définir un nouveau mot de passe :</p>
            <p style="margin: 24px 0;">
                <a href="{reset_url}"
                   style="background-color: #0065A1; color: white; padding: 12px 24px;
                          text-decoration: none; border-radius: 4px; display: inline-block;">
                    Réinitialiser mon mot de passe
                </a>
            </p>
            <p style="color: #666; font-size: 12px;">
                Ce lien expire dans 1 heure. Si vous n'avez pas demandé cette réinitialisation, ignorez cet email.
            </p>
        </div>
        """
        return await self.send_email(to, subject, body_html)


email_service = EmailService()
