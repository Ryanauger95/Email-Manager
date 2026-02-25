"""Upload credentials to AWS SSM Parameter Store.

Run after setup_oauth.py to store credentials securely for Lambda.

Usage:
    python scripts/upload_tokens_to_ssm.py

You will be prompted for each secret value interactively.
Requires AWS CLI configured with appropriate IAM permissions.
"""

import sys
from getpass import getpass

try:
    import boto3
except ImportError:
    print("Error: boto3 is required. Install with: pip install boto3")
    sys.exit(1)


GMAIL_PARAMETERS = [
    {
        "name": "/email-manager/gmail/client-id",
        "prompt": "Gmail OAuth Client ID",
        "secret": False,
    },
    {
        "name": "/email-manager/gmail/client-secret",
        "prompt": "Gmail OAuth Client Secret",
        "secret": True,
    },
    {
        "name": "/email-manager/gmail/refresh-token",
        "prompt": "Gmail OAuth Refresh Token",
        "secret": True,
    },
]

SLACK_PARAMETERS = [
    {
        "name": "/email-manager/slack/bot-token",
        "prompt": "Slack Bot Token (xoxb-...)",
        "secret": True,
    },
    {
        "name": "/email-manager/slack/signing-secret",
        "prompt": "Slack Signing Secret",
        "secret": True,
    },
    {
        "name": "/email-manager/slack/user-id",
        "prompt": "Your Slack User ID (U0XXXXXXXXX)",
        "secret": False,
    },
]


def main() -> None:
    ssm = boto3.client("ssm")

    print("Upload credentials to AWS SSM Parameter Store")
    print("=" * 50)
    print()

    # Anthropic auth — choose one
    print("  Anthropic Authentication (choose one):")
    print("    1. OAuth token from Claude CLI (run: claude setup-token)")
    print("    2. API key from console.anthropic.com")
    choice = input("  Enter 1 or 2: ").strip()

    if choice == "1":
        anthropic_params = [{
            "name": "/email-manager/anthropic/oauth-token",
            "prompt": "Claude OAuth Token (from: claude setup-token)",
            "secret": True,
        }]
    else:
        anthropic_params = [{
            "name": "/email-manager/anthropic/api-key",
            "prompt": "Anthropic API Key (sk-ant-...)",
            "secret": True,
        }]

    print()
    PARAMETERS = GMAIL_PARAMETERS + anthropic_params + SLACK_PARAMETERS

    for param in PARAMETERS:
        if param["secret"]:
            value = getpass(f"  {param['prompt']}: ")
        else:
            value = input(f"  {param['prompt']}: ")

        if not value.strip():
            print(f"  Skipping {param['name']} (empty value)")
            continue

        try:
            ssm.put_parameter(
                Name=param["name"],
                Value=value.strip(),
                Type="SecureString" if param["secret"] else "String",
                Overwrite=True,
            )
            print(f"  -> Stored {param['name']}")
        except Exception as e:
            print(f"  -> FAILED to store {param['name']}: {e}")
            sys.exit(1)

    print()
    print("All credentials stored successfully!")
    print("You can now deploy with: serverless deploy")


if __name__ == "__main__":
    main()
