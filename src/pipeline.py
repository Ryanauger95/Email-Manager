from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.ai.categorizer import EmailCategorizer
from src.config import AppConfig
from src.gmail.client import GmailClient
from src.gmail.thread_grouper import ThreadGrouper
from src.logging_config import get_json_formatter
from src.models import (
    CategorizedThread,
    Digest,
    DigestGroup,
    EmailCategory,
    EmailThread,
    LambdaResponse,
    PipelineState,
    RawEmail,
)
from src.notifications.slack import SlackNotifier
from src.report.generator import ReportGenerator
from src.report.slack_formatter import SlackFormatter

logger = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    """Accumulates data as the pipeline progresses through states."""

    config: AppConfig
    request_id: Optional[str] = None

    # State tracking
    success: bool = True
    error: Optional[Exception] = None
    failed_state: Optional[PipelineState] = None
    errors: list[str] = field(default_factory=list)

    # Pipeline data
    raw_emails: list[RawEmail] = field(default_factory=list)
    threads: list[EmailThread] = field(default_factory=list)
    categorized_threads: list[CategorizedThread] = field(default_factory=list)
    groups: list[DigestGroup] = field(default_factory=list)
    digest: Optional[Digest] = None
    report_path: Optional[str] = None
    slack_sent: bool = False


# Ordered list of states the pipeline transitions through on success
_STATE_ORDER = [
    PipelineState.INIT,
    PipelineState.GATHER_EMAILS,
    PipelineState.CATEGORIZE_EMAILS,
    PipelineState.DRAFT_REPLIES,
    PipelineState.GROUP_EMAILS,
    PipelineState.GENERATE_REPORT,
    PipelineState.REPORT,
]


