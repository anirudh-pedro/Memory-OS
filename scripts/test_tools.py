import os
import sys
import logging
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from composio import Composio, SESSION_PRESET_DIRECT_TOOLS
from composio_langchain import LangchainProvider
from langchain_groq import ChatGroq

load_dotenv()

# LLM Setup
llm = ChatGroq(
    model="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY")
)

# Composio Setup
composio = Composio(provider=LangchainProvider())
session = composio.create(
    user_id="user_123",
    toolkits=["github", "googlecalendar", "notion", "gmail"],
    tools={
        "github": {
            "enable": [
                "GITHUB_GET_THE_AUTHENTICATED_USER",
                "GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER",
                "GITHUB_GET_A_REPOSITORY",
                "GITHUB_GET_A_REPOSITORY_README",
                "GITHUB_LIST_REPOSITORY_ISSUES",
                "GITHUB_LIST_PULL_REQUESTS",
                "GITHUB_LIST_REPOSITORY_PROJECTS",
                "GITHUB_LIST_USER_PROJECTS",
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
                "NOTION_SEARCH_NOTION_PAGE",
                "NOTION_CREATE_NOTION_PAGE",
                "NOTION_APPEND_TEXT_BLOCKS",
            ]
        },
        "gmail": {
            "enable": [
                "GMAIL_FETCH_EMAILS",
                "GMAIL_SEND_EMAIL",
            ]
        }
    },
    session_preset=SESSION_PRESET_DIRECT_TOOLS,
)
tools = session.tools()

print(f"Total tools loaded: {len(tools)}")
for t in tools:
    name = getattr(t, "name", None)
    print(f"Tool name: '{name}', class: {t.__class__.__name__}")
    if not name:
        print(f"ERROR: Tool missing name: {t}")

print("Patching tool schemas...")
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

try:
    print("Binding tools to Groq LLM...")
    bound_llm = llm.bind_tools(tools)
    print("Successfully bound tools!")
    
    # Try a simple invocation to see if it triggers the rendering error
    print("Testing simple invoke...")
    resp = bound_llm.invoke("Hello, who are you?")
    print("Invoke success!")
    print(resp)
except Exception as e:
    print(f"BIND/INVOKE FAILED: {e}")
