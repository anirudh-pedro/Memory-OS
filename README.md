# Memory-OS 🧠

Memory-OS is a stateful, AI-powered personal assistant agent designed to connect your primary productivity platforms—**GitHub**, **Google Calendar**, and **Notion**—and orchestrate them through a single command-line interface. It features both short-term conversational context and a persistent long-term memory database.

---

## ✨ Features

- **🗣️ Interactive CLI Chat Loop:** A real-time chat interface with structured, clean output formatting.
- **💾 Short-Term Conversational Memory:** Powered by LangGraph's `SqliteSaver` checkpointer. Conversational threads are persisted across system restarts.
- **🧠 Long-Term Semantic Memory (RAG):** Saves facts and user preferences (e.g. favorite programming languages, project repositories, birthdates) into a persistent database, letting the agent recall them in future sessions.
- **🔄 Multi-Session Support:** Start, switch, or isolate different conversations using custom session IDs.
- **⚙️ Integrated Productivity Toolkits:**
  * **GitHub:** Read profile details, create public/private repositories, and open issue tickets.
  * **Google Calendar:** List calendar directories, create events, and quick-add appointments.
  * **Notion:** List workspace members, create documents/pages, and append block content.

---

## 🛠️ Commands

While interacting with Memory-OS, you can issue the following control commands directly in the prompt:

| Command | Action |
| :--- | :--- |
| `/session <id>` | Switch to or create a different conversation thread (e.g. `/session work_chat`). |
| `/clear` | Clear the conversational history of the active session. |
| `exit` / `quit` | Gracefully exit the terminal chat loop. |

---

## 🚀 Getting Started

### 1. Installation
This project uses `uv` for lightning-fast Python package and project management. Install the dependencies by running:
```bash
uv sync
```
*(Or manually install using `uv pip install -r pyproject.toml`)*

### 2. Environment Configuration
Create a `.env` file in the root directory:
```env
COMPOSIO_API_KEY=your_composio_api_key
GROQ_API_KEY=your_groq_api_key
```

### 3. Run Memory-OS
Launch the interactive CLI:
```bash
uv run python main.py
```
On your first run, the script will guide you with authorization URLs to connect your GitHub, Google Calendar, and Notion accounts in your web browser. Once connected, they will remain active automatically.