class PipelineRunner:
    """Runs the email processing pipeline as an in-process state machine.

    States: INIT -> GATHER_EMAILS -> CATEGORIZE_EMAILS -> DRAFT_REPLIES -> GROUP_EMAILS -> GENERATE_REPORT -> REPORT
    Any failure transitions directly to REPORT, which sends either a success digest or failure alert.
    """

    def __init__(self, config: AppConfig, request_id: Optional[str] = None):
        self._config = config
        self._context = PipelineContext(config=config, request_id=request_id)
        self._current_state = PipelineState.INIT

        self._state_handlers = {
            PipelineState.INIT: self._execute_init,
            PipelineState.GATHER_EMAILS: self._execute_gather,
            PipelineState.CATEGORIZE_EMAILS: self._execute_categorize,
            PipelineState.DRAFT_REPLIES: self._execute_draft_replies,
            PipelineState.GROUP_EMAILS: self._execute_group,
            PipelineState.GENERATE_REPORT: self._execute_generate_report,
            PipelineState.REPORT: self._execute_report,
        }

    def run(self) -> LambdaResponse:
        """Execute the pipeline. Always reaches REPORT state."""
        for state in _STATE_ORDER:
            self._transition_to(state)

            if state == PipelineState.REPORT:
                # REPORT is always executed, even on failure
                self._state_handlers[state]()
                break

            try:
                start = time.monotonic()
                self._state_handlers[state]()
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    f"State {state.value} completed in {duration_ms}ms",
                    extra={"duration_ms": duration_ms, "state": state.value},
                )
            except Exception as e:
                self._context.success = False
                self._context.error = e
                self._context.failed_state = state
                self._context.errors.append(f"[{state.value}] {type(e).__name__}: {e}")
                logger.error(
                    f"State {state.value} failed: {e}",
                    exc_info=True,
                    extra={"state": state.value},
                )
                # Jump to REPORT
                self._transition_to(PipelineState.REPORT)
                self._state_handlers[PipelineState.REPORT]()
                break

        return self._build_response()

    def _transition_to(self, new_state: PipelineState) -> None:
        old_state = self._current_state
        self._current_state = new_state
        logger.info(f"State transition: {old_state.value} -> {new_state.value}")

        formatter = get_json_formatter()
        if formatter:
            formatter.set_state(new_state.value)

    def _execute_init(self) -> None:
        self._config.slack.validate()
        logger.info("Pipeline initialized", extra={"state": "INIT"})

    def _execute_gather(self) -> None:
        gmail_client = GmailClient(self._config.gmail)
        self._context.raw_emails = gmail_client.fetch_unlabeled_emails()
        logger.info(f"Gathered {len(self._context.raw_emails)} emails")

        if not self._context.raw_emails:
            logger.info("No unlabeled emails found — pipeline will report empty digest")
            return

        # Consolidate individual emails into threads
        self._context.threads = GmailClient.consolidate_into_threads(
            self._context.raw_emails
        )
        logger.info(
            f"Consolidated {len(self._context.raw_emails)} emails into "
            f"{len(self._context.threads)} threads"
        )

    def _execute_categorize(self) -> None:
        if not self._context.threads:
            logger.info("No threads to categorize, skipping")
            return

        categorizer = EmailCategorizer(self._config.ai, user_email=self._config.gmail.user_email)
        self._context.categorized_threads = categorizer.categorize_all(
            self._context.threads
        )
        logger.info(f"Categorized {len(self._context.categorized_threads)} threads")

    def _execute_draft_replies(self) -> None:
        if not self._context.categorized_threads:
            logger.info("No categorized threads to draft replies for, skipping")
            return

        categorizer = EmailCategorizer(self._config.ai, user_email=self._config.gmail.user_email)
        self._context.categorized_threads = categorizer.draft_replies(
            self._context.categorized_threads
        )

        drafted_count = sum(
            1 for ct in self._context.categorized_threads
            if ct.categorization.awaiting_reply
        )
        logger.info(
            f"Draft phase complete: {drafted_count} threads awaiting reply"
        )

    def _execute_group(self) -> None:
        if not self._context.categorized_threads:
            logger.info("No categorized threads to group, skipping")
            return

        grouper = ThreadGrouper()
        self._context.groups = grouper.group_threads(self._context.categorized_threads)
        logger.info(f"Created {len(self._context.groups)} display groups")

    def _execute_generate_report(self) -> None:
        now = datetime.now(timezone.utc)
        categorized = self._context.categorized_threads
        total_messages = sum(ct.thread.message_count for ct in categorized)

        self._context.digest = Digest(
            generated_at=now,
            total_threads=len(categorized),
            total_messages=total_messages,
            groups=self._context.groups,
            action_immediately=sorted(
                [
                    t
                    for t in categorized
                    if t.categorization.category == EmailCategory.ACTION_IMMEDIATELY
                ],
                key=lambda t: t.categorization.priority,
                reverse=True,
            ),
            action_eventually=sorted(
                [
                    t
                    for t in categorized
                    if t.categorization.category == EmailCategory.ACTION_EVENTUALLY
                ],
                key=lambda t: t.categorization.priority,
                reverse=True,
            ),
            summary_only=sorted(
                [
                    t
                    for t in categorized
                    if t.categorization.category == EmailCategory.SUMMARY_ONLY
                ],
                key=lambda t: t.categorization.priority,
                reverse=True,
            ),
        )

        if categorized:
            try:
                report_gen = ReportGenerator()
                self._context.report_path = report_gen.generate(
                    self._context.digest, self._config.report.output_path
                )
                logger.info(f"Report generated at {self._context.report_path}")
            except Exception as e:
                logger.error(f"Report file generation failed: {e}", exc_info=True)
                self._context.errors.append(f"Report generation failed: {e}")

    def _execute_report(self) -> None:
        """Terminal state: send Slack notification (success digest or failure alert)."""
        if not self._config.slack.enabled:
            logger.info("Slack notifications disabled, skipping")
            return

        formatter = SlackFormatter(
            max_per_category=self._config.slack.max_emails_per_category,
            include_reply_drafts=self._config.slack.include_reply_drafts,
        )
        notifier = SlackNotifier(self._config.slack)

        if self._context.success:
            self._send_success_notification(formatter, notifier)
        else:
            self._send_failure_notification(formatter, notifier)

    def _send_success_notification(
        self, formatter: SlackFormatter, notifier: SlackNotifier
    ) -> None:
        if self._context.digest is None:
            logger.info("No digest to send (no emails found)")
            return

        if self._context.digest.total_threads == 0:
            logger.info("Empty digest, skipping Slack notification")
            return

        try:
            payload = formatter.format_digest(self._context.digest)
            notifier.send(payload)
            self._context.slack_sent = True
            logger.info("Success digest sent to Slack")
        except Exception as e:
            logger.error(f"Failed to send success digest to Slack: {e}", exc_info=True)
            self._context.errors.append(f"Slack delivery failed: {e}")

    def _send_failure_notification(
        self, formatter: SlackFormatter, notifier: SlackNotifier
    ) -> None:
        if self._context.error is None or self._context.failed_state is None:
            return

        try:
            payload = formatter.format_failure(
                failed_state=self._context.failed_state,
                error=self._context.error,
                request_id=self._context.request_id,
            )
            notifier.send(payload)
            self._context.slack_sent = True
            logger.info("Failure alert sent to Slack")
        except Exception as e:
            # Last resort: CloudWatch will always have the error logged above
            logger.error(
                f"CRITICAL: Failed to send failure alert to Slack: {e}. "
                f"Original error in state {self._context.failed_state.value}: "
                f"{self._context.error}",
                exc_info=True,
            )

    def _build_response(self) -> LambdaResponse:
        categorized = self._context.categorized_threads
        total_messages = sum(ct.thread.message_count for ct in categorized)
        category_counts = {}
        if categorized:
            category_counts = {
                "Action Immediately": sum(
                    1
                    for t in categorized
                    if t.categorization.category == EmailCategory.ACTION_IMMEDIATELY
                ),
                "Action Eventually": sum(
                    1
                    for t in categorized
                    if t.categorization.category == EmailCategory.ACTION_EVENTUALLY
                ),
                "Summary Only": sum(
                    1
                    for t in categorized
                    if t.categorization.category == EmailCategory.SUMMARY_ONLY
                ),
            }

        return LambdaResponse(
            status="success" if self._context.success else "error",
            threads_processed=len(categorized),
            emails_processed=total_messages,
            emails_by_category=category_counts,
            slack_sent=self._context.slack_sent,
            report_location=self._context.report_path,
            errors=self._context.errors,
        )
