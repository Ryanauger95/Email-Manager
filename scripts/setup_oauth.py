"""One-time script to perform Gmail OAuth2 consent flow.

Run locally on a machine with a browser. Produces the refresh_token
needed for Lambda deployment.

Prerequisites:
1. Place your OAuth client secret JSON in the config/ directory
2. Enable the Gmail API in your Google Cloud project
3. IMPORTANT: Set the app publishing status to "Production" in
   OAuth consent screen to avoid 7-day token expiration

Usage:
    pip install google-auth-oauthlib
    python scripts/setup_oauth.py
"""

import sys
from pathlib import Path

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("Error: google-auth-oauthlib is required.")
    print("Install with: pip install google-auth-oauthlib")
    sys.exit(1)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CONFIG_DIR = Path(__file__).parent.parent / "config"


def find_client_secret() -> Path:
    """Find the client secret JSON file in the config/ directory."""
    json_files = list(CONFIG_DIR.glob("client_secret*.json"))
    if not json_files:
        print(f"Error: No client_secret*.json file found in {CONFIG_DIR}")
        print("Download it from Google Cloud Console -> APIs & Services -> Credentials")
        sys.exit(1)
    if len(json_files) > 1:
        print(f"Found multiple client secret files in {CONFIG_DIR}:")
        for f in json_files:
            print(f"  - {f.name}")
        print("Using the first one.")
    return json_files[0]


def main() -> None:
    print("Gmail OAuth2 Setup")
    print("=" * 50)

    client_secret_path = find_client_secret()
    print(f"\nUsing credentials from: {client_secret_path.name}")

    print("\nStarting OAuth consent flow...")
    print("A browser window will open. Sign in and grant Gmail read access.\n")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secret_path),
        SCOPES,
    )
    creds = flow.run_local_server(
        port=8080,
        access_type="offline",
        prompt="consent",
    )

    print("\n" + "=" * 60)
    print("OAuth setup complete! Save these values:\n")
    print(f"  GMAIL_CLIENT_ID={creds.client_id}")
    print(f"  GMAIL_CLIENT_SECRET={creds.client_secret}")
    print(f"  GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print("\n" + "=" * 60)
    print("\nNext steps:")
    print("  1. Add these to your .env file for local testing")
    print("  2. Run: python scripts/upload_tokens_to_ssm.py  (for Lambda deployment)")
    print("\nWARNING: If your Google Cloud app is in 'Testing' mode,")
    print("the refresh token will expire after 7 days. Move to 'Production'")
    print("publishing status to avoid this.")


if __name__ == "__main__":
    main()
