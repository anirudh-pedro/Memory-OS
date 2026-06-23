# Composio Integrations

Memory-OS relies heavily on [Composio](https://composio.dev/) to securely manage OAuth authentications and interface with external APIs. All connectors are defined in the `connectors/` directory and inherit from `BaseConnector`.

## Supported Connectors

### 1. GitHub (`connectors/github.py`)
*   **Purpose**: Syncs software development metadata.
*   **Fetches**: Authenticated user profile, Repositories, README files, Issues, and Pull Requests.
*   **Enabled Tools**: `GITHUB_GET_THE_AUTHENTICATED_USER`, `GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER`, `GITHUB_GET_A_REPOSITORY_README`, `GITHUB_LIST_REPOSITORY_ISSUES`, `GITHUB_LIST_PULL_REQUESTS`.

### 2. Gmail (`connectors/gmail.py`)
*   **Purpose**: Syncs communication context.
*   **Fetches**: Recent emails (extracting sender, recipient, subject, and body).
*   **Enabled Tools**: `GMAIL_FETCH_EMAILS`.

### 3. Notion (`connectors/notion.py`)
*   **Purpose**: Syncs workspace documentation.
*   **Fetches**: Workspace users and pages/documents.
*   **Enabled Tools**: `NOTION_LIST_USERS`, `NOTION_SEARCH_NOTION_PAGE`.

### 4. Google Calendar (`connectors/calendar.py`)
*   **Purpose**: Syncs scheduling and event data.
*   **Fetches**: Calendar lists and upcoming events.
*   **Enabled Tools**: `GOOGLECALENDAR_LIST_CALENDARS`.

## Authentication Flow

If a connection token expires or is not present, `main.py` detects this on startup via `ensure_connections()`. It generates a Composio redirect URL, prompting the user to complete the OAuth flow in their browser before continuing.
