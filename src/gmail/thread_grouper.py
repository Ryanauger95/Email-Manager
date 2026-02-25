from __future__ import annotations

from collections import defaultdict

from src.models import CategorizedThread, DigestGroup


class ThreadGrouper:
    """Groups categorized threads by sender domain for display."""

    @staticmethod
    def group_threads(threads: list[CategorizedThread]) -> list[DigestGroup]:
        """Group threads by sender domain for presentation.

        Threads are already consolidated (one entry per conversation),
        so this only handles domain-level grouping for display.
        Returns groups sorted by highest priority descending.
        """
        domain_groups: dict[str, list[CategorizedThread]] = defaultdict(list)

        for ct in threads:
            sender_email = ct.thread.messages[0].sender_email
            domain = (
                sender_email.split("@")[-1]
                if "@" in sender_email
                else "unknown"
            )
            domain_groups[domain].append(ct)

        digest_groups: list[DigestGroup] = []

        for domain, domain_threads in domain_groups.items():
            if len(domain_threads) > 1:
                digest_groups.append(
                    DigestGroup(
                        group_key=f"domain:{domain}",
                        group_label=f"From: {domain} ({len(domain_threads)} threads)",
                        threads=sorted(
                            domain_threads,
                            key=lambda t: t.categorization.priority,
                            reverse=True,
                        ),
                        highest_priority=max(
                            t.categorization.priority for t in domain_threads
                        ),
                    )
                )
            else:
                ct = domain_threads[0]
                label = ct.thread.subject
                if ct.thread.message_count > 1:
                    label = f"Thread: {label} ({ct.thread.message_count} messages)"
                digest_groups.append(
                    DigestGroup(
                        group_key=ct.thread.thread_id,
                        group_label=label,
                        threads=[ct],
                        highest_priority=ct.categorization.priority,
                    )
                )

        digest_groups.sort(key=lambda g: g.highest_priority, reverse=True)
        return digest_groups
