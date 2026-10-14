"""Settings for the infrastructure PDF reports.

Values come from the `.env` file next to this package (the ThingsBoard project root);
process environment variables are the fallback. The process environment is never
modified, because this package is imported inside the shared n8n report API process.
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

REPORT_TZ = ZoneInfo("Asia/Kolkata")

# Device profiles (ThingsBoard device "type") that feed each report
DEFAULT_PROFILES = {
    "dg": ["woodward_kg1500"],
    "lt": ["LT Panels Profile", "LT Panel Master Profile"],
    "fire": ["LT Panel Fire Profile"],
    "ro": ["RO System Profile"],
}

DEFAULT_TB_URLS = ["http://172.17.0.1:9091", "http://172.20.0.1:9091", "http://localhost:9091"]
DEFAULT_PDF_URLS = ["http://pdf-generator:3005", "http://172.17.0.1:3005", "http://172.20.0.1:3005", "http://localhost:3005"]

_EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


class ConfigError(RuntimeError):
    """Required configuration is missing or invalid."""


def read_env_file(path=ENV_PATH):
    """Parse KEY=VALUE lines of a .env file (no shell expansion, quotes stripped)."""
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def parse_recipients(value):
    """Comma/semicolon separated addresses -> list; raises ConfigError on an invalid address."""
    recipients = [r.strip() for r in re.split(r"[,;]", value or "") if r.strip()]
    invalid = [r for r in recipients if not _EMAIL_RE.match(r)]
    if invalid:
        raise ConfigError(f"Invalid recipient address(es): {', '.join(invalid)}")
    return recipients


@dataclass(frozen=True)
class Settings:
    tb_urls: list
    tb_tenant_user: str
    tb_tenant_pass: str
    tb_sysadmin_user: str
    tb_sysadmin_pass: str
    tb_tenant_id: str
    pdf_urls: list
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pass: str
    smtp_from: str
    smtp_from_name: str
    recipients: list
    telegram_bot_token: str
    telegram_chat_ids: list
    profiles: dict = field(default_factory=dict)
    http_timeout: float = 60.0
    http_retries: int = 3


def load_settings(env_path=ENV_PATH):
    file_values = read_env_file(env_path)

    def get(key, default=""):
        value = file_values.get(key)
        if value is None or value == "":
            value = os.environ.get(key, default)
        return value.strip() if isinstance(value, str) else value

    def url_list(key, defaults):
        configured = [u.strip().rstrip("/") for u in get(key).split(",") if u.strip()]
        return configured + [u for u in defaults if u not in configured]

    profiles = {
        name: [p.strip() for p in get(f"REPORT_PROFILES_{name.upper()}").split(",") if p.strip()] or default
        for name, default in DEFAULT_PROFILES.items()
    }

    try:
        smtp_port = int(get("SMTP_PORT", "465"))
    except ValueError as exc:
        raise ConfigError("SMTP_PORT must be a number") from exc

    return Settings(
        tb_urls=url_list("TB_BASE_URL", DEFAULT_TB_URLS),
        tb_tenant_user=get("TB_TENANT_USER"),
        tb_tenant_pass=get("TB_TENANT_PASS"),
        # TB_USER / TB_PASS are the names older scripts in this repo use for the sysadmin login
        tb_sysadmin_user=get("TB_SYSADMIN_USER") or get("TB_USER"),
        tb_sysadmin_pass=get("TB_SYSADMIN_PASS") or get("TB_PASS"),
        tb_tenant_id=get("TB_TENANT_ID"),
        pdf_urls=url_list("PDF_SERVICE_URL", DEFAULT_PDF_URLS),
        smtp_host=get("SMTP_HOST") or get("SMTP_SERVER"),
        smtp_port=smtp_port,
        smtp_user=get("SMTP_USER"),
        smtp_pass=get("SMTP_PASS") or get("SMTP_PASSWORD"),
        smtp_from=get("SMTP_FROM") or get("SMTP_USER"),
        smtp_from_name=get("INFRA_REPORT_FROM_NAME", "ThingsBoard Infrastructure Operations"),
        recipients=parse_recipients(get("REPORT_RECIPIENTS")),
        telegram_bot_token=get("TELEGRAM_BOT_TOKEN"),
        telegram_chat_ids=[c.strip() for c in get("TELEGRAM_CHAT_ID").split(",") if c.strip()],
        profiles=profiles,
    )
