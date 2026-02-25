from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from src.utils.errors import ConfigError


@dataclass
class GmailConfig:
    client_id: str
    client_secret: str
    refresh_token: str
    user_email: str = ""
    scopes: list[str] = field(
        default_factory=lambda: ["https://www.googleapis.com/auth/gmail.readonly"]
    )
    query: str = "has:nouserlabels newer_than:2h"
    max_results_per_page: int = 100
    max_total_emails: int = 500


@dataclass
class AIConfig:
    api_key: Optional[str] = None
    oauth_token: Optional[str] = None
    model: str = "claude-sonnet-4-5-20250929"
    max_tokens: int = 4096
    temperature: float = 0.2
    batch_size: int = 10
    max_concurrent_requests: int = 5

    def __post_init__(self) -> None:
        if not self.api_key and not self.oauth_token:
            raise ConfigError(
                "Either ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN must be set. "
                "Run 'claude setup-token' to generate an OAuth token, or get an API key "
                "from console.anthropic.com."
            )


@dataclass
class SlackConfig:
    bot_token: str = ""
    user_id: str = ""
    signing_secret: str = ""
    enabled: bool = True
    max_message_length: int = 3000
    include_reply_drafts: bool = True
    max_emails_per_category: int = 15

    def validate(self) -> None:
        """Validate that required fields are set when Slack is enabled."""
        if self.enabled and (not self.bot_token or not self.user_id):
            raise ConfigError(
                "SLACK_BOT_TOKEN and SLACK_USER_ID are required when Slack is enabled. "
                "Set them in .env or disable Slack in config.yaml (slack.enabled: false)."
            )


@dataclass
class ReportConfig:
    format: str = "markdown"
    output_path: str = "/tmp/email_digest.md"
    s3_bucket: str = ""
    s3_prefix: str = "digests/"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "json"


@dataclass
class AppConfig:
    gmail: GmailConfig
    ai: AIConfig
    slack: SlackConfig
    report: ReportConfig
    logging: LoggingConfig


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Load configuration from config.yaml overlaid with environment variables.

    Secrets come from env vars (resolved from SSM at deploy time).
    Non-secret settings come from config.yaml.
    """
    if config_path is None:
        config_path = os.environ.get(
            "CONFIG_PATH",
            str(Path(__file__).parent.parent / "config.yaml"),
        )

    try:
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raw = {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Failed to parse config.yaml: {e}") from e

    gmail_cfg = raw.get("gmail", {})
    ai_cfg = raw.get("ai", {})
    slack_cfg = raw.get("slack", {})
    report_cfg = raw.get("report", {})
    logging_cfg = raw.get("logging", {})

    try:
        return AppConfig(
            gmail=GmailConfig(
                client_id=os.environ["GMAIL_CLIENT_ID"],
                client_secret=os.environ["GMAIL_CLIENT_SECRET"],
                refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
                user_email=os.environ.get("USER_EMAIL", ""),
                scopes=gmail_cfg.get("scopes", ["https://www.googleapis.com/auth/gmail.readonly"]),
                query=gmail_cfg.get("query", "has:nouserlabels newer_than:2h"),
                max_results_per_page=gmail_cfg.get("max_results_per_page", 100),
                max_total_emails=gmail_cfg.get("max_total_emails", 500),
            ),
            ai=AIConfig(
                api_key=os.environ.get("ANTHROPIC_API_KEY"),
                oauth_token=os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
                model=os.environ.get("AI_MODEL", ai_cfg.get("model", "claude-sonnet-4-5-20250929")),
                max_tokens=ai_cfg.get("max_tokens", 4096),
                temperature=ai_cfg.get("temperature", 0.2),
                batch_size=ai_cfg.get("batch_size", 10),
                max_concurrent_requests=ai_cfg.get("max_concurrent_requests", 5),
            ),
            slack=SlackConfig(
                bot_token=os.environ.get("SLACK_BOT_TOKEN", ""),
                user_id=os.environ.get("SLACK_USER_ID", ""),
                signing_secret=os.environ.get("SLACK_SIGNING_SECRET", ""),
                enabled=slack_cfg.get("enabled", True),
                max_message_length=slack_cfg.get("max_message_length", 3000),
                include_reply_drafts=slack_cfg.get("include_reply_drafts", True),
                max_emails_per_category=slack_cfg.get("max_emails_per_category", 15),
            ),
            report=ReportConfig(
                format=report_cfg.get("format", "markdown"),
                output_path=report_cfg.get("output_path", "/tmp/email_digest.md"),
                s3_bucket=report_cfg.get("s3_bucket", ""),
                s3_prefix=report_cfg.get("s3_prefix", "digests/"),
            ),
            logging=LoggingConfig(
                level=logging_cfg.get("level", "INFO"),
                format=logging_cfg.get("format", "json"),
            ),
        )
    except KeyError as e:
        raise ConfigError(
            f"Missing required environment variable: {e}. "
            "See .env.example for required variables."
        ) from e
