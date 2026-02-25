# Email Manager

Serverless pipeline that reads your unlabeled Gmail emails, categorizes them with Claude AI, and sends you a prioritized Slack DM digest every hour.

## How It Works

```
INIT → GATHER_EMAILS → CATEGORIZE_EMAILS → GROUP_EMAILS → GENERATE_REPORT → REPORT
```

The pipeline runs as an in-process state machine. On failure at any stage, it jumps directly to `REPORT` and sends a Slack error alert with the failed state and traceback.

**What each stage does:**

1. **GATHER_EMAILS** — Fetches unlabeled emails from Gmail (`has:nouserlabels newer_than:2h`)
2. **CATEGORIZE_EMAILS** — Sends emails to Claude in batches, categorizes each as:
   - **Action Immediately** — Needs your attention now
   - **Action Eventually** — Needs a response, but not urgent
   - **Summary Only** — FYI, no action needed
3. **GROUP_EMAILS** — Groups related emails by thread/sender to reduce noise
4. **GENERATE_REPORT** — Builds a markdown digest with priority scores (1-10), summaries, and suggested reply drafts for urgent emails
5. **REPORT** — Sends the digest as a Slack DM (or a failure alert if something went wrong)

## Project Structure

```
src/
├── handler.py              # Lambda entrypoint
├── pipeline.py             # State machine runner
├── config.py               # Config loading (env + config.yaml)
├── models.py               # Pydantic models
├── logging_config.py       # CloudWatch JSON / local text logging
├── ai/
│   ├── categorizer.py      # Claude API integration (tool_use for structured output)
│   └── prompts.py          # System/user prompts
├── gmail/
│   ├── client.py           # Gmail API with pagination
│   ├── token_manager.py    # OAuth token refresh via AWS SSM
│   └── thread_grouper.py   # Thread/sender grouping
├── notifications/
│   └── slack.py            # Bot Token API (DMs via conversations.open)
├── report/
│   ├── generator.py        # Markdown report writer
│   └── slack_formatter.py  # Block Kit formatting
└── utils/
    ├── errors.py           # Custom exceptions
    ├── rate_limiter.py     # Token-bucket rate limiting
    └── batch_processor.py  # Batch processing with graceful degradation
scripts/
├── setup_oauth.py          # Gmail OAuth2 flow (generates refresh token)
├── test_local.py           # Local end-to-end test runner
└── upload_tokens_to_ssm.py # Push credentials to AWS SSM Parameter Store
```

## Setup

### Prerequisites

- Python 3.12+
- A Google Workspace / Gmail account
- An Anthropic account (API key or Claude CLI `setup-token`)
- A Slack workspace with a bot app
- AWS account (for Lambda deployment)
- Node.js (for Serverless Framework)

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Gmail OAuth

Create OAuth credentials in the [Google Cloud Console](https://console.cloud.google.com/apis/credentials) (Desktop app type), download the JSON, and place it in `config/`:

```bash
mkdir -p config
# Move your client_secret_*.json into config/
python scripts/setup_oauth.py
```

This opens a browser for OAuth consent and saves your refresh token.

### 3. Anthropic auth

Pick one:

- **Claude CLI OAuth** (recommended, lasts 1 year):
  ```bash
  claude setup-token
  ```
  Copy the token into `CLAUDE_CODE_OAUTH_TOKEN` in your `.env`.

- **API key**: Get one from [console.anthropic.com](https://console.anthropic.com) and set `ANTHROPIC_API_KEY` in your `.env`.

### 4. Slack bot

1. Create an app at [api.slack.com/apps](https://api.slack.com/apps)
2. Add **Bot Token Scopes**: `im:write`, `chat:write`, `im:read`, `im:history`
3. Install the app to your workspace
4. Copy the Bot Token (`xoxb-...`) and Signing Secret to your `.env`
5. Get your Slack User ID (profile → three dots → Copy member ID)

### 5. Configure

```bash
cp .env.example .env
# Fill in your credentials
```

See `config.yaml` for tunable settings (model, batch size, rate limits, etc).

## Usage

### Test locally

```bash
# Full pipeline: Gmail → AI → Slack DM
python scripts/test_local.py

# Skip Gmail (use fake emails)
python scripts/test_local.py --skip-gmail

# Skip AI (just test Gmail connection)
python scripts/test_local.py --skip-ai

# Skip Slack (terminal output only)
python scripts/test_local.py --skip-slack
```

### Deploy to AWS

Upload credentials to SSM:

```bash
python scripts/upload_tokens_to_ssm.py
```

Deploy with Serverless Framework:

```bash
npm install
npx serverless deploy
```

The function runs every hour via CloudWatch Events. Logs go to CloudWatch with configurable log level.

## Configuration

Key settings in `config.yaml`:

| Setting | Default | Description |
|---------|---------|-------------|
| `ai.model` | `claude-sonnet-4-5-20250929` | Claude model to use |
| `ai.batch_size` | `10` | Emails per AI request |
| `gmail.query` | `has:nouserlabels newer_than:2h` | Gmail search filter |
| `gmail.max_total_emails` | `500` | Max emails per run |
| `slack.include_reply_drafts` | `true` | Show suggested replies in digest |
| `logging.level` | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `logging.format` | `json` | `json` for CloudWatch, `text` for local |
