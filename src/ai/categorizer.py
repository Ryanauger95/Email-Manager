from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional

import anthropic

from src.ai.prompts import (
    BATCH_CATEGORIZATION_PROMPT,
    DRAFT_REPLIES_PROMPT,
    DRAFT_SYSTEM_PROMPT,
    EMAIL_XML_TEMPLATE,
    SYSTEM_PROMPT,
    THREAD_MESSAGE_XML_TEMPLATE,
    THREAD_XML_TEMPLATE,
)
from src.models import (
    Categorization,
    CategorizedThread,
    EmailCategory,
    EmailThread,
)
from src.utils.errors import AnthropicAPIError

if TYPE_CHECKING:
    from src.config import AIConfig

logger = logging.getLogger(__name__)

CATEGORIZATION_TOOL = {
    "name": "submit_categorizations",
    "description": "Submit the categorization results for a batch of email threads.",
    "input_schema": {
        "type": "object",
        "properties": {
            "categorizations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "email_id": {"type": "string"},
                        "category": {
                            "type": "string",
                            "enum": ["Summary Only", "Action Eventually", "Action Immediately"],
                        },
                        "priority": {"type": "integer", "minimum": 1, "maximum": 10},
                        "summary": {"type": "string"},
                        "reasoning": {"type": "string"},
                    },
                    "required": [
                        "email_id",
                        "category",
                        "priority",
                        "summary",
                        "reasoning",
                    ],
                },
            }
        },
        "required": ["categorizations"],
    },
}

DRAFT_TOOL = {
    "name": "submit_drafts",
    "description": "Submit reply draft decisions for a batch of email threads.",
    "input_schema": {
        "type": "object",
        "properties": {
            "drafts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "thread_id": {"type": "string"},
                        "awaiting_reply": {"type": "boolean"},
                        "suggested_reply": {"type": ["string", "null"]},
                    },
                    "required": ["thread_id", "awaiting_reply"],
                },
            }
        },
        "required": ["drafts"],
    },
}


