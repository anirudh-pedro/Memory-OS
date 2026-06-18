import logging
from typing import List
from connectors.base import BaseConnector
from core.models import Memory

logger = logging.getLogger(__name__)

class CalendarConnector(BaseConnector):
    def sync(self, session) -> List[Memory]:
        """Fetch and normalize Google Calendar info into Memory objects."""
        logger.info("Starting Google Calendar memory sync...")
        memories = []
        
        try:
            response = session.execute(
                tool_slug="googlecalendar_list_calendars",
                arguments={}
            )
            
            if not response or response.error:
                logger.error(f"Google Calendar sync API error: {response.error if response else 'No response'}")
                return []
                
            data = response.data or {}
            calendars = data.get("calendars", [])
            if not isinstance(calendars, list):
                calendars = data.get("items", [])
                if not isinstance(calendars, list):
                    calendars = []

            for cal in calendars:
                if not isinstance(cal, dict):
                    continue
                cal_id = str(cal.get("id", ""))
                summary = cal.get("summary", "No Summary")
                description = cal.get("description", "")
                time_zone = cal.get("timeZone", "")
                access_role = cal.get("accessRole", "")
                
                content = f"Calendar: {summary}\nID: {cal_id}\nRole: {access_role}\nTimezone: {time_zone}\nDescription: {description}"
                
                memories.append(
                    Memory(
                        source_app="googlecalendar",
                        external_id=cal_id,
                        title=f"[Calendar] {summary}",
                        content=content,
                        metadata_json=cal
                    )
                )
        except Exception as e:
            logger.error(f"Failed to sync Google Calendar: {e}")
            
        logger.info(f"Successfully normalized {len(memories)} Calendar memories.")
        return memories
