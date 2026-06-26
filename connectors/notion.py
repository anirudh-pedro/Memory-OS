import sys
from datetime import datetime
from composio import Composio
from models.memory import RepositoryDocument
from storage.db import insert_repository_document, get_connection

def get_page_title(page: dict) -> str:
    properties = page.get("properties", {}) or {}
    # Title is usually in 'title' field or 'Name' field
    title_text = ""
    for field_name in ["title", "Name", "name"]:
        prop = properties.get(field_name)
        if isinstance(prop, dict):
            title_list = prop.get("title") or prop.get("rich_text") or []
            if isinstance(title_list, list) and title_list:
                title_text = "".join([t.get("plain_text", "") for t in title_list if isinstance(t, dict)])
                if title_text:
                    break
    if not title_text:
        title_text = f"Notion Page {page.get('id')}"
    return title_text

def sync_notion():
    try:
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

        print("Syncing Notion...\n")
        c = Composio()
        s = c.create(user_id="user_123")

        # Verify Notion toolkit is active
        toolkits_info = s.toolkits()
        notion_tk = next((t for t in toolkits_info.items if t.slug == "notion"), None)
        if not notion_tk or not (notion_tk.connection and notion_tk.connection.is_active):
            print("Notion connection not active.")
            return

        # Fetch page list via Composio
        resp = s.execute(tool_slug="notion_search_notion_page", arguments={"query": ""})
        if resp.error or not resp.data:
            print("No Notion pages found.")
            return

        resp_data = resp.data
        if "response_data" in resp_data:
            resp_data = resp_data["response_data"]

        pages = resp_data.get("results") or []
        if not pages:
            print("No Notion pages found in results.")
            return

        print(f"Found {len(pages)} Notion pages")

        conn = get_connection()
        cursor = conn.cursor()

        synced_count = 0
        skipped_count = 0

        for page in pages:
            if not isinstance(page, dict):
                continue
            
            page_id = page.get("id")
            if not page_id:
                continue

            title = get_page_title(page)
            last_edited_time = page.get("last_edited_time") or ""

            # Incremental check: check if already in DB with same last_edited_time
            cursor.execute(
                "SELECT content, synced_at FROM repository_documents WHERE repo_name = 'Notion' AND file_name = ?",
                (title,)
            )
            row = cursor.fetchone()
            if row:
                stored_synced_at = row[1]
                # If we have stored it and it wasn't edited since our last sync, skip it
                if stored_synced_at and last_edited_time and stored_synced_at >= last_edited_time:
                    skipped_count += 1
                    continue

            # Fetch page content
            try:
                print(f"Syncing page: {title}")
                resp_content = s.execute(
                    tool_slug="notion_get_page_markdown",
                    arguments={"page_id": page_id}
                )
                if resp_content and not resp_content.error and resp_content.data:
                    content_data = resp_content.data
                    if "response_data" in content_data:
                        content_data = content_data["response_data"]
                    
                    markdown = content_data.get("markdown") or ""
                    if markdown.strip():
                        # Save to database
                        doc = RepositoryDocument(
                            repo_name="Notion",
                            file_name=title,
                            content=markdown,
                            source="notion_get_page_markdown",
                            synced_at=datetime.now().isoformat()
                        )
                        insert_repository_document(doc)
                        synced_count += 1
                    else:
                        print(f"Page '{title}' content was empty.")
                else:
                    print(f"Failed to fetch content for page: {title}")
            except Exception as e:
                print(f"Error fetching page content for '{title}': {e}")

        conn.close()
        print(f"Notion Sync Complete: {synced_count} pages synced, {skipped_count} pages skipped.")

    except Exception as e:
        print(f"Error during Notion sync: {e}")
