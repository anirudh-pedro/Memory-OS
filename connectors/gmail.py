from composio import Composio
from models.memory import Email
from storage.db import insert_email, get_connection

import sys

def sync_gmail():
    try:
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
            
        c = Composio()
        s = c.create(user_id="user_123")
        
        # Verify connection
        toolkits_info = s.toolkits()
        gmail_tk = next((t for t in toolkits_info.items if t.slug == "gmail"), None)
        if not gmail_tk or not (gmail_tk.connection and gmail_tk.connection.is_active):
            print("Gmail connection not active.")
            return

        # Fetch emails
        resp = s.execute(tool_slug="gmail_fetch_emails", arguments={"max_results": 50, "include_payload": True})
        if not resp or resp.error or not resp.data:
            print("No emails found.")
            return

        emails = resp.data.get("messages", [])
        if not emails:
            # Check response_data structure just in case
            emails = resp.data.get("response_data", {}).get("messages", [])
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
