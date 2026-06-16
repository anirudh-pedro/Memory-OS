import logging
from memory.memory_manager import WorkspaceCacheRepository

logger = logging.getLogger(__name__)

def sync_calendar(session, cache_repo: WorkspaceCacheRepository) -> int:
    """Sync Google Calendar lists/events and save to local workspace cache. Returns count of synced items."""
    logger.info("Starting Google Calendar sync...")
    try:
        # Call GOOGLECALENDAR_LIST_CALENDARS
        response = session.execute(
            tool_slug="googlecalendar_list_calendars",
            arguments={}
        )
        
        if not response or response.error:
            logger.error(f"Google Calendar sync API error: {response.error if response else 'No response'}")
            return 0
            
        data = response.data or {}
        calendars = data.get("calendars", [])
        if not isinstance(calendars, list):
            calendars = data.get("items", [])
            if not isinstance(calendars, list):
                calendars = []

        count = 0
        for cal in calendars:
            if not isinstance(cal, dict):
                continue
            cal_id = str(cal.get("id", ""))
            summary = cal.get("summary", "No Summary")
            description = cal.get("description", "")
            time_zone = cal.get("timeZone", "")
            access_role = cal.get("accessRole", "")
            
            content = f"Calendar: {summary}\nID: {cal_id}\nRole: {access_role}\nTimezone: {time_zone}\nDescription: {description}"
            
            success = cache_repo.upsert_cache(
                source_app="googlecalendar",
                external_id=cal_id,
                title=f"[Calendar] {summary}",
                content=content,
                metadata=cal
            )
            if success:
                count += 1
                
        logger.info(f"Successfully synced {count} calendars from Google Calendar.")
        return count
    except Exception as e:
        logger.error(f"Failed to sync Google Calendar: {e}")
        return 0
