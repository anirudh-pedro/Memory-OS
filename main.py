def main():
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print("Hello from memory-os!")
    
    import os

    from composio import Composio, SESSION_PRESET_DIRECT_TOOLS
    from composio_langchain import LangchainProvider
    from langchain.agents import create_agent
    from langchain_groq import ChatGroq
    from dotenv import load_dotenv

    load_dotenv()
    composio = Composio(provider=LangchainProvider())

    llm = ChatGroq(
        model="openai/gpt-oss-120b",
        api_key=os.getenv("GROQ_API_KEY")
    )

    session = composio.create(
        user_id="user_123",
        toolkits=["github", "googlecalendar", "notion"],
        tools={
            "github": {
                "enable": [
                    "GITHUB_GET_THE_AUTHENTICATED_USER",
                    "GITHUB_CREATE_A_REPOSITORY_FOR_THE_AUTHENTICATED_USER",
                    "GITHUB_CREATE_AN_ISSUE",
                ]
            },
            "googlecalendar": {
                "enable": [
                    "GOOGLECALENDAR_LIST_CALENDARS",
                    "GOOGLECALENDAR_CREATE_EVENT",
                    "GOOGLECALENDAR_QUICK_ADD",
                ]
            },
            "notion": {
                "enable": [
                    "NOTION_LIST_USERS",
                    "NOTION_CREATE_NOTION_PAGE",
                    "NOTION_APPEND_TEXT_BLOCKS",
                ]
            }
        },
        session_preset=SESSION_PRESET_DIRECT_TOOLS,
    )
    tools = session.tools()

    def patch_tool_schemas(tools_list):
        import typing
        from pydantic import create_model
        for t in tools_list:
            if t.args_schema is None:
                continue
            patched_fields = {}
            for name, field in t.args_schema.model_fields.items():
                annotation = field.annotation
                default = field.default
                if default is None:
                    args = typing.get_args(annotation)
                    if type(None) not in args:
                        if args:
                            annotation = typing.Union[annotation, None]
                        else:
                            annotation = typing.Optional[annotation]
                patched_fields[name] = (annotation, default)
            t.args_schema = create_model(t.args_schema.__name__, **patched_fields)

    patch_tool_schemas(tools)

    import json

    # for tool in tools:
    #     print(tool.name)
    #     print(json.dumps(tool.args, indent=2))
    print("Number of tools:", len(tools))

    from langchain_core.tools import tool

    db_path = "memory.db"

    @tool
    def save_personal_fact(fact: str) -> str:
        """Save a long-term personal fact or preference about the user to help personalize future conversations."""
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS semantic_memory (id INTEGER PRIMARY KEY, fact TEXT)")
        cursor.execute("INSERT INTO semantic_memory (fact) VALUES (?)", (fact,))
        conn.commit()
        conn.close()
        return f"Successfully saved fact: '{fact}'"

    @tool
    def search_personal_facts(query: str) -> str:
        """Search for previously saved personal facts or preferences about the user using keywords."""
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS semantic_memory (id INTEGER PRIMARY KEY, fact TEXT)")
        
        words = [w.strip() for w in query.split() if len(w.strip()) > 2]
        if not words:
            cursor.execute("SELECT fact FROM semantic_memory LIMIT 20")
        else:
            conditions = " OR ".join(["fact LIKE ?"] * len(words))
            params = [f"%{w}%" for w in words]
            cursor.execute(f"SELECT fact FROM semantic_memory WHERE {conditions} LIMIT 20", params)
            
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return "No matching personal facts found."
        
        facts_str = "\n".join([f"- {r[0]}" for r in rows])
        return f"Found matching facts:\n{facts_str}"

    tools = list(tools) + [save_personal_fact, search_personal_facts]

    # Check and establish connections for toolkits
    toolkits_to_check = ["github", "googlecalendar", "notion"]
    toolkits_info = session.toolkits()
    for tk_slug in toolkits_to_check:
        tk = next((t for t in toolkits_info.items if t.slug == tk_slug), None)
        if not tk or not (tk.connection and tk.connection.is_active):
            print(f"{tk_slug} connection is not active. Initiating connection...")
            connection_req = session.authorize(tk_slug)
            print(f"\n[ACTION REQUIRED] Please authorize Composio to access your {tk_slug} account by visiting this URL:")
            print(f"--> {connection_req.redirect_url}\n")
            print("Waiting for you to complete authorization in your browser...")
            connection_req.wait_for_connection()
            print(f"{tk_slug} connection established successfully!\n")
        else:
            print(f"{tk_slug} connection is active.")

    from langgraph.checkpoint.sqlite import SqliteSaver

    with SqliteSaver.from_conn_string(db_path) as memory:
        agent = create_agent(
            model=llm,
            tools=tools,
            checkpointer=memory,
            system_prompt=(
                "You are a helpful assistant with access to the user's personal accounts (GitHub, Google Calendar, Notion) "
                "and a long-term personal memory database.\n\n"
                "MEMORY GUIDELINES:\n"
                "- If the user shares a personal fact, preference, or detail (e.g. 'I love coffee', 'My wife's name is Emily', 'My birth year is 1995'), "
                "save it using the save_personal_fact tool.\n"
                "- If the user asks a question about themselves, their history, or preferences, look it up using the search_personal_facts tool.\n\n"
                "TOOL CALLING GUIDELINES:\n"
                "- IMPORTANT: When invoking tools, do NOT include optional arguments with 'null' or null values in the JSON. Omit them completely."
            )
        )
        
        thread_id = "default_session"
        
        print("\n" + "="*40)
        print("🧠 MEMORY-OS INTERACTIVE CLI CHAT 🧠")
        print("Connected toolkits: " + ", ".join(toolkits_to_check))
        print(f"Active Session ID: {thread_id}")
        print("="*40)
        print("Commands:")
        print("  /clear          - Clear current session chat history")
        print("  /session <id>   - Switch to or create a different session")
        print("  exit / quit     - Exit the chat")
        print("="*40)
        
        while True:
            try:
                user_input = input(f"\n[{thread_id}] You: ").strip()
                if user_input.lower() in ["exit", "quit"]:
                    print("Goodbye!")
                    break
                
                if not user_input:
                    continue
                
                # Command: Clear chat history
                if user_input.lower() == "/clear":
                    import sqlite3
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
                    cursor.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
                    conn.commit()
                    conn.close()
                    print(f"Memory cleared for session '{thread_id}'.")
                    continue
                
                # Command: Switch session
                if user_input.startswith("/session "):
                    parts = user_input.split(" ", 1)
                    if len(parts) > 1 and parts[1].strip():
                        thread_id = parts[1].strip()
                        print(f"Switched to session '{thread_id}'.")
                    else:
                        print("Invalid session ID.")
                    continue
                
                config = {"configurable": {"thread_id": thread_id}}
                
                print("\nThinking...")
                response = agent.invoke({"messages": [("user", user_input)]}, config=config)
                
                messages = response.get("messages", [])
                if messages:
                    last_msg = messages[-1]
                    print(f"\nMemory-OS:\n{last_msg.content}")
                else:
                    print("\nMemory-OS: No response received.")
                    
            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"\nError: {e}")
   


if __name__ == "__main__":
    main()
