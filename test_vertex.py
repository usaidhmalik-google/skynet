import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

from google.adk import Agent, Runner
from google.adk.models import Gemini
from google.adk.sessions import InMemorySessionService
from google.genai import types

async def main():
    agent = Agent(
        name="test_agent",
        model=Gemini(model="gemini-3.5-flash", client_kwargs={"vertexai": True}),
        instruction="You are a helpful assistant.",
    )
    
    runner = Runner(
        agent=agent,
        app_name="test_app",
        session_service=InMemorySessionService(),
        auto_create_session=True
    )
    
    async for event in runner.run_async(
        user_id="user_1",
        session_id="sess_1",
        new_message=types.Content(parts=[types.Part(text="Hello!")])
    ):
        print(event)

if __name__ == "__main__":
    asyncio.run(main())
