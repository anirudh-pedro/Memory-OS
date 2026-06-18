STATE_CHANGING_TOOLS = {
    "github_create_an_issue", "GITHUB_CREATE_AN_ISSUE",
    "github_create_a_repository_for_the_authenticated_user", "GITHUB_CREATE_A_REPOSITORY_FOR_THE_AUTHENTICATED_USER",
    "googlecalendar_create_event", "GOOGLECALENDAR_CREATE_EVENT",
    "googlecalendar_quick_add", "GOOGLECALENDAR_QUICK_ADD",
    "notion_create_notion_page", "NOTION_CREATE_NOTION_PAGE",
    "notion_append_text_blocks", "NOTION_APPEND_TEXT_BLOCKS",
    "gmail_send_email", "GMAIL_SEND_EMAIL"
}

ACTION_MAPPINGS = {
    "github_create_an_issue": "Create a GitHub issue",
    "GITHUB_CREATE_AN_ISSUE": "Create a GitHub issue",
    "github_create_a_repository_for_the_authenticated_user": "Create a GitHub repository",
    "GITHUB_CREATE_A_REPOSITORY_FOR_THE_AUTHENTICATED_USER": "Create a GitHub repository",
    "notion_create_notion_page": "Create a Notion page",
    "NOTION_CREATE_NOTION_PAGE": "Create a Notion page",
    "googlecalendar_create_event": "Create a Calendar event",
    "GOOGLECALENDAR_CREATE_EVENT": "Create a Calendar event",
    "googlecalendar_quick_add": "Quick add a Calendar event",
    "GOOGLECALENDAR_QUICK_ADD": "Quick add a Calendar event",
    "gmail_send_email": "Send an email",
    "GMAIL_SEND_EMAIL": "Send an email",
    "notion_append_text_blocks": "Append content to Notion page",
    "NOTION_APPEND_TEXT_BLOCKS": "Append content to Notion page"
}

def get_action_description(tool_name: str) -> str:
    return ACTION_MAPPINGS.get(tool_name, f"Execute {tool_name}")
