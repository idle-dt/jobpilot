#!/usr/bin/env python3
"""Interactive Gmail OAuth setup for JobPilot."""

import sys
from pathlib import Path

# Add src to path so we can import jobpilot
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jobpilot.config import settings
from jobpilot.gmail.auth import GmailAuth


def main():
    print("=" * 50)
    print("  JobPilot — Gmail Setup")
    print("=" * 50)
    print()

    creds_path = settings.gmail_credentials_path
    token_path = settings.gmail_token_path

    if not creds_path.exists():
        print(f"ERROR: credentials.json not found at {creds_path}")
        print()
        print("To fix this:")
        print("1. Go to console.cloud.google.com")
        print("2. Create OAuth 2.0 Desktop credentials")
        print("3. Download the JSON file")
        print(f"4. Save it as: {creds_path}")
        sys.exit(1)

    print(f"Found credentials at: {creds_path}")

    auth = GmailAuth(creds_path, token_path)

    if auth.is_authenticated():
        print("Already authenticated! Token is valid.")
        print(f"Token stored at: {token_path}")
        return

    print()
    print("Opening browser for Google authentication...")
    print("Grant Gmail access when prompted.")
    print()

    try:
        creds = auth.get_credentials()
        print()
        print("Authentication successful!")
        print(f"Token saved to: {token_path}")
    except Exception as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
