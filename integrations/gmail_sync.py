import logging
from memory.memory_manager import WorkspaceCacheRepository

logger = logging.getLogger(__name__)

def sync_gmail(session, cache_repo: WorkspaceCacheRepository) -> int:
    """Sync Gmail recent messages and save to local workspace cache. Returns count of synced items."""
    logger.info("Starting Gmail sync...")
    try:
        # Check connection first
        toolkits_info = session.toolkits()
        gmail_tk = next((t for t in toolkits_info.items if t.slug == "gmail"), None)
        if not gmail_tk or not (gmail_tk.connection and gmail_tk.connection.is_active):
            logger.warning("Gmail connection is not active. Skipping Gmail sync.")
            return 0

        # Call GMAIL_FETCH_EMAILS
        response = session.execute(
            tool_slug="gmail_fetch_emails",
            arguments={"max_results": 5, "include_payload": True}
        )
        
        if not response or response.error:
            logger.error(f"Gmail sync API error: {response.error if response else 'No response'}")
            return 0
            
        data = response.data or {}
        emails = data.get("messages", [])
        if not isinstance(emails, list):
            emails = data.get("response_data", {}).get("messages", [])
            if not isinstance(emails, list):
                emails = []

        count = 0
        for email in emails:
            if not isinstance(email, dict):
                continue
            msg_id = str(email.get("messageId", ""))
            if not msg_id:
                msg_id = str(email.get("id", ""))
                
            subject = email.get("subject", "No Subject")
            sender = email.get("sender", "") or email.get("from", "")
            date = email.get("date", "")
            body = email.get("body", "") or email.get("snippet", "")
            
            content = f"From: {sender}\nDate: {date}\nSubject: {subject}\n\n{body}"
            
            success = cache_repo.upsert_cache(
                source_app="gmail",
                external_id=msg_id,
                title=subject,
                content=content,
                metadata=email
            )
            if success:
                count += 1
                
        logger.info(f"Successfully synced {count} emails from Gmail.")
        return count
    except Exception as e:
        logger.error(f"Failed to sync Gmail: {e}")
        return 0
