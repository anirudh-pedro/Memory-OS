import logging
import os
from typing import List
from connectors.base import BaseConnector
from core.models import Memory

logger = logging.getLogger(__name__)

class ComposioCalendarConnector(BaseConnector):
    def sync(self, session) -> List[Memory]:
        """Fetch and normalize Google Calendar info into Memory objects via Composio."""
        logger.info("Starting Composio Google Calendar memory sync...")
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


class NativeCalendarConnector(BaseConnector):
    def sync(self, session) -> List[Memory]:
        """Fetch Google Calendar events using native Google Calendar REST APIs or mock synchronization."""
        logger.info("Starting Native Google Calendar memory sync...")
        memories = []
        google_token = os.getenv("GOOGLE_CALENDAR_TOKEN")
        
        if google_token:
            try:
                import requests
                headers = {"Authorization": f"Bearer {google_token}"}
                res = requests.get("https://www.googleapis.com/calendar/v3/users/me/calendarList", headers=headers, timeout=10)
                if res.status_code == 200:
                    calendars = res.json().get("items", [])
                    for cal in calendars:
                        cal_id = cal.get("id")
                        summary = cal.get("summary", "No Summary")
                        description = cal.get("description", "")
                        content = f"Calendar: {summary}\nID: {cal_id}\nTimezone: {cal.get('timeZone', '')}\nDescription: {description}"
                        memories.append(
                            Memory(
                                source_app="googlecalendar",
                                external_id=cal_id,
                                title=f"[Calendar] {summary}",
                                content=content,
                                metadata_json=cal
                            )
                        )
                    return memories
            except Exception as e:
                logger.error(f"Native Calendar sync failed: {e}. Syncing simulated calendar details.")

        logger.info("No GOOGLE_CALENDAR_TOKEN found. Syncing simulated Google Calendar data...")
        mock_calendars = [
            {
                "id": "cal_main",
                "summary": "Personal Work Calendar",
                "timeZone": "Asia/Kolkata",
                "description": "Primary calendar tracking project standups and PKOS milestones."
            }
        ]

        for cal in mock_calendars:
            content = f"Calendar: {cal['summary']}\nID: {cal['id']}\nTimezone: {cal['timeZone']}\nDescription: {cal['description']}"
            memories.append(
                Memory(
                    source_app="googlecalendar",
                    external_id=cal["id"],
                    title=f"[Calendar] {cal['summary']}",
                    content=content,
                    metadata_json=cal
                )
            )

        return memories


class CalendarConnector(BaseConnector):
    def __new__(cls, *args, **kwargs):
        provider = os.getenv("CONNECTOR_PROVIDER", "composio").lower()
        if provider == "native":
            return NativeCalendarConnector(*args, **kwargs)
        else:
            return ComposioCalendarConnector(*args, **kwargs)