class EmailCategorizer:
    """Uses Anthropic Claude to categorize email threads and draft replies."""

    def __init__(self, config: AIConfig):
        self._config = config
        if config.oauth_token:
            self._client = anthropic.Anthropic(auth_token=config.oauth_token)
        else:
            self._client = anthropic.Anthropic(api_key=config.api_key)

    # ── Categorization ──────────────────────────────────────────────────

    def categorize_batch(self, threads: list[EmailThread]) -> list[CategorizedThread]:
        """Categorize a batch of threads in a single API call using tool use."""
        if not threads:
            return []

        emails_xml = "\n\n".join(
            self._build_thread_xml(thread) for thread in threads
        )

        prompt = BATCH_CATEGORIZATION_PROMPT.format(
            count=len(threads),
            emails_xml=emails_xml,
        )

        try:
            response = self._client.messages.create(
                model=self._config.model,
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                tools=[CATEGORIZATION_TOOL],
                tool_choice={"type": "tool", "name": "submit_categorizations"},
            )
        except anthropic.RateLimitError as e:
            raise AnthropicAPIError(f"Anthropic rate limit exceeded: {e}") from e
        except anthropic.APIError as e:
            raise AnthropicAPIError(f"Anthropic API error: {e}") from e

        return self._parse_categorization_response(response, threads)

    def _parse_categorization_response(
        self, response: anthropic.types.Message, threads: list[EmailThread]
    ) -> list[CategorizedThread]:
        thread_map = {t.thread_id: t for t in threads}
        results: list[CategorizedThread] = []

        for block in response.content:
            if block.type != "tool_use":
                continue

            categorizations = block.input.get("categorizations", [])
            for item in categorizations:
                thread = thread_map.get(item.get("email_id", ""))
                if not thread:
                    logger.warning(f"AI returned unknown id: {item.get('email_id')}")
                    continue

                try:
                    category = EmailCategory(item["category"])
                except ValueError:
                    logger.warning(
                        f"Invalid category '{item.get('category')}' for {item['email_id']}, "
                        "defaulting to Summary Only"
                    )
                    category = EmailCategory.SUMMARY_ONLY

                priority = max(1, min(10, item.get("priority", 5)))

                categorization = Categorization(
                    category=category,
                    priority=priority,
                    summary=item.get("summary", "No summary provided")[:500],
                    reasoning=item.get("reasoning", "No reasoning provided")[:300],
                )
                results.append(CategorizedThread(thread=thread, categorization=categorization))

        return results

    def categorize_all(self, threads: list[EmailThread]) -> list[CategorizedThread]:
        """Process all threads in batches."""
        all_results: list[CategorizedThread] = []
        batch_size = self._config.batch_size

        for i in range(0, len(threads), batch_size):
            batch = threads[i : i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(threads) + batch_size - 1) // batch_size
            logger.info(f"Categorizing batch {batch_num}/{total_batches} ({len(batch)} threads)")

            try:
                results = self.categorize_batch(batch)
                all_results.extend(results)
            except Exception as e:
                logger.error(f"Failed to categorize batch {batch_num}: {e}", exc_info=True)
                for thread in batch:
                    all_results.append(
                        CategorizedThread(
                            thread=thread,
                            categorization=Categorization(
                                category=EmailCategory.SUMMARY_ONLY,
                                priority=5,
                                summary="[Categorization failed - please review manually]",
                                reasoning=f"AI categorization error: {str(e)[:200]}",
                            ),
                        )
                    )

        return all_results

    # ── Draft replies ───────────────────────────────────────────────────

    def draft_replies(self, threads: list[CategorizedThread]) -> list[CategorizedThread]:
        """For non-summary threads, determine if a reply is needed and draft one.

        Only threads categorized as Action Immediately or Action Eventually
        are evaluated. Summary Only threads are returned unchanged.
        """
        actionable = [
            ct for ct in threads
            if ct.categorization.category != EmailCategory.SUMMARY_ONLY
        ]
        summary_only = [
            ct for ct in threads
            if ct.categorization.category == EmailCategory.SUMMARY_ONLY
        ]

        if not actionable:
            logger.info("No actionable threads to draft replies for")
            return threads

        logger.info(f"Drafting replies for {len(actionable)} actionable threads")

        # Process in batches
        batch_size = self._config.batch_size
        drafted: list[CategorizedThread] = []

        for i in range(0, len(actionable), batch_size):
            batch = actionable[i : i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(actionable) + batch_size - 1) // batch_size
            logger.info(f"Drafting batch {batch_num}/{total_batches} ({len(batch)} threads)")

            try:
                results = self._draft_batch(batch)
                drafted.extend(results)
            except Exception as e:
                logger.error(f"Failed to draft batch {batch_num}: {e}", exc_info=True)
                # On failure, return threads without drafts
                drafted.extend(batch)

        return drafted + summary_only

    def _draft_batch(self, threads: list[CategorizedThread]) -> list[CategorizedThread]:
        """Send a batch of threads to Claude for reply drafting."""
        threads_xml = "\n\n".join(
            self._build_thread_xml(ct.thread) for ct in threads
        )

        prompt = DRAFT_REPLIES_PROMPT.format(
            count=len(threads),
            threads_xml=threads_xml,
        )

        try:
            response = self._client.messages.create(
                model=self._config.model,
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
                system=DRAFT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                tools=[DRAFT_TOOL],
                tool_choice={"type": "tool", "name": "submit_drafts"},
            )
        except anthropic.RateLimitError as e:
            raise AnthropicAPIError(f"Anthropic rate limit exceeded: {e}") from e
        except anthropic.APIError as e:
            raise AnthropicAPIError(f"Anthropic API error: {e}") from e

        return self._parse_draft_response(response, threads)

    def _parse_draft_response(
        self, response: anthropic.types.Message, threads: list[CategorizedThread]
    ) -> list[CategorizedThread]:
        """Apply draft results back onto CategorizedThread objects."""
        thread_map = {ct.thread.thread_id: ct for ct in threads}
        updated: list[CategorizedThread] = []

        for block in response.content:
            if block.type != "tool_use":
                continue

            drafts = block.input.get("drafts", [])
            for item in drafts:
                ct = thread_map.pop(item.get("thread_id", ""), None)
                if not ct:
                    logger.warning(f"AI returned unknown thread_id: {item.get('thread_id')}")
                    continue

                awaiting = item.get("awaiting_reply", False)
                reply = item.get("suggested_reply") if awaiting else None

                updated_categorization = ct.categorization.model_copy(
                    update={
                        "awaiting_reply": awaiting,
                        "suggested_reply": reply,
                    }
                )
                updated.append(
                    CategorizedThread(
                        thread=ct.thread,
                        categorization=updated_categorization,
                    )
                )

        # Any threads not returned by Claude get passed through unchanged
        for ct in thread_map.values():
            logger.warning(f"Thread {ct.thread.thread_id} not in draft response, keeping as-is")
            updated.append(ct)

        return updated

    # ── Shared helpers ──────────────────────────────────────────────────

    def _build_thread_xml(self, thread: EmailThread) -> str:
        """Build XML representation of a thread for the AI prompt."""
        if thread.message_count == 1:
            msg = thread.messages[0]
            return EMAIL_XML_TEMPLATE.format(
                thread_id=thread.thread_id,
                sender=msg.sender,
                subject=msg.subject,
                date=msg.date.isoformat(),
                body=(msg.body_plain or msg.snippet)[:3000],
            )

        messages_xml = "\n".join(
            THREAD_MESSAGE_XML_TEMPLATE.format(
                sender=msg.sender,
                date=msg.date.isoformat(),
                body=(msg.body_plain or msg.snippet)[:2000],
            )
            for msg in thread.messages
        )
        return THREAD_XML_TEMPLATE.format(
            thread_id=thread.thread_id,
            message_count=thread.message_count,
            subject=thread.subject,
            participants=", ".join(thread.participants),
            messages_xml=messages_xml,
        )
