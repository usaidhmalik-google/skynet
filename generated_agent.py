import os
import asyncio
from google.adk import Agent, Runner
from google.adk.sessions import InMemorySessionService
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

def calculate_factorial(n: int) -> str:
    """Computes the factorial of a non-negative integer n.
    
    Args:
        n: The integer to compute factorial for.
    """
    if n < 0:
        return "Error: Factorial requires non-negative integer."
    import math
    return f"The factorial of {n} is {math.factorial(n)}"

def create_agent() -> Agent:
    agent = Agent(
        name="custom_math_agent",
        instruction="""You are a custom assistant configured to solve user queries.
        Description: A math agent that can solve mathematical expressions and has a custom tool to compute factorial
        If the user asks to calculate a factorial, use the custom 'calculate_factorial' tool.
        """,
        tools=[calculate_factorial],
        model=get_adk_model("gemini-3.5-flash")
    )
    return agent

def get_runner(agent) -> Runner:
    return Runner(
        agent=agent,
        app_name="custom_agent_app",
        session_service=InMemorySessionService(),
        auto_create_session=True
    )
