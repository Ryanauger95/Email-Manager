from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class EmailCategory(str, Enum):
    SUMMARY_ONLY = "Summary Only"
    ACTION_EVENTUALLY = "Action Eventually"
    ACTION_IMMEDIATELY = "Action Immediately"


class PipelineState(str, Enum):
    INIT = "INIT"
    GATHER_EMAILS = "GATHER_EMAILS"
    CATEGORIZE_EMAILS = "CATEGORIZE_EMAILS"
    DRAFT_REPLIES = "DRAFT_REPLIES"
    APPLY_LABELS = "APPLY_LABELS"
    GROUP_EMAILS = "GROUP_EMAILS"
    GENERATE_REPORT = "GENERATE_REPORT"
    REPORT = "REPORT"


class RawEmail(BaseModel):
    message_id: str
    thread_id: str
    subject: str
    sender: str
    sender_email: str
    recipient: str
    date: datetime
    snippet: str
    body_plain: Optional[str] = None
    body_html: Optional[str] = None
    label_ids: list[str] = Field(default_factory=list)
    gmail_link: str


class Categorization(BaseModel):
    category: EmailCategory
    priority: int = Field(ge=1, le=10)
    summary: str = Field(max_length=500)
    reasoning: str = Field(max_length=300)
    awaiting_reply: bool = False
    suggested_reply: Optional[str] = None


class CategorizedEmail(BaseModel):
    email: RawEmail
    categorization: Categorization


class EmailThread(BaseModel):
    """A conversation thread containing one or more chronologically ordered emails."""

    thread_id: str
    subject: str
    messages: list[RawEmail]
    gmail_link: str
    message_count: int
    latest_date: datetime
    participants: list[str]


class CategorizedThread(BaseModel):
    """A thread with a single holistic categorization."""

    thread: EmailThread
    categorization: Categorization


class DigestGroup(BaseModel):
    group_key: str
    group_label: str
    threads: list[CategorizedThread]
    highest_priority: int


class Digest(BaseModel):
    generated_at: datetime
    total_threads: int
    total_messages: int
    groups: list[DigestGroup]
    action_immediately: list[CategorizedThread]
    action_eventually: list[CategorizedThread]
    summary_only: list[CategorizedThread]


class LambdaResponse(BaseModel):
    status: str
    threads_processed: int
    emails_processed: int
    emails_by_category: dict[str, int]
    slack_sent: bool
    report_location: Optional[str] = None
    errors: list[str] = Field(default_factory=list)
