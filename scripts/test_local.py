"""Local test runner — runs the full pipeline end-to-end.

Loads credentials from .env file, fetches real emails from Gmail,
categorizes with Claude, generates the markdown report, sends a
Slack DM digest, and prints results to stdout.

Usage:
    python scripts/test_local.py               # Full pipeline (Gmail + AI + Slack)
    python scripts/test_local.py --skip-gmail   # Use fake emails instead of Gmail
    python scripts/test_local.py --skip-ai      # Skip AI, just test Gmail connection
    python scripts/test_local.py --skip-slack   # Skip Slack DM, just print to terminal
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env file
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())
else:
    print("WARNING: No .env file found. Set env vars manually or create .env from .env.example")


def make_fake_emails():
    """Generate fake emails for testing AI categorization without Gmail."""
    from src.models import RawEmail

    return [
        RawEmail(
            message_id="fake-001",
            thread_id="thread-001",
            subject="URGENT: Production server down - need immediate fix",
            sender="Sarah Chen <sarah.chen@company.com>",
            sender_email="sarah.chen@company.com",
            recipient="me@company.com",
            date=datetime.now(timezone.utc),
            snippet="The production API is returning 500 errors...",
            body_plain=(
                "Hi,\n\nThe production API server has been returning 500 errors for the "
                "last 15 minutes. Customer-facing services are affected. Can you jump on "
                "this immediately? I've already looped in the on-call team but we need "
                "your expertise on the database layer.\n\nThanks,\nSarah"
            ),
            label_ids=[],
            gmail_link="https://mail.google.com/mail/u/0/#inbox/fake-001",
        ),
        RawEmail(
            message_id="fake-002",
            thread_id="thread-002",
            subject="Q3 Planning: Please review the proposed roadmap by Friday",
            sender="Mike Johnson <mike.j@company.com>",
            sender_email="mike.j@company.com",
            recipient="me@company.com",
            date=datetime.now(timezone.utc),
            snippet="Attached is the Q3 roadmap proposal...",
            body_plain=(
                "Hey team,\n\nI've put together the Q3 roadmap proposal based on our "
                "strategy session last week. Please review the attached document and "
                "leave comments by end of day Friday. We'll discuss in Monday's meeting.\n\n"
                "Key changes from Q2:\n- Shifted focus to mobile\n- New hire for platform team\n"
                "- Deprioritized internal tooling\n\nBest,\nMike"
            ),
            label_ids=[],
            gmail_link="https://mail.google.com/mail/u/0/#inbox/fake-002",
        ),
        RawEmail(
            message_id="fake-003",
            thread_id="thread-003",
            subject="Your weekly GitHub digest",
            sender="GitHub <notifications@github.com>",
            sender_email="notifications@github.com",
            recipient="me@company.com",
            date=datetime.now(timezone.utc),
            snippet="Here's what happened this week...",
            body_plain=(
                "Here's your weekly summary:\n\n"
                "- 12 new issues opened\n- 8 pull requests merged\n"
                "- 3 new releases published\n\nTop repositories:\n"
                "- company/api-server: 5 PRs merged\n- company/web-app: 3 PRs merged"
            ),
            label_ids=[],
            gmail_link="https://mail.google.com/mail/u/0/#inbox/fake-003",
        ),
        RawEmail(
            message_id="fake-004",
            thread_id="thread-004",
            subject="Invoice #4521 from Acme Cloud Services",
            sender="billing@acmecloud.com",
            sender_email="billing@acmecloud.com",
            recipient="me@company.com",
            date=datetime.now(timezone.utc),
            snippet="Your monthly invoice is ready...",
            body_plain=(
                "Your invoice for February 2026 is now available.\n\n"
                "Amount: $2,847.00\nDue date: March 15, 2026\n\n"
                "View and pay your invoice at: https://acmecloud.com/billing/4521"
            ),
            label_ids=[],
            gmail_link="https://mail.google.com/mail/u/0/#inbox/fake-004",
        ),
        RawEmail(
            message_id="fake-005",
            thread_id="thread-001",
            subject="Re: URGENT: Production server down - need immediate fix",
            sender="DevOps Bot <alerts@company.com>",
            sender_email="alerts@company.com",
            recipient="me@company.com",
            date=datetime.now(timezone.utc),
            snippet="Auto-scaling triggered, 3 new instances...",
            body_plain=(
                "Auto-scaling has been triggered for production-api cluster.\n\n"
                "- 3 new instances launched\n- Current healthy instances: 5/8\n"
                "- Error rate: 23% (down from 67%)\n\nThe situation is improving but "
                "not fully resolved. Database connection pool may need manual intervention."
            ),
            label_ids=[],
            gmail_link="https://mail.google.com/mail/u/0/#inbox/fake-005",
        ),
    ]


def print_results(categorized_emails, digest, report_path):
    """Pretty-print results to terminal."""
    from src.models import EmailCategory

    print("\n" + "=" * 70)
    print("  EMAIL MANAGER — LOCAL TEST RESULTS")
    print("=" * 70)

    print(f"\n  Total emails processed: {len(categorized_emails)}")

    categories = {
        EmailCategory.ACTION_IMMEDIATELY: [],
        EmailCategory.ACTION_EVENTUALLY: [],
        EmailCategory.SUMMARY_ONLY: [],
    }
    for e in categorized_emails:
        categories[e.categorization.category].append(e)

    colors = {
        EmailCategory.ACTION_IMMEDIATELY: "\033[91m",  # Red
        EmailCategory.ACTION_EVENTUALLY: "\033[93m",    # Yellow
        EmailCategory.SUMMARY_ONLY: "\033[90m",         # Gray
    }
    reset = "\033[0m"
    bold = "\033[1m"

    for category, emails in categories.items():
        color = colors[category]
        print(f"\n{color}{bold}  {'─' * 66}")
        print(f"  {category.value.upper()} ({len(emails)} emails)")
        print(f"  {'─' * 66}{reset}")

        for e in sorted(emails, key=lambda x: x.categorization.priority, reverse=True):
            print(f"\n  {color}{'●' * e.categorization.priority}{'○' * (10 - e.categorization.priority)}{reset} P{e.categorization.priority}")
            print(f"  {bold}{e.email.subject}{reset}")
            print(f"  From: {e.email.sender}")
            print(f"  {e.categorization.summary}")
            print(f"  Reason: {e.categorization.reasoning}")
            if e.categorization.suggested_reply:
                print(f"  {bold}Suggested reply:{reset} {e.categorization.suggested_reply[:150]}")
            print(f"  Link: {e.email.gmail_link}")

    if report_path and Path(report_path).exists():
        print(f"\n{'=' * 70}")
        print(f"  Markdown report saved to: {report_path}")

    if digest and digest.groups:
        print(f"\n  Email groups: {len(digest.groups)}")
        for group in digest.groups:
            print(f"    - {group.group_label} ({len(group.emails)} emails, max P{group.highest_priority})")

    print(f"\n{'=' * 70}\n")


def run_test(
    skip_gmail: bool = False,
    skip_ai: bool = False,
    skip_slack: bool = False,
):
    from src.config import load_config
    from src.logging_config import setup_logging
    from src.models import EmailCategory, Digest
    from src.gmail.client import GmailClient
    from src.gmail.thread_grouper import ThreadGrouper
    from src.ai.categorizer import EmailCategorizer
    from src.report.generator import ReportGenerator
    from src.report.slack_formatter import SlackFormatter
    from src.notifications.slack import SlackNotifier

    config = load_config()
    config.logging.format = "text"
    config.report.output_path = str(Path(__file__).parent.parent / "test_digest.md")

    # Validate Slack early so we fail fast if creds are missing
    if not skip_slack:
        config.slack.validate()
    else:
        config.slack.enabled = False

    setup_logging(level="DEBUG", log_format="text")

    total_steps = 5 if not skip_slack else 4
    step = 0

    # Step 1: Get emails
    step += 1
    print(f"\n[{step}/{total_steps}] Gathering emails...")
    if skip_gmail:
        print("  (Using fake emails — Gmail skipped)")
        raw_emails = make_fake_emails()
    else:
        gmail_client = GmailClient(config.gmail)
        raw_emails = gmail_client.fetch_unlabeled_emails()

    print(f"  Got {len(raw_emails)} emails")

    if not raw_emails:
        print("\n  No emails to process. Done!")
        return

    if skip_ai:
        print(f"\n[{step + 1}/{total_steps}] Skipping AI categorization")
        print("  Emails fetched successfully. Gmail connection works!\n")
        for e in raw_emails:
            print(f"  - {e.subject}")
            print(f"    From: {e.sender} | Date: {e.date}")
        return

    # Step 2: Categorize
    step += 1
    print(f"\n[{step}/{total_steps}] Categorizing with Claude...")
    categorizer = EmailCategorizer(config.ai)
    categorized = categorizer.categorize_all(raw_emails)
    print(f"  Categorized {len(categorized)} emails")

    # Step 3: Group
    step += 1
    print(f"\n[{step}/{total_steps}] Grouping emails...")
    grouper = ThreadGrouper()
    groups = grouper.group_emails(categorized)
    print(f"  Created {len(groups)} groups")

    # Step 4: Generate report
    step += 1
    print(f"\n[{step}/{total_steps}] Generating report...")
    digest = Digest(
        generated_at=datetime.now(timezone.utc),
        total_emails=len(categorized),
        groups=groups,
        action_immediately=sorted(
            [e for e in categorized if e.categorization.category == EmailCategory.ACTION_IMMEDIATELY],
            key=lambda e: e.categorization.priority, reverse=True,
        ),
        action_eventually=sorted(
            [e for e in categorized if e.categorization.category == EmailCategory.ACTION_EVENTUALLY],
            key=lambda e: e.categorization.priority, reverse=True,
        ),
        summary_only=sorted(
            [e for e in categorized if e.categorization.category == EmailCategory.SUMMARY_ONLY],
            key=lambda e: e.categorization.priority, reverse=True,
        ),
    )

    report_gen = ReportGenerator()
    report_path = report_gen.generate(digest, config.report.output_path)

    # Always print to terminal
    print_results(categorized, digest, report_path)

    # Step 5: Send Slack DM
    if not skip_slack:
        step += 1
        print(f"[{step}/{total_steps}] Sending Slack DM digest...")
        print(f"  Bot token: {config.slack.bot_token[:12]}...")
        print(f"  User ID: {config.slack.user_id}")

        formatter = SlackFormatter(
            max_per_category=config.slack.max_emails_per_category,
            include_reply_drafts=config.slack.include_reply_drafts,
        )
        slack_payload = formatter.format_digest(digest)
        notifier = SlackNotifier(config.slack)
        notifier.send(slack_payload)
        print("  \033[92mSlack DM sent! Check your Slack.\033[0m")

    print(f"\n{'=' * 70}")
    print("  ALL TESTS PASSED")
    print(f"{'=' * 70}\n")


def main():
    parser = argparse.ArgumentParser(description="Test Email Manager locally")
    parser.add_argument(
        "--skip-gmail", action="store_true",
        help="Use fake emails instead of connecting to Gmail",
    )
    parser.add_argument(
        "--skip-ai", action="store_true",
        help="Skip AI categorization — just test Gmail connection",
    )
    parser.add_argument(
        "--skip-slack", action="store_true",
        help="Skip Slack DM — just print results to terminal",
    )
    args = parser.parse_args()

    try:
        run_test(
            skip_gmail=args.skip_gmail,
            skip_ai=args.skip_ai,
            skip_slack=args.skip_slack,
        )
    except Exception as e:
        print(f"\n\033[91mERROR: {type(e).__name__}: {e}\033[0m", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
