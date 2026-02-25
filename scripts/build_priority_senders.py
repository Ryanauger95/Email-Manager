"""Analyze sent mail to identify priority senders.

Scans threads where the user has replied, ranks external contacts by
frequency and conversation nature, then uses Claude to classify them
as key business contacts (brokers, accountants, lawyers, investors,
partners, etc.). Outputs a priority senders list and optionally appends
it to config/categorization_guidelines.md.

Usage:
    python scripts/build_priority_senders.py                    # Full run
    python scripts/build_priority_senders.py --max-threads 1000  # Scan more threads
    python scripts/build_priority_senders.py --dry-run           # Print results, don't write
    python scripts/build_priority_senders.py --min-messages 3    # Require 3+ messages exchanged
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

import anthropic
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"

GUIDELINES_PATH = PROJECT_ROOT / "config" / "categorization_guidelines.md"
OUTPUT_PATH = PROJECT_ROOT / "config" / "priority_senders.json"

# ── Gmail helpers ────────────────────────────────────────────────────────

def get_gmail_service():
    """Build Gmail API service using env credentials."""
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri=GOOGLE_TOKEN_URI,
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def extract_email(header_value: str) -> str:
    """Extract email address from a 'Name <email>' header."""
    if "<" in header_value and ">" in header_value:
        return header_value.split("<")[1].rstrip(">").lower().strip()
    return header_value.lower().strip()


def extract_name(header_value: str) -> str:
    """Extract display name from a 'Name <email>' header."""
    if "<" in header_value:
        name = header_value.split("<")[0].strip().strip('"')
        return name if name else extract_email(header_value)
    return header_value.strip()


def is_noreply(email: str) -> bool:
    """Filter out automated/noreply addresses."""
    skip_patterns = [
        "noreply", "no-reply", "donotreply", "do-not-reply",
        "mailer-daemon", "postmaster@", "bounce",
        "calendar-notification",
    ]
    email_lower = email.lower()
    return any(pattern in email_lower for pattern in skip_patterns)


# ── Fetch threads with user replies ─────────────────────────────────────

def fetch_replied_thread_ids(service, max_threads: int) -> set[str]:
    """Get thread IDs where the user has sent at least one message.

    Paginates through sent mail until we have enough unique thread IDs.
    """
    thread_ids: set[str] = set()
    page_token = None
    pages_fetched = 0

    while len(thread_ids) < max_threads:
        result = (
            service.users()
            .messages()
            .list(
                userId="me",
                q="from:me -label:draft -label:spam -label:trash",
                maxResults=500,
                pageToken=page_token,
            )
            .execute()
        )
        pages_fetched += 1

        messages = result.get("messages", [])
        if not messages:
            break

        for msg in messages:
            thread_ids.add(msg["threadId"])

        page_token = result.get("nextPageToken")
        if not page_token:
            break

        if pages_fetched % 5 == 0:
            logger.info(f"  Scanned {pages_fetched} pages, {len(thread_ids)} unique threads so far...")

    return thread_ids


def fetch_thread_metadata(service, thread_ids: set[str]) -> list[dict]:
    """Fetch metadata for each thread (From, To, Cc, Subject, Date headers)."""
    threads = []
    total = len(thread_ids)

    for i, thread_id in enumerate(thread_ids):
        if i > 0 and i % 100 == 0:
            logger.info(f"  Fetching thread details... {i}/{total}")

        try:
            thread = (
                service.users()
                .threads()
                .get(
                    userId="me", id=thread_id, format="metadata",
                    metadataHeaders=["From", "To", "Cc", "Subject", "Date"],
                )
                .execute()
            )
            threads.append(thread)
        except Exception as e:
            logger.warning(f"  Failed to fetch thread {thread_id}: {e}")

    return threads


# ── Analyze contacts ────────────────────────────────────────────────────

def analyze_contacts(threads: list[dict], user_email: str, min_messages: int) -> list[dict]:
    """Extract and rank contacts from threads.

    For each external contact, counts:
    - Total threads shared with user
    - Total messages exchanged (both directions)
    - Messages they sent to user
    - Messages user sent to them
    - Most recent interaction date
    - Sample subjects for context
    """
    user_email_lower = user_email.lower()

    # contact_email -> stats
    contacts: dict[str, dict] = defaultdict(lambda: {
        "email": "",
        "names": Counter(),
        "thread_count": 0,
        "messages_from_them": 0,
        "messages_to_them": 0,
        "subjects": [],
        "latest_date": "",
        "domain": "",
    })

    for thread in threads:
        thread_participants = set()
        subjects = set()

        for msg in thread.get("messages", []):
            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }

            from_email = extract_email(headers.get("from", ""))
            from_name = extract_name(headers.get("from", ""))

            subject = headers.get("subject", "")
            if subject:
                # Strip Re:/Fwd: prefixes for cleaner subjects
                clean = subject
                while True:
                    stripped = clean.strip()
                    lower = stripped.lower()
                    if lower.startswith("re:") or lower.startswith("fwd:"):
                        clean = stripped[4:]
                    elif lower.startswith("fw:"):
                        clean = stripped[3:]
                    else:
                        break
                subjects.add(clean.strip())

            # Collect all To/Cc recipients
            all_recipients = []
            for field in ["to", "cc"]:
                raw = headers.get(field, "")
                if raw:
                    all_recipients.extend(
                        extract_email(r.strip()) for r in raw.split(",")
                    )

            if from_email == user_email_lower:
                # User sent this message — count it for each recipient
                for recip in all_recipients:
                    if recip != user_email_lower and not is_noreply(recip):
                        thread_participants.add(recip)
                        contacts[recip]["messages_to_them"] += 1
                        contacts[recip]["email"] = recip
                        if "@" in recip:
                            contacts[recip]["domain"] = recip.split("@")[1]
            else:
                # Someone else sent this message
                if not is_noreply(from_email):
                    thread_participants.add(from_email)
                    c = contacts[from_email]
                    c["email"] = from_email
                    c["names"][from_name] += 1
                    c["messages_from_them"] += 1
                    if "@" in from_email:
                        c["domain"] = from_email.split("@")[1]

                    date_str = headers.get("date", "")
                    if date_str and date_str > c["latest_date"]:
                        c["latest_date"] = date_str

        # Update thread counts for all participants in this thread
        for email in thread_participants:
            c = contacts[email]
            c["email"] = email
            c["thread_count"] += 1
            if not c["domain"] and "@" in email:
                c["domain"] = email.split("@")[1]
            for subj in list(subjects)[:2]:
                if subj and subj not in c["subjects"] and len(c["subjects"]) < 8:
                    c["subjects"].append(subj)

    # Convert to sorted list, filter by minimum message threshold
    results = []
    for email, stats in contacts.items():
        total_messages = stats["messages_from_them"] + stats["messages_to_them"]
        if total_messages < min_messages:
            continue

        best_name = stats["names"].most_common(1)[0][0] if stats["names"] else email

        results.append({
            "email": email,
            "name": best_name,
            "domain": stats["domain"],
            "thread_count": stats["thread_count"],
            "messages_from_them": stats["messages_from_them"],
            "messages_to_them": stats["messages_to_them"],
            "total_messages": total_messages,
            "latest_date": stats["latest_date"],
            "sample_subjects": stats["subjects"][:8],
        })

    results.sort(key=lambda x: x["total_messages"], reverse=True)
    return results


# ── Claude classification ───────────────────────────────────────────────

CLASSIFY_PROMPT = """You are analyzing a user's email contacts to identify key business relationships that should always be treated as priority in their inbox.

