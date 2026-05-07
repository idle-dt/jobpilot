"""Gmail API service wrapper."""

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class GmailClient:
    """Thin wrapper around the Gmail API service."""

    def __init__(self, credentials: Credentials):
        self.service = build("gmail", "v1", credentials=credentials)

    def list_messages(self, query: str, max_results: int = 100) -> list[dict]:
        """List message IDs matching a Gmail search query."""
        messages = []
        page_token = None

        while True:
            results = self.service.users().messages().list(
                userId="me",
                q=query,
                pageToken=page_token,
                maxResults=min(max_results - len(messages), 100),
            ).execute()

            if "messages" in results:
                messages.extend(results["messages"])

            page_token = results.get("nextPageToken")
            if not page_token or len(messages) >= max_results:
                break

        return messages[:max_results]

    def get_message(self, message_id: str) -> dict:
        """Fetch a full message by ID."""
        return self.service.users().messages().get(
            userId="me",
            id=message_id,
            format="full",
        ).execute()

    def apply_label(self, message_id: str, label_id: str) -> None:
        """Add a label to a message."""
        self.service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()

    def get_or_create_label(self, label_name: str) -> str:
        """Get a label ID by name, creating it if it doesn't exist."""
        results = self.service.users().labels().list(userId="me").execute()
        for label in results.get("labels", []):
            if label["name"] == label_name:
                return label["id"]

        created = self.service.users().labels().create(
            userId="me",
            body={
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        ).execute()
        return created["id"]
