from __future__ import annotations

import base64
import logging
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Optional

from googleapiclient.discovery import build

from src.gmail.token_manager import TokenManager
from src.models import EmailThread, RawEmail
from src.utils.errors import GmailFetchError

if TYPE_CHECKING:
    from src.config import GmailConfig

logger = logging.getLogger(__name__)

GMAIL_LINK_TEMPLATE = "https://mail.google.com/mail/u/0/#inbox/{message_id}"
GMAIL_THREAD_LINK_TEMPLATE = "https://mail.google.com/mail/u/0/#inbox/{thread_id}"


class GmailClient:
    """Fetches unlabeled emails from Gmail API."""

    def __init__(self, config: GmailConfig):
        self._config = config
        self._token_manager = TokenManager(config)
        self._service = None

    def _get_service(self):
        if self._service is None:
            creds = self._token_manager.get_credentials()
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def fetch_unlabeled_emails(self) -> list[RawEmail]:
        """Fetch emails matching the configured query.

        Default: has:nouserlabels newer_than:2h
        Paginates through results up to max_total_emails.
        """
        service = self._get_service()
        emails: list[RawEmail] = []
        page_token: Optional[str] = None

        try:
            while len(emails) < self._config.max_total_emails:
                result = (
                    service.users()
                    .messages()
                    .list(
                        userId="me",
                        q=self._config.query,
                        maxResults=min(
                            self._config.max_results_per_page,
                            self._config.max_total_emails - len(emails),
                        ),
                        pageToken=page_token,
                    )
                    .execute()
                )

                messages = result.get("messages", [])
                if not messages:
                    break

                for msg_stub in messages:
                    try:
                        full_msg = self._get_message(msg_stub["id"])
                        if full_msg:
                            emails.append(full_msg)
                    except Exception as e:
                        logger.warning(
                            f"Failed to fetch message {msg_stub['id']}: {e}",
                            exc_info=True,
                        )

                page_token = result.get("nextPageToken")
                if not page_token:
                    break

        except Exception as e:
            raise GmailFetchError(f"Failed to list Gmail messages: {e}") from e

        logger.info(f"Fetched {len(emails)} unlabeled emails")
        return emails

    def _get_message(self, message_id: str) -> Optional[RawEmail]:
        service = self._get_service()
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

        headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
        body_plain = self._extract_body(msg["payload"], "text/plain")

        return RawEmail(
            message_id=msg["id"],
            thread_id=msg["threadId"],
            subject=headers.get("subject", "(No Subject)"),
            sender=headers.get("from", "Unknown"),
            sender_email=self._extract_email(headers.get("from", "")),
            recipient=headers.get("to", ""),
            date=self._parse_date(headers.get("date", "")),
            snippet=msg.get("snippet", ""),
            body_plain=body_plain[:5000] if body_plain else None,
            label_ids=msg.get("labelIds", []),
            gmail_link=GMAIL_LINK_TEMPLATE.format(message_id=msg["id"]),
        )

    def _extract_body(self, payload: dict, mime_type: str) -> Optional[str]:
        if payload.get("mimeType") == mime_type and payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode(
                "utf-8", errors="replace"
            )

        for part in payload.get("parts", []):
            result = self._extract_body(part, mime_type)
            if result:
                return result
        return None

    @staticmethod
    def _extract_email(from_header: str) -> str:
        if "<" in from_header and ">" in from_header:
            return from_header.split("<")[1].rstrip(">")
        return from_header

    @staticmethod
    def _parse_date(date_str: str) -> datetime:
        try:
            return parsedate_to_datetime(date_str)
        except (ValueError, TypeError):
            return datetime.now(timezone.utc)

    @staticmethod
    def consolidate_into_threads(emails: list[RawEmail]) -> list[EmailThread]:
        """Group raw emails by thread_id into EmailThread objects.

        Messages within each thread are sorted chronologically.
        Threads are sorted by latest message date (most recent first).
        """
        thread_map: dict[str, list[RawEmail]] = defaultdict(list)
        for email in emails:
            thread_map[email.thread_id].append(email)

        threads: list[EmailThread] = []
        for thread_id, messages in thread_map.items():
            messages.sort(key=lambda m: m.date)
            first_msg = messages[0]
            # Deduplicated, order-preserving participant list
            participants = list(dict.fromkeys(m.sender for m in messages))

            threads.append(
                EmailThread(
                    thread_id=thread_id,
                    subject=first_msg.subject,
                    messages=messages,
                    gmail_link=GMAIL_THREAD_LINK_TEMPLATE.format(thread_id=thread_id),
                    message_count=len(messages),
                    latest_date=messages[-1].date,
                    participants=participants,
                )
            )

        threads.sort(key=lambda t: t.latest_date, reverse=True)
        return threads
