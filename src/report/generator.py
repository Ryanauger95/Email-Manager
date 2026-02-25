from __future__ import annotations

from pathlib import Path

from src.models import CategorizedThread, Digest


class ReportGenerator:
    """Generates a pretty-printed Markdown digest report."""

    def generate(self, digest: Digest, output_path: str) -> str:
        lines: list[str] = []
        lines.append("# Email Digest Report")
        lines.append(
            f"**Generated:** {digest.generated_at.strftime('%Y-%m-%d %H:%M UTC')}"
        )
        lines.append(
            f"**Threads:** {digest.total_threads} | **Messages:** {digest.total_messages}"
        )
        lines.append("")
        lines.append("---")
        lines.append("")

        lines.append("## Summary")
        lines.append(f"- Action Immediately: {len(digest.action_immediately)}")
        lines.append(f"- Action Eventually: {len(digest.action_eventually)}")
        lines.append(f"- Summary Only: {len(digest.summary_only)}")
        lines.append("")
        lines.append("---")
        lines.append("")

        if digest.action_immediately:
            lines.append("## Action Immediately")
            lines.append("")
            for ct in digest.action_immediately:
                lines.extend(self._format_thread(ct, include_reply=True))
            lines.append("---")
            lines.append("")

        if digest.action_eventually:
            lines.append("## Action Eventually")
            lines.append("")
            for ct in digest.action_eventually:
                lines.extend(self._format_thread(ct, include_reply=True))
            lines.append("---")
            lines.append("")

        if digest.summary_only:
            lines.append("## Summary Only")
            lines.append("")
            for ct in digest.summary_only:
                lines.extend(self._format_thread(ct, include_reply=False))

        content = "\n".join(lines)
        Path(output_path).write_text(content, encoding="utf-8")
        return output_path

    def _format_thread(
        self, ct: CategorizedThread, include_reply: bool
    ) -> list[str]:
        lines: list[str] = []
        thread = ct.thread
        lines.append(f"### [{thread.subject}]({thread.gmail_link})")
        if thread.message_count > 1:
            lines.append(f"- **Thread:** {thread.message_count} messages")
            lines.append(f"- **Participants:** {', '.join(thread.participants)}")
        else:
            lines.append(f"- **From:** {thread.messages[0].sender}")
        lines.append(
            f"- **Date:** {thread.latest_date.strftime('%Y-%m-%d %H:%M')}"
        )
        lines.append(f"- **Priority:** {ct.categorization.priority}/10")
        lines.append(f"- **Summary:** {ct.categorization.summary}")
        lines.append(f"- **Reasoning:** {ct.categorization.reasoning}")
        if ct.categorization.awaiting_reply:
            lines.append("- **Status:** Awaiting your reply")
            if include_reply and ct.categorization.suggested_reply:
                lines.append("- **Draft Reply:**")
                lines.append(f"  > {ct.categorization.suggested_reply}")
        elif ct.categorization.category.value != "Summary Only":
            lines.append("- **Status:** No reply needed")
        lines.append("")
        return lines
