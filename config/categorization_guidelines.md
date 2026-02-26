# Email Categorization Guidelines

These guidelines are injected into the AI prompt to control how emails and threads are categorized, prioritized, and drafted. Edit this document to tune behavior.

---

## Categories

### Summary Only
Emails that require no response or action from the user. Read-only information.

**Examples:**
- Newsletters and marketing emails
- Automated notifications (CI/CD, monitoring alerts that are FYI-only)
- Order confirmations and shipping updates
- Calendar event notifications where no RSVP is needed
- CC'd threads where the user is not addressed
- Promotional offers, product announcements
- Social media notifications
- Generic security alerts 

**Priority range:** 1-3

NOTE: Never mark something as Summary Only if I have sent a message in the email chain.

### Action Eventually
Emails that need a response or action, but are not time-sensitive. Can be addressed within a few days.

**Examples:**
- Non-urgent requests from colleagues
- Document review requests with a deadline several days out
- Meeting scheduling where timing is flexible
- Feedback or survey requests
- Expense reports or approvals that aren't overdue
- Follow-ups on non-critical projects

**Priority range:** 3-6

### Action Immediately
Emails requiring urgent attention. Time-sensitive requests, critical issues, or messages from key stakeholders that cannot wait.

**Examples:**
- Production incidents or outages
- Requests from leadership with same-day deadlines
- Client-facing issues or escalations
- Meeting invitations requiring immediate RSVP
- Time-sensitive approvals (contracts, offers, deals)
- Serious, specific security alerts

**Priority range:** 7-10

---

## Priority Scoring

| Score | Meaning | Typical scenario |
|-------|---------|------------------|
| 1-2 | Ignorable | Marketing, spam-adjacent, mass mailing |
| 3-4 | Low | Informational, no action needed soon |
| 5-6 | Moderate | Needs attention within a few days |
| 7-8 | High | Time-sensitive, important stakeholders |
| 9-10 | Critical | Immediate action required, production down |

---

## Thread Handling

When processing multi-message threads:

- **Evaluate holistically.** Consider the entire conversation, not just the latest message.
- **Category reflects current state.** If an urgent thread has been resolved in later messages, it may no longer be "Action Immediately."
- **Priority reflects urgency now.** A thread that was urgent yesterday but resolved today should have a lower priority.

---

## Draft Reply Rules

A draft reply should **only** be generated when ALL of these are true:

1. The thread is categorized as "Action Eventually" or "Action Immediately" (never "Summary Only")
2. The most recent message is **not** from the user
3. The sender is clearly waiting for the user to respond (asked a question, made a request, etc.)

A draft reply should **not** be generated when:

- The user sent the most recent message (they already replied)
- The thread is an automated notification that doesn't expect a human response
- The user is only CC'd and not directly addressed
- The thread has been resolved or closed
- The message is informational with no implicit request

**When in doubt, do not generate a draft.**

### Draft Tone

- Professional but not overly formal
- Concise — get to the point
- Match the tone of the thread (casual internal thread vs. formal client thread)
- Never commit the user to deadlines, meetings, or deliverables — use language like "I'll take a look" or "Let me get back to you on this"

---

## Edge Cases

| Scenario | Category | Notes |
|----------|----------|-------|
| Automated alert that requires human action (e.g., "approve this deploy") | Action Eventually or Immediately | Depends on urgency |
| Newsletter with a buried action item | Action Eventually | If there's a genuine task; otherwise Summary Only |
| Thread where user is CC'd but later directly addressed | Action Eventually | Reassess based on latest messages |
| Out-of-office auto-replies | Summary Only | Always |
| Calendar invites | Action Eventually | Unless the meeting is imminent |
| Invoices and billing | Action Eventually | Unless overdue or amount is unusual |

---

## Customization

To adjust these guidelines for your workflow, edit this file. Changes here will be reflected in the AI prompts at runtime once wired into the categorization system prompt.

### Adding sender-specific rules

You can add overrides for specific senders or domains:

### Sender Overrides
- kryzrestauro@gmail.com = Action Eventually
 
