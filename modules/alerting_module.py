import logging
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class AlertingModule:
    def __init__(
        self,
        from_addr: str,
        to_addr: str,
        password: str,
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
    ):
        self.from_addr = from_addr
        self.to_addr = to_addr
        self.password = password
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self._enabled = bool(password)
        if not self._enabled:
            logger.warning("AlertingModule: no email password set — alerts disabled")

    def send(self, subject: str, body: str) -> None:
        logger.info("ALERT: %s", subject)
        if not self._enabled:
            return
        try:
            msg = MIMEText(body)
            msg["Subject"] = f"[Involio Bot] {subject}"
            msg["From"] = self.from_addr
            msg["To"] = self.to_addr

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as smtp:
                smtp.starttls()
                smtp.login(self.from_addr, self.password)
                smtp.sendmail(self.from_addr, [self.to_addr], msg.as_string())
        except Exception as exc:
            logger.error("Failed to send alert email: %s", exc)

    # Convenience wrappers used by other modules
    def login_failed(self, detail: str = "") -> None:
        self.send("Login failed", detail or "Check screenshots/after_login.png")

    def order_failed(self, trade_id: str, detail: str = "") -> None:
        self.send(f"Order failed — {trade_id}", detail)

    def interface_changed(self, detail: str = "") -> None:
        self.send("Interface change detected — execution paused", detail)

    def browser_closed(self) -> None:
        self.send("Browser closed — attempting restart", "")

    def session_expired(self) -> None:
        self.send("Session expired — manual intervention required", "")

    def system_paused(self, reason: str = "") -> None:
        self.send("System PAUSED", reason)

    def system_resumed(self) -> None:
        self.send("System RESUMED", "")

    def trade_not_copied(self, trade_id: str, reason: str = "") -> None:
        self.send(f"Trade detected but NOT copied — {trade_id}", reason)
