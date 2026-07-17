import asyncio
from dotenv import load_dotenv
load_dotenv()

from google.auth import default
from google.genai import Client

async def main():
    try:
        creds, project = default()
        print("Project:", project)
        for loc in ["us-central1", "global"]:
            try:
                client = Client(vertexai=True, project=project, location=loc)
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents="Hello",
                )
                print(f"Success with location {loc}:", response.text)
                return
            except Exception as e:
                print(f"Failed with location {loc}:", e)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(main())