**About the user:** Their email is {user_email}. Their company domain is @{user_domain}. Use context clues from domains, names, and subject lines to infer what they do and who matters.

Below is a list of their most frequent email contacts, ranked by total messages exchanged. For each contact you can see:
- How many threads they share
- How many messages they sent to the user vs. received from the user
- Sample email subjects (stripped of Re:/Fwd:)

**Your task:** For each contact, classify their likely relationship and whether they are a priority sender. A "priority sender" is someone whose emails should NEVER be categorized as "Summary Only" — they should always be at least "Action Eventually".

Priority senders are typically: brokers, accountants, lawyers, investors, business partners, key clients, critical vendors, or executives. People the user has frequent, substantive back-and-forth conversations with.

NOT priority: mass mailers, automated systems, one-off contacts, generic customer service, recruiters sending cold emails, mailing lists.

Relationship types:
- "broker" — real estate, financial, insurance, or other broker
- "accountant" — CPA, bookkeeper, tax, accounting firm
- "lawyer" — attorney, legal counsel, compliance
- "investor" — investor, LP, funding partner, lender
- "partner" — business partner, co-founder, JV partner
- "client" — paying client or customer
- "vendor" — critical vendor or service provider
- "executive" — C-level, VP, director (at user's company or closely related)
- "colleague" — frequent internal collaborator (same domain as user)
- "other_priority" — clearly important but doesn't fit above categories
- "low_priority" — not a key relationship (mass sender, automated, generic, cold outreach)

Look at the EVIDENCE: high message counts with substantive subjects = likely priority. Look at domains — brokerage firms, law firms, accounting firms, investment firms are strong signals. Same-domain contacts who exchange many messages are likely colleagues.

Here are the contacts:

{contacts_json}

Respond using the submit_classifications tool."""

CLASSIFY_TOOL = {
    "name": "submit_classifications",
    "description": "Submit contact classifications.",
    "input_schema": {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string"},
                        "relationship": {
                            "type": "string",
                            "enum": [
                                "broker", "accountant", "lawyer", "investor",
                                "partner", "client", "vendor", "executive",
                                "colleague", "other_priority", "low_priority",
                            ],
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Brief explanation for this classification",
                        },
                        "always_action": {
                            "type": "boolean",
                            "description": "true = emails from this contact should always be at least Action Eventually, never Summary Only",
                        },
                    },
                    "required": ["email", "relationship", "reasoning", "always_action"],
                },
            }
        },
        "required": ["classifications"],
    },
}


def classify_contacts_batch(
    contacts: list[dict], user_email: str, client: anthropic.Anthropic, model: str
) -> dict[str, dict]:
    """Classify a batch of contacts with Claude. Returns {email: classification}."""
    user_domain = user_email.split("@")[1] if "@" in user_email else "unknown"

    contacts_summary = []
    for c in contacts:
        contacts_summary.append({
            "email": c["email"],
            "name": c["name"],
            "domain": c["domain"],
            "thread_count": c["thread_count"],
            "messages_from_them": c["messages_from_them"],
            "messages_to_them": c["messages_to_them"],
            "total_messages": c["total_messages"],
            "sample_subjects": c["sample_subjects"],
        })

    prompt = CLASSIFY_PROMPT.format(
        user_email=user_email,
        user_domain=user_domain,
        contacts_json=json.dumps(contacts_summary, indent=2),
    )

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=0.1,
        system=(
            "You are a business contact analyst. Classify email contacts by relationship type. "
            "Be generous with priority classification — if the user has frequent substantive "
            "conversations with someone, they are likely important. Err on the side of marking "
            "someone as priority rather than low_priority when evidence is ambiguous."
        ),
        messages=[{"role": "user", "content": prompt}],
        tools=[CLASSIFY_TOOL],
        tool_choice={"type": "tool", "name": "submit_classifications"},
    )

    results = {}
    for block in response.content:
        if block.type == "tool_use":
            for item in block.input.get("classifications", []):
                results[item["email"]] = item

    return results


def classify_contacts(contacts: list[dict], user_email: str) -> list[dict]:
    """Use Claude to classify contacts by relationship type.

    Processes in batches of 40 to avoid token limits.
    """
    if not contacts:
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")

    if oauth_token:
        client = anthropic.Anthropic(auth_token=oauth_token)
    elif api_key:
        client = anthropic.Anthropic(api_key=api_key)
    else:
        logger.error("No Anthropic credentials found. Set ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN.")
        sys.exit(1)

    model = os.environ.get("AI_MODEL", "claude-sonnet-4-5-20250929")

    # Process in batches of 40
    batch_size = 40
    all_classifications: dict[str, dict] = {}

    for i in range(0, len(contacts), batch_size):
        batch = contacts[i : i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(contacts) + batch_size - 1) // batch_size
        logger.info(f"  Classifying batch {batch_num}/{total_batches} ({len(batch)} contacts)...")

        try:
            results = classify_contacts_batch(batch, user_email, client, model)
            all_classifications.update(results)
        except Exception as e:
            logger.error(f"  Failed to classify batch {batch_num}: {e}")

    # Merge classifications back into contacts
    classified = []
    for c in contacts:
        classification = all_classifications.get(c["email"], {})
        c["relationship"] = classification.get("relationship", "low_priority")
        c["always_action"] = classification.get("always_action", False)
        c["reasoning"] = classification.get("reasoning", "")
        classified.append(c)

    return classified


# ── Output ──────────────────────────────────────────────────────────────

def print_results(classified: list[dict]):
    """Pretty-print classification results."""
    priority = [c for c in classified if c["always_action"]]
    low = [c for c in classified if not c["always_action"]]

    bold = "\033[1m"
    green = "\033[92m"
    gray = "\033[90m"
    cyan = "\033[96m"
    reset = "\033[0m"

    print(f"\n{'=' * 70}")
    print(f"  {bold}PRIORITY SENDER ANALYSIS{reset}")
    print(f"{'=' * 70}")

    print(f"\n  {green}{bold}PRIORITY CONTACTS ({len(priority)}){reset}")
    print(f"  {green}{'─' * 66}{reset}")

    # Group by relationship type
    by_type: dict[str, list] = defaultdict(list)
    for c in priority:
        by_type[c["relationship"]].append(c)

    type_labels = {
        "broker": "Brokers",
        "accountant": "Accountants",
        "lawyer": "Lawyers",
        "investor": "Investors",
        "partner": "Partners",
        "client": "Clients",
        "vendor": "Vendors",
        "executive": "Executives",
        "colleague": "Colleagues",
        "other_priority": "Other Priority",
    }

    for rel_type, label in type_labels.items():
        group = by_type.get(rel_type, [])
        if not group:
            continue
        print(f"\n  {cyan}{bold}{label}{reset}")
        for c in sorted(group, key=lambda x: x["total_messages"], reverse=True):
            msgs = f"{c['total_messages']} msgs across {c['thread_count']} threads"
            print(f"    {bold}{c['name']}{reset} <{c['email']}>")
            print(f"      {msgs}")
            if c.get("reasoning"):
                print(f"      {gray}{c['reasoning']}{reset}")

    if low:
        print(f"\n  {gray}{'─' * 66}")
        print(f"  LOW PRIORITY ({len(low)} contacts not flagged as priority)")
        for c in low[:10]:
            print(f"    {c['name']} <{c['email']}> — {c['total_messages']} msgs, {c['thread_count']} threads")
        if len(low) > 10:
            print(f"    ... and {len(low) - 10} more")
        print(f"  {reset}")

    print(f"\n{'=' * 70}\n")


def save_json(classified: list[dict]):
    """Save full results to JSON."""
    priority = [c for c in classified if c["always_action"]]

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_analyzed": len(classified),
        "priority_count": len(priority),
        "priority_senders": [
            {
                "email": c["email"],
                "name": c["name"],
                "domain": c["domain"],
                "relationship": c["relationship"],
                "thread_count": c["thread_count"],
                "total_messages": c["total_messages"],
                "reasoning": c.get("reasoning", ""),
            }
            for c in priority
        ],
        "all_contacts": [
            {
                "email": c["email"],
                "name": c["name"],
                "domain": c["domain"],
                "relationship": c["relationship"],
                "always_action": c["always_action"],
                "thread_count": c["thread_count"],
                "total_messages": c["total_messages"],
            }
            for c in classified
        ],
    }

    OUTPUT_PATH.write_text(json.dumps(output, indent=2))
    logger.info(f"Saved results to {OUTPUT_PATH} ({len(priority)} priority, {len(classified)} total)")


def append_to_guidelines(classified: list[dict]):
    """Append a Priority Senders section to categorization_guidelines.md."""
    priority = [c for c in classified if c["always_action"]]
    if not priority:
        logger.info("No priority senders to add to guidelines")
        return

    # Group by relationship
    by_type: dict[str, list] = defaultdict(list)
    for c in priority:
        by_type[c["relationship"]].append(c)

    type_labels = {
        "broker": "Brokers",
        "accountant": "Accountants",
        "lawyer": "Lawyers",
        "investor": "Investors",
        "partner": "Partners",
        "client": "Clients",
        "vendor": "Vendors",
        "executive": "Executives",
        "colleague": "Colleagues",
        "other_priority": "Other Priority",
    }

    lines = [
        "",
        "---",
        "",
        "## Priority Senders",
        "",
        "Emails from the following contacts should **always** be categorized as at least \"Action Eventually\" — never \"Summary Only\". These are key business relationships identified from email history.",
        "",
    ]

    for rel_type, label in type_labels.items():
        group = by_type.get(rel_type, [])
        if not group:
            continue
        lines.append(f"### {label}")
        for c in sorted(group, key=lambda x: x["total_messages"], reverse=True):
            lines.append(f"- **{c['name']}** — `{c['email']}` ({c['total_messages']} messages)")
        lines.append("")

    lines.append(f"> Auto-generated on {datetime.now(timezone.utc).strftime('%Y-%m-%d')} by `build_priority_senders.py`. Re-run to refresh.")
    lines.append("")

    section_text = "\n".join(lines)

    if GUIDELINES_PATH.exists():
        content = GUIDELINES_PATH.read_text()

        # Replace existing Priority Senders section if present
        marker = "## Priority Senders"
        if marker in content:
            # Find the --- before Priority Senders
            idx = content.index(marker)
            # Walk backwards to find the preceding ---
            before_idx = content.rfind("---", 0, idx)
            if before_idx != -1:
                content = content[:before_idx].rstrip() + "\n" + section_text
            else:
                content = content[:idx].rstrip() + "\n\n" + section_text
        else:
            content = content.rstrip() + "\n" + section_text

        GUIDELINES_PATH.write_text(content)
        logger.info(f"Updated {GUIDELINES_PATH} with {len(priority)} priority senders")
    else:
        logger.warning(f"Guidelines file not found at {GUIDELINES_PATH}, skipping")


# ── Main ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Analyze sent mail to build priority sender list")
    parser.add_argument(
        "--max-threads", type=int, default=500,
        help="Max threads to scan (default: 500)",
    )
    parser.add_argument(
        "--min-messages", type=int, default=2,
        help="Minimum total messages exchanged to include contact (default: 2)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print results but don't write to files",
    )
    args = parser.parse_args()

    user_email = os.environ.get("USER_EMAIL", "")
    if not user_email:
        logger.error("USER_EMAIL not set in .env — required to identify your messages.")
        sys.exit(1)

    print(f"\n  Analyzing email contacts for: {user_email}")
    print(f"  Max threads: {args.max_threads} | Min messages: {args.min_messages}\n")

    # Step 1: Fetch thread IDs from sent mail
    service = get_gmail_service()

    logger.info("Step 1: Finding threads where you've replied...")
    thread_ids = fetch_replied_thread_ids(service, max_threads=args.max_threads)
    logger.info(f"  Found {len(thread_ids)} unique threads")

    if not thread_ids:
        logger.info("No sent threads found. Check your Gmail credentials.")
        return

    # Step 2: Fetch thread metadata
    logger.info(f"\nStep 2: Fetching thread metadata for {len(thread_ids)} threads...")
    threads = fetch_thread_metadata(service, thread_ids)
    logger.info(f"  Fetched {len(threads)} threads")

    # Step 3: Analyze contacts
    logger.info(f"\nStep 3: Analyzing contacts...")
    contacts = analyze_contacts(threads, user_email, min_messages=args.min_messages)
    logger.info(f"  Found {len(contacts)} contacts with {args.min_messages}+ messages exchanged")

    if not contacts:
        logger.info("No qualifying contacts found. Try lowering --min-messages.")
        return

    # Show top contacts before classification
    logger.info(f"\n  Top 10 by message volume:")
    for c in contacts[:10]:
        logger.info(f"    {c['name']} <{c['email']}> — {c['total_messages']} msgs, {c['thread_count']} threads")
        if c["sample_subjects"]:
            logger.info(f"      Subjects: {', '.join(c['sample_subjects'][:3])}")

    # Step 4: Classify with Claude
    logger.info(f"\nStep 4: Classifying {len(contacts)} contacts with Claude...")
    classified = classify_contacts(contacts, user_email)

    # Step 5: Output
    print_results(classified)

    if not args.dry_run:
        save_json(classified)
        append_to_guidelines(classified)
        print(f"  Files updated:")
        print(f"    - {OUTPUT_PATH}")
        print(f"    - {GUIDELINES_PATH}")
    else:
        print("  (Dry run — no files written)")

    print()


if __name__ == "__main__":
    main()
