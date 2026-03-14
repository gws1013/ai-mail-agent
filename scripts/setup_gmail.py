"""Gmail OAuth setup script.
Run this once to authorize the application and generate token.json.
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


def setup():
    """Run OAuth flow and save credentials."""
    credentials_path = os.getenv("GMAIL_CREDENTIALS_PATH", "./credentials/credentials.json")
    token_path = os.getenv("GMAIL_TOKEN_PATH", "./credentials/token.json")

    if not Path(credentials_path).exists():
        print(f"Error: {credentials_path} not found.")
        print("Download OAuth credentials from Google Cloud Console:")
        print("1. Go to https://console.cloud.google.com/apis/credentials")
        print("2. Create OAuth 2.0 Client ID (Desktop application)")
        print("3. Download JSON and save as credentials/credentials.json")
        sys.exit(1)

    # Check if token already exists
    if Path(token_path).exists():
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if creds and creds.valid:
            print("Token already exists and is valid.")
            return
        print("Token exists but is invalid. Re-authenticating...")

    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
    creds = flow.run_local_server(port=0)

    # Save token
    Path(token_path).parent.mkdir(parents=True, exist_ok=True)
    with open(token_path, "w") as f:
        f.write(creds.to_json())

    print(f"Token saved to {token_path}")
    print("Gmail OAuth setup complete!")


if __name__ == "__main__":
    setup()
