from __future__ import annotations

import traceback
from datetime import datetime
from typing import Optional

from src.models import CategorizedEmail, Digest, PipelineState


class SlackFormatter:
    """Builds Slack Block Kit JSON payloads for success digests and failure alerts."""

    def __init__(
        self,
        max_per_category: int = 15,
        include_reply_drafts: bool = True,
    ):
        self._max_per_category = max_per_category
        self._include_reply_drafts = include_reply_drafts

    def format_digest(self, digest: Digest) -> dict:
        """Build the Slack Block Kit payload for a successful digest."""
        blocks: list[dict] = []

        blocks.append(
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Email Digest", "emoji": True},
            }
        )
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"*{digest.total_emails} emails processed* | "
                            f"Generated {digest.generated_at.strftime('%Y-%m-%d %H:%M UTC')}"
                        ),
                    }
                ],
            }
        )
        blocks.append({"type": "divider"})

        if digest.action_immediately:
            blocks.append(
                self._section_header("Action Immediately", len(digest.action_immediately))
            )
            for email in digest.action_immediately[: self._max_per_category]:
                blocks.extend(
                    self._format_email_block(email, show_reply=self._include_reply_drafts)
                )
            blocks.append({"type": "divider"})

        if digest.action_eventually:
            blocks.append(
                self._section_header("Action Eventually", len(digest.action_eventually))
            )
            for email in digest.action_eventually[: self._max_per_category]:
                blocks.extend(self._format_email_block(email, show_reply=False))
            blocks.append({"type": "divider"})

        if digest.summary_only:
            blocks.append(
                self._section_header("Summary Only", len(digest.summary_only))
            )
            summary_text = "\n".join(
                f"- <{e.email.gmail_link}|{self._truncate(e.email.subject, 60)}> "
                f"(P{e.categorization.priority}) - "
                f"{self._truncate(e.categorization.summary, 80)}"
                for e in digest.summary_only[: self._max_per_category]
            )
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": summary_text[:3000]},
                }
            )

        return {"blocks": blocks}

    def format_failure(
        self,
        failed_state: PipelineState,
        error: Exception,
        request_id: Optional[str] = None,
    ) -> dict:
        """Build the Slack Block Kit payload for a pipeline failure alert."""
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        tb = traceback.format_exception(type(error), error, error.__traceback__)
        tb_str = "".join(tb)[-500:]

        blocks: list[dict] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": ":rotating_light: Email Manager - Pipeline Failed",
                    "emoji": True,
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Failed State:*\n`{failed_state.value}`"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Error Type:*\n`{type(error).__name__}`",
                    },
                    {"type": "mrkdwn", "text": f"*Time:*\n{now}"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Request ID:*\n`{request_id or 'N/A'}`",
                    },
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Error Message:*\n```{str(error)[:500]}```",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Traceback (last 500 chars):*\n```{tb_str}```",
                },
            },
        ]

        return {"blocks": blocks}

    def _section_header(self, title: str, count: int) -> dict:
        return {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{title}* ({count} emails)"},
        }

    def _format_email_block(
        self, email: CategorizedEmail, show_reply: bool
    ) -> list[dict]:
        blocks: list[dict] = []
        e = email
        priority_bar = self._priority_indicator(e.categorization.priority)

        text = (
            f"{priority_bar} *<{e.email.gmail_link}|"
            f"{self._truncate(e.email.subject, 80)}>*\n"
            f"From: {e.email.sender} | Priority: {e.categorization.priority}/10\n"
            f"{e.categorization.summary}"
        )
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": text[:3000]}}
        )

        if show_reply and e.categorization.suggested_reply:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": (
                                f"*Suggested reply:* "
                                f"_{self._truncate(e.categorization.suggested_reply, 200)}_"
                            ),
                        }
                    ],
                }
            )

        return blocks

    @staticmethod
    def _priority_indicator(priority: int) -> str:
        if priority >= 8:
            return ":red_circle:"
        elif priority >= 5:
            return ":large_orange_circle:"
        else:
            return ":white_circle:"

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."
