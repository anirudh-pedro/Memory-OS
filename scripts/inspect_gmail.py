import sqlite3
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

db_path = "memory.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("--- Synced Account Details ---")

# 1. GitHub
cursor.execute("SELECT title, content FROM workspace_cache WHERE source_app = 'github' AND title LIKE '[GitHub User]%' LIMIT 1")
github_row = cursor.fetchone()
if github_row:
    print(f"GitHub: {github_row['title']} -> {github_row['content'].replace('\n', ', ')}")
else:
    cursor.execute("SELECT title FROM workspace_cache WHERE source_app = 'github' AND title LIKE '[GitHub Repo]%' LIMIT 1")
    repo_row = cursor.fetchone()
    if repo_row:
        print(f"GitHub: Associated repository owner matches: {repo_row['title']}")
    else:
        print("GitHub: No profile cache found.")

# 2. Gmail
cursor.execute("SELECT title, content, metadata_json FROM workspace_cache WHERE source_app = 'gmail' LIMIT 1")
gmail_row = cursor.fetchone()
if gmail_row:
    try:
        meta = json.loads(gmail_row['metadata_json'] or "{}")
        print(f"Gmail: {meta.get('to') or 'anirudh200503@gmail.com'}")
    except:
        print("Gmail: anirudh200503@gmail.com")
else:
    print("Gmail: No emails found in cache.")

# 3. Google Calendar
cursor.execute("SELECT title, content FROM workspace_cache WHERE source_app = 'googlecalendar' LIMIT 1")
cal_row = cursor.fetchone()
if cal_row:
    print(f"Google Calendar: {cal_row['title']} -> {cal_row['content'].replace('\n', ', ')}")
else:
    print("Google Calendar: No calendar found in cache.")

# 4. Notion
cursor.execute("SELECT title, content FROM workspace_cache WHERE source_app = 'notion' AND title LIKE '[User]%' LIMIT 1")
notion_row = cursor.fetchone()
if notion_row:
    print(f"Notion User: {notion_row['title']} -> {notion_row['content'].replace('\n', ', ')}")
else:
    cursor.execute("SELECT title, content FROM workspace_cache WHERE source_app = 'notion' LIMIT 1")
    any_notion = cursor.fetchone()
    if any_notion:
        print(f"Notion Workspace item: {any_notion['title']}")
    else:
        print("Notion: No Notion user found in cache.")

conn.close()
