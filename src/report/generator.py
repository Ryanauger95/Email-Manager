from __future__ import annotations

from pathlib import Path

from src.models import CategorizedEmail, Digest


class ReportGenerator:
    """Generates a pretty-printed Markdown digest report."""

    def generate(self, digest: Digest, output_path: str) -> str:
        lines: list[str] = []
        lines.append("# Email Digest Report")
        lines.append(
            f"**Generated:** {digest.generated_at.strftime('%Y-%m-%d %H:%M UTC')}"
        )
        lines.append(f"**Total Emails:** {digest.total_emails}")
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
            for email in digest.action_immediately:
                lines.extend(self._format_email(email, include_reply=True))
            lines.append("---")
            lines.append("")

        if digest.action_eventually:
            lines.append("## Action Eventually")
            lines.append("")
            for email in digest.action_eventually:
                lines.extend(self._format_email(email, include_reply=False))
            lines.append("---")
            lines.append("")

        if digest.summary_only:
            lines.append("## Summary Only")
            lines.append("")
            for email in digest.summary_only:
                lines.extend(self._format_email(email, include_reply=False))

        content = "\n".join(lines)
        Path(output_path).write_text(content, encoding="utf-8")
        return output_path

    def _format_email(
        self, ce: CategorizedEmail, include_reply: bool
    ) -> list[str]:
        lines: list[str] = []
        lines.append(f"### [{ce.email.subject}]({ce.email.gmail_link})")
        lines.append(f"- **From:** {ce.email.sender}")
        lines.append(f"- **Date:** {ce.email.date.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"- **Priority:** {ce.categorization.priority}/10")
        lines.append(f"- **Summary:** {ce.categorization.summary}")
        lines.append(f"- **Reasoning:** {ce.categorization.reasoning}")
        if include_reply and ce.categorization.suggested_reply:
            lines.append("- **Suggested Reply:**")
            lines.append(f"  > {ce.categorization.suggested_reply}")
        lines.append("")
        return lines
