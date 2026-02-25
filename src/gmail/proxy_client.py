"""Client for the Gmail Proxy API (label and archive operations).

The proxy runs on API Gateway + Lambda and provides write access to Gmail
threads (apply/remove labels, archive/unarchive) while the main pipeline
only needs gmail.readonly OAuth scope.

API endpoint: POST /email
Required body: { "secret": str, "id": str, "action": str, "label"?: str }
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import requests

from src.models import CategorizedThread, EmailCategory
from src.utils.errors import GmailActionError

if TYPE_CHECKING:
    from src.config import GmailProxyConfig

logger = logging.getLogger(__name__)

# Maps our categories to Gmail label names
CATEGORY_LABELS = {
    EmailCategory.ACTION_IMMEDIATELY: "Action Immediately",
    EmailCategory.ACTION_EVENTUALLY: "Action Eventually",
    EmailCategory.SUMMARY_ONLY: "Summary",
}


class GmailProxyClient:
    """Applies labels and archives threads via the Gmail proxy API."""

    def __init__(self, config: GmailProxyConfig):
        self._url = config.api_url.rstrip("/")
        self._secret = config.secret
        self._archive_summary = config.archive_summary
        self._timeout = config.timeout

    # ── Public API ───────────────────────────────────────────────────

    def apply_labels_and_archive(
        self, threads: list[CategorizedThread]
    ) -> dict[str, int]:
        """Label and optionally archive categorized threads.

        - All threads get a label matching their category.
        - Summary Only threads are archived (moved out of inbox).
        - Action Eventually / Action Immediately stay in inbox.

        Returns a summary dict: {"labeled": n, "archived": n, "errors": n}
        """
        stats = {"labeled": 0, "archived": 0, "errors": 0}

        for ct in threads:
            thread_id = ct.thread.thread_id
            category = ct.categorization.category
            label = CATEGORY_LABELS.get(category)

            if not label:
                logger.warning(f"No label mapping for category {category}")
                continue

            # Step 1: Apply category label
            try:
                self._apply_label(thread_id, label)
                stats["labeled"] += 1
            except GmailActionError as e:
                logger.error(f"Failed to label thread {thread_id}: {e}")
                stats["errors"] += 1
                continue  # Skip archive if label failed

            # Step 2: Archive Summary Only threads
            if category == EmailCategory.SUMMARY_ONLY and self._archive_summary:
                try:
                    self._archive(thread_id)
                    stats["archived"] += 1
                except GmailActionError as e:
                    logger.error(f"Failed to archive thread {thread_id}: {e}")
                    stats["errors"] += 1

        logger.info(
            f"Gmail actions complete: {stats['labeled']} labeled, "
            f"{stats['archived']} archived, {stats['errors']} errors"
        )
        return stats

    # ── Private helpers ──────────────────────────────────────────────

    def _apply_label(self, thread_id: str, label: str) -> None:
        """Apply a label to a thread."""
        self._call_proxy("apply_label", thread_id, label=label)

    def _remove_label(self, thread_id: str, label: str) -> None:
        """Remove a label from a thread."""
        self._call_proxy("remove_label", thread_id, label=label)

    def _archive(self, thread_id: str) -> None:
        """Archive a thread (remove from inbox)."""
        self._call_proxy("archive", thread_id)

    def _unarchive(self, thread_id: str) -> None:
        """Unarchive a thread (return to inbox)."""
        self._call_proxy("unarchive", thread_id)

    def _call_proxy(
        self, action: str, thread_id: str, label: str | None = None
    ) -> dict:
        """Make a POST request to the Gmail proxy API."""
        payload: dict = {
            "secret": self._secret,
            "id": thread_id,
            "action": action,
        }
        if label is not None:
            payload["label"] = label

        try:
            response = requests.post(
                self._url,
                json=payload,
                timeout=self._timeout,
            )
        except requests.RequestException as e:
            raise GmailActionError(
                f"Gmail proxy request failed for {action} on thread {thread_id}: {e}"
            ) from e

        if response.status_code == 401:
            raise GmailActionError(
                f"Gmail proxy auth failed (401). Check GMAIL_PROXY_SECRET."
            )
        if response.status_code == 400:
            raise GmailActionError(
                f"Gmail proxy bad request (400) for {action} on {thread_id}: "
                f"{response.text}"
            )
        if response.status_code >= 400:
            raise GmailActionError(
                f"Gmail proxy error ({response.status_code}) for {action} on "
                f"{thread_id}: {response.text}"
            )

        try:
            return response.json()
        except ValueError:
            return {"status": "ok"}
