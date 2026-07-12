from composio import Composio
from models.memory import Email
from storage.db import insert_email, get_connection

import os
import sys

def sync_gmail():
    try:
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
            
        c = Composio()
        user_id = os.getenv("COMPOSIO_USER_ID", "user_123")
        s = c.create(user_id=user_id)
        
        # Verify connection
        toolkits_info = s.toolkits()
        gmail_tk = next((t for t in toolkits_info.items if t.slug == "gmail"), None)
        if not gmail_tk or not (gmail_tk.connection and gmail_tk.connection.is_active):
            print("Gmail connection not active.")
            return

        # Determine last fetched date from stored emails to optimize retrieval query
        query = ""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(received_at) FROM emails WHERE received_at IS NOT NULL AND received_at != ''")
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                import re
                m = re.match(r"(\d{4})[-/](\d{2})[-/](\d{2})", row[0])
                if m:
                    query = f"after:{m.group(1)}/{m.group(2)}/{m.group(3)}"
        except Exception as e:
            import logging
            logging.getLogger("gmail").warning(f"Failed to query last fetched date from SQLite: {e}")

        # Fetch emails with pagination
        emails = []
        page_token = None
        while True:
            args = {"max_results": 100, "include_payload": True}
            if query:
                args["q"] = query
            if page_token:
                args["page_token"] = page_token

            resp = s.execute(tool_slug="gmail_fetch_emails", arguments=args)
            if not resp or resp.error or not resp.data:
                break

            page_emails = resp.data.get("messages", [])
            if not page_emails:
                page_emails = resp.data.get("response_data", {}).get("messages", [])

            if not page_emails:
                break

            emails.extend(page_emails)
            page_token = resp.data.get("nextPageToken")
            if not page_token:
                break

            # Safety check: avoid infinite loops if user has thousands of new emails
            if len(emails) >= 500:
                break

        if not emails:
            print("No emails found.")
            return

        print(f"Found {len(emails)} emails")
        
        conn = get_connection()
        cursor = conn.cursor()
        
        synced_count = 0
        skipped_count = 0

        for email in emails:
            message_id = email.get("id") or email.get("messageId") or email.get("threadId") or ""
            
            # Check if email is already in SQLite
            if message_id:
                cursor.execute("SELECT id FROM emails WHERE message_id = ?", (message_id,))
                if cursor.fetchone():
                    skipped_count += 1
                    continue
            
            subject = email.get("subject") or "No Subject"
            sender = email.get("sender") or email.get("from") or "Unknown Sender"
            snippet = email.get("messageText") or email.get("snippet") or ""
            received_at = email.get("messageTimestamp") or ""
            date_str = received_at[:10] if len(received_at) >= 10 else received_at

            # Save to SQLite
            db_email = Email(
                message_id=message_id,
                subject=subject,
                sender=sender,
                snippet=snippet,
                received_at=received_at
            )
            insert_email(db_email)
            synced_count += 1

            # Print to terminal
            print("--------------------------------------------------")
            print(f"Subject: {subject}")
            print(f"From: {sender}")
            print(f"Date: {date_str}")
            print("--------------------------------------------------")
        
        conn.close()
        print(f"Gmail Sync Complete: {synced_count} emails synced, {skipped_count} emails skipped.")
            
    except Exception as e:
        print(f"Error during Gmail sync: {e}")


from connectors.base import BaseConnector
from connectors.registry import register

@register
class GmailConnector(BaseConnector):
    name = "Gmail"
    slug = "gmail"

    def authenticate(self) -> bool:
        try:
            c = Composio()
            user_id = os.getenv("COMPOSIO_USER_ID", "user_123")
            s = c.create(user_id=user_id)
            toolkits_info = s.toolkits()
            tk = next((t for t in toolkits_info.items if t.slug == "gmail"), None)
            return bool(tk and tk.connection and tk.connection.is_active)
        except Exception:
            return False

    def sync(self) -> dict:
        sync_gmail()
        return {"status": "success"}

    def health(self) -> tuple[bool, str]:
        if self.authenticate():
            return True, "Connected"
        return False, "Not connected"

