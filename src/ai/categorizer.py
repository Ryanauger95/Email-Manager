from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional

import anthropic

from src.ai.prompts import BATCH_CATEGORIZATION_PROMPT, EMAIL_XML_TEMPLATE, SYSTEM_PROMPT
from src.models import Categorization, CategorizedEmail, EmailCategory, RawEmail
from src.utils.errors import AnthropicAPIError

if TYPE_CHECKING:
    from src.config import AIConfig

logger = logging.getLogger(__name__)

CATEGORIZATION_TOOL = {
    "name": "submit_categorizations",
    "description": "Submit the categorization results for a batch of emails.",
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
                        "suggested_reply": {"type": ["string", "null"]},
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


class EmailCategorizer:
    """Uses Anthropic Claude to categorize emails via tool use for structured output."""

    def __init__(self, config: AIConfig):
        self._config = config
        # Support both API key and OAuth token (from `claude setup-token`)
        # OAuth token uses Bearer auth header; API key uses x-api-key header
        if config.oauth_token:
            self._client = anthropic.Anthropic(auth_token=config.oauth_token)
        else:
            self._client = anthropic.Anthropic(api_key=config.api_key)

    def categorize_batch(self, emails: list[RawEmail]) -> list[CategorizedEmail]:
        """Categorize a batch of emails in a single API call using tool use."""
        if not emails:
            return []

        emails_xml = "\n\n".join(
            EMAIL_XML_TEMPLATE.format(
                message_id=email.message_id,
                sender=email.sender,
                subject=email.subject,
                date=email.date.isoformat(),
                body=(email.body_plain or email.snippet)[:3000],
            )
            for email in emails
        )

        prompt = BATCH_CATEGORIZATION_PROMPT.format(
            count=len(emails),
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

        return self._parse_response(response, emails)

    def _parse_response(
        self, response: anthropic.types.Message, emails: list[RawEmail]
    ) -> list[CategorizedEmail]:
        email_map = {e.message_id: e for e in emails}
        results: list[CategorizedEmail] = []

        for block in response.content:
            if block.type != "tool_use":
                continue

            categorizations = block.input.get("categorizations", [])
            for item in categorizations:
                email = email_map.get(item.get("email_id", ""))
                if not email:
                    logger.warning(f"AI returned unknown email_id: {item.get('email_id')}")
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

                suggested_reply = item.get("suggested_reply")
                if category != EmailCategory.ACTION_IMMEDIATELY:
                    suggested_reply = None

                categorization = Categorization(
                    category=category,
                    priority=priority,
                    summary=item.get("summary", "No summary provided")[:500],
                    reasoning=item.get("reasoning", "No reasoning provided")[:300],
                    suggested_reply=suggested_reply,
                )
                results.append(CategorizedEmail(email=email, categorization=categorization))

        return results

    def categorize_all(self, emails: list[RawEmail]) -> list[CategorizedEmail]:
        """Process all emails in batches."""
        all_results: list[CategorizedEmail] = []
        batch_size = self._config.batch_size

        for i in range(0, len(emails), batch_size):
            batch = emails[i : i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(emails) + batch_size - 1) // batch_size
            logger.info(f"Categorizing batch {batch_num}/{total_batches} ({len(batch)} emails)")

            try:
                results = self.categorize_batch(batch)
                all_results.extend(results)
            except Exception as e:
                logger.error(f"Failed to categorize batch {batch_num}: {e}", exc_info=True)
                for email in batch:
                    all_results.append(
                        CategorizedEmail(
                            email=email,
                            categorization=Categorization(
                                category=EmailCategory.SUMMARY_ONLY,
                                priority=5,
                                summary="[Categorization failed - please review manually]",
                                reasoning=f"AI categorization error: {str(e)[:200]}",
                            ),
                        )
                    )

        return all_results
