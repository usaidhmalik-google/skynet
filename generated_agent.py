import os
import asyncio
from pydantic import BaseModel, Field
from google.adk import Agent, Runner
from google.adk.apps import App
from google.adk.apps._configs import EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.models import Gemini
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.genai import types

def get_adk_model(model_name="gemini-3.5-flash"):
    """Configures the ADK model wrapper dynamically for Gemini API or Vertex AI."""
    api_key = os.environ.get("GEMINI_API_KEY")
    project = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GCP_LOCATION") or "us-central1"
    if api_key and api_key.startswith("AQ."):
        creds = OAuthCredentials(token=api_key)
        client_kwargs = {"vertexai": True, "credentials": creds, "location": location}
        if project:
            client_kwargs["project"] = project
        return Gemini(model=model_name, client_kwargs=client_kwargs)
    return Gemini(model=model_name)

# Pydantic schemas for verification
class FactorialInput(BaseModel):
    n: int = Field(..., ge=0, description="The non-negative integer to compute factorial for.")

def calculate_factorial(args: FactorialInput) -> str:
    """Computes the factorial of a non-negative integer.
    
    Args:
        args: Input parameters containing n.
    """
    import math
    n = args.n
    return f"The factorial of {n} is {math.factorial(n)}"

async def before_tool_check(tool, args, context):
    print(f"[HITL] Approving tool: {tool.name} with arguments: {args}")
    return args

def create_agent() -> Agent:
    # Strategic Routing: flash for coordinating agent, high-performance pro for analytical tools
    coordinator_model = get_adk_model("gemini-3.5-flash")
    
    agent = Agent(
        name="custom_math_agent",
        instruction="""You are a custom assistant configured to solve user queries.
        Description: A math agent that can solve mathematical expressions and has a custom tool to compute factorial
        If the user asks to calculate a factorial, use the custom 'calculate_factorial' tool.
        """,
        tools=[calculate_factorial],
        before_tool_callback=before_tool_check,
        model=coordinator_model
    )
    return agent

def get_runner(agent) -> Runner:
    model_wrapper = get_adk_model("gemini-3.5-flash")
    sqlite_service = SqliteSessionService(db_path="skynet_sessions.db")
    
    compaction = EventsCompactionConfig(
        summarizer=LlmEventSummarizer(llm=model_wrapper),
        compaction_interval=5,
        overlap_size=1
    )
    
    app = App(
        name="custom_agent_app",
        root_agent=agent,
        events_compaction_config=compaction
    )
    
    return Runner(
        app=app,
        session_service=sqlite_service,
        memory_service=InMemoryMemoryService(),
        auto_create_session=True
    )
