import logging
from typing import List
from connectors.base import BaseConnector
from core.models import Memory

logger = logging.getLogger(__name__)

class NotionConnector(BaseConnector):
    def sync(self, session) -> List[Memory]:
        """Fetch and normalize Notion data (pages/databases/users) into Memory objects."""
        logger.info("Starting Notion memory sync...")
        memories = []
        
        # 1. Search pages and databases
        try:
            search_response = session.execute(
                tool_slug="notion_search_notion_page",
                arguments={}
            )
            
            if search_response and not search_response.error:
                data = search_response.data or {}
                results = data.get("results", [])
                if not isinstance(results, list):
                    results = data.get("response_data", {}).get("results", [])
                    if not isinstance(results, list):
                        results = []
                        
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    page_id = str(item.get("id", ""))
                    obj_type = item.get("object", "page")
                    
                    # Extract title
                    title = "Untitled"
                    properties = item.get("properties", {})
                    for prop_name, prop_val in properties.items():
                        if isinstance(prop_val, dict) and prop_val.get("type") == "title":
                            title_list = prop_val.get("title", [])
                            if title_list:
                                title = "".join([t.get("plain_text", "") for t in title_list])
                                break
                                
                    if title == "Untitled":
                        title_list = item.get("title", [])
                        if isinstance(title_list, list) and title_list:
                            title = "".join([t.get("plain_text", "") for t in title_list])

                    url = item.get("url", "")
                    content = f"Notion {obj_type.capitalize()}: {title}\nURL: {url}"
                    
                    memories.append(
                        Memory(
                            source_app="notion",
                            external_id=page_id,
                            title=f"[{obj_type.capitalize()}] {title}",
                            content=content,
                            metadata_json=item
                        )
                    )
            else:
                err_msg = search_response.error if search_response else "No response"
                logger.error(f"Notion page search API error: {err_msg}")
        except Exception as e:
            logger.error(f"Failed to sync Notion pages: {e}")

        # 2. List workspace users
        try:
            users_response = session.execute(
                tool_slug="notion_list_users",
                arguments={}
            )
            
            if users_response and not users_response.error:
                data = users_response.data or {}
                results = data.get("response_data", {}).get("results", [])
                if not isinstance(results, list):
                    results = data.get("results", [])
                    if not isinstance(results, list):
                        results = []
                        
                for user in results:
                    if not isinstance(user, dict):
                        continue
                    user_id = str(user.get("id", ""))
                    name = user.get("name", "Unknown User")
                    user_type = user.get("type", "person")
                    email = user.get("person", {}).get("email", "")
                    
                    content = f"Notion User: {name}\nType: {user_type}\nEmail: {email}"
                    memories.append(
                        Memory(
                            source_app="notion",
                            external_id=f"user_{user_id}",
                            title=f"[User] {name}",
                            content=content,
                            metadata_json=user
                        )
                    )
            else:
                err_msg = users_response.error if users_response else "No response"
                logger.error(f"Notion user list API error: {err_msg}")
        except Exception as e:
            logger.error(f"Failed to sync Notion users: {e}")
                        
        logger.info(f"Successfully normalized {len(memories)} Notion memories.")
        return memories
