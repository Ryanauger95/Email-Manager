from __future__ import annotations

from collections import defaultdict

from src.models import CategorizedEmail, DigestGroup


class ThreadGrouper:
    """Groups categorized emails by thread ID and sender domain."""

    @staticmethod
    def group_emails(emails: list[CategorizedEmail]) -> list[DigestGroup]:
        """Group emails by threadId first, then by sender domain for singletons.

        Returns groups sorted by highest priority descending.
        """
        thread_groups: dict[str, list[CategorizedEmail]] = defaultdict(list)
        for email in emails:
            thread_groups[email.email.thread_id].append(email)

        digest_groups: list[DigestGroup] = []
        singleton_emails: list[CategorizedEmail] = []

        for thread_id, thread_emails in thread_groups.items():
            if len(thread_emails) > 1:
                subject = thread_emails[0].email.subject
                digest_groups.append(
                    DigestGroup(
                        group_key=thread_id,
                        group_label=f"Thread: {subject}",
                        emails=sorted(thread_emails, key=lambda e: e.email.date),
                        highest_priority=max(
                            e.categorization.priority for e in thread_emails
                        ),
                    )
                )
            else:
                singleton_emails.extend(thread_emails)

        domain_groups: dict[str, list[CategorizedEmail]] = defaultdict(list)
        for email in singleton_emails:
            domain = (
                email.email.sender_email.split("@")[-1]
                if "@" in email.email.sender_email
                else "unknown"
            )
            domain_groups[domain].append(email)

        for domain, domain_emails in domain_groups.items():
            if len(domain_emails) > 1:
                digest_groups.append(
                    DigestGroup(
                        group_key=f"domain:{domain}",
                        group_label=f"From: {domain} ({len(domain_emails)} emails)",
                        emails=sorted(
                            domain_emails,
                            key=lambda e: e.categorization.priority,
                            reverse=True,
                        ),
                        highest_priority=max(
                            e.categorization.priority for e in domain_emails
                        ),
                    )
                )
            else:
                e = domain_emails[0]
                digest_groups.append(
                    DigestGroup(
                        group_key=e.email.message_id,
                        group_label=e.email.subject,
                        emails=[e],
                        highest_priority=e.categorization.priority,
                    )
                )

        digest_groups.sort(key=lambda g: g.highest_priority, reverse=True)
        return digest_groups
