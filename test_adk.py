import asyncio
from google.adk import Agent, Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

async def main():
    agent = Agent(
        name="my_agent",
        instruction="You are a helpful assistant.",
    )

    runner = Runner(
        agent=agent,
        app_name="my_app",
        session_service=InMemorySessionService(),
        auto_create_session=True,
    )

    print("Running agent...")
    async for event in runner.run_async(
        user_id="user_1",
        session_id="session_1",
        new_message=types.Content(
            parts=[types.Part(text="Say hello in one word!")]
        ),
    ):
        print(f"Event: {event}")
        if event.content:
            print(f"Content: {event.content}")

if __name__ == "__main__":
    asyncio.run(main())
