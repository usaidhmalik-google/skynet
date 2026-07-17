import os
import re
import json
import sys
import asyncio
import importlib.util
from flask import Flask, request, jsonify, render_template, Response
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Import Google ADK and Auth modules
from google.adk import Agent, Runner
from google.adk.sessions import InMemorySessionService
from google.adk.models import Gemini
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.genai import types

app = Flask(__name__)

# Shared session service for user's generated agents
chat_session_service = InMemorySessionService()

def get_adk_model(model_name="gemini-3.5-flash"):
    """Configures the ADK model wrapper dynamically for Gemini API or Vertex AI."""
    api_key = os.environ.get("GEMINI_API_KEY")
    project = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GCP_LOCATION") or "us-central1"
    
    if api_key:
        if api_key.startswith("AQ."):
            # GCP/Vertex AI access token
            creds = OAuthCredentials(token=api_key)
            client_kwargs = {
                "vertexai": True,
                "credentials": creds,
                "location": location
            }
            if project:
                client_kwargs["project"] = project
            return Gemini(model=model_name, client_kwargs=client_kwargs)
        else:
            # Google AI Studio developer API key
            return Gemini(model=model_name)
    return model_name

# System builder agent instructions
BUILDER_INSTRUCTION = """You are an expert developer specializing in the Google Agent Development Kit (ADK).
Your task is to write a single Python file named `generated_agent.py` that implements a custom agent (or multi-agent team) based on the user's description.

You MUST follow these rules when writing the python code:
1. ONLY return the executable Python code inside a markdown block. Do NOT write any conversational text outside of it.
2. Use standard imports:
   import os
   import asyncio
   from google.adk import Agent, Runner
   from google.adk.sessions import InMemorySessionService
   from google.adk.models import Gemini
   from google.oauth2.credentials import Credentials as OAuthCredentials
   from google.adk.tools import google_search, McpToolset
   from google.adk.tools.google_search_tool import GoogleSearchTool
   from mcp import StdioServerParameters
   from google.genai import types
3. The file MUST define a function `create_agent() -> Agent` that returns the configured agent instance.
4. The file MUST define a function `get_runner(agent) -> Runner` that returns a Runner configured with the agent and an InMemorySessionService.
5. In the generated file, implement a robust helper `get_adk_model(model_name="gemini-3.5-flash")` that configures the model based on the env:
   def get_adk_model(model_name="gemini-3.5-flash"):
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
6. Use `get_adk_model("gemini-3.5-flash")` as the model when instantiating the Agent.
7. If the user mentions working with local files, file management, or filesystem operations, you MUST include the `@modelcontextprotocol/server-filesystem` MCP toolset. The toolset connection parameters should be configured like this:
   filesystem_toolset = McpToolset(
       connection_params=StdioServerParameters(
           command="npx",
           args=["-y", "@modelcontextprotocol/server-filesystem", "/Users/usaidhmalik/Projects/skynet"],
       )
   )
   Include this toolset in the agent's `tools` list.
8. If the user mentions web search or searching the internet, include GoogleSearchTool in the agent's `tools` list. Note: If GoogleSearchTool is used alongside other tools, initialize it with bypass_multi_tools_limit=True, e.g., GoogleSearchTool(bypass_multi_tools_limit=True). If it is the only tool, you can use the pre-instantiated `google_search` import.
9. If the user request requires custom actions, define them as Python functions with clear docstrings and type annotations, and include them in the agent's `tools` list.
10. Make the system instructions for the generated agent detailed, robust, and aligned with its goal.
11. Ensure all code is syntactically valid and runnable.
"""

def extract_code(response_text: str) -> str:
    """Helper to extract python block from model response."""
    match = re.search(r"```python\n(.*?)\n```", response_text, re.DOTALL)
    if match:
        return match.group(1)
    match = re.search(r"```\n(.*?)\n```", response_text, re.DOTALL)
    if match:
        return match.group(1)
    return response_text

def generate_fallback_agent_code(prompt: str) -> str:
    """Fallback compiler that designs a clean Google ADK Agent structure when the LLM builder is offline."""
    prompt_lower = prompt.lower()
    
    # Filesystem / Local File Analyst Agent
    if any(k in prompt_lower for k in ["file", "directory", "folder", "filesystem", "csv", "excel", "local"]):
        return """import os
import asyncio
from google.adk import Agent, Runner
from google.adk.sessions import InMemorySessionService
from google.adk.models import Gemini
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.adk.tools import McpToolset
from mcp import StdioServerParameters
from google.genai import types

def get_adk_model(model_name="gemini-3.5-flash"):
    \"\"\"Configures the ADK model wrapper dynamically for Gemini API or Vertex AI.\"\"\"
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

def analyze_data(filepath: str) -> str:
    \"\"\"Reads and analyzes a data file, returning a summary.
    
    Args:
        filepath: The path to the file relative to the workspace.
    \"\"\"
    try:
        if not os.path.exists(filepath):
            return f"Error: File '{filepath}' not found."
        with open(filepath, 'r') as f:
            content = f.read(2000)
        return f"File Analysis Success! Preview of '{filepath}':\\n{content}\\n... [Total: {os.path.getsize(filepath)} bytes]"
    except Exception as e:
        return f"Error reading file: {str(e)}"

def create_agent() -> Agent:
    # Connects to the filesystem MCP server
    filesystem_toolset = McpToolset(
        connection_params=StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", os.getcwd()],
        )
    )
    
    agent = Agent(
        name="filesystem_analyst_agent",
        instruction=\"\"\"You are a filesystem analyst agent. Your goal is to help the user manage and analyze their local files.
        Use the filesystem MCP tools to list, read, and write files in the directory.
        Use the custom 'analyze_data' tool to run local data processing.
        \"\"\",
        tools=[filesystem_toolset, analyze_data],
        model=get_adk_model("gemini-3.5-flash")
    )
    return agent

def get_runner(agent) -> Runner:
    return Runner(
        agent=agent,
        app_name="filesystem_analyst_app",
        session_service=InMemorySessionService(),
        auto_create_session=True
    )
"""

    # Web Research Agent
    elif any(k in prompt_lower for k in ["search", "web", "internet", "google", "browse", "news"]):
        return """import os
import asyncio
from google.adk import Agent, Runner
from google.adk.sessions import InMemorySessionService
from google.adk.models import Gemini
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.adk.tools.google_search_tool import GoogleSearchTool
from google.genai import types

def get_adk_model(model_name="gemini-3.5-flash"):
    \"\"\"Configures the ADK model wrapper dynamically for Gemini API or Vertex AI.\"\"\"
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

def generate_report(query: str, results: str) -> str:
    \"\"\"Generates a formatted markdown report based on search results.
    
    Args:
        query: The search query.
        results: The combined search results.
    \"\"\"
    return f"# Search Report for: {query}\\n\\n## Summary\\n{results}"

def create_agent() -> Agent:
    search_tool = GoogleSearchTool(bypass_multi_tools_limit=True)
    
    agent = Agent(
        name="web_researcher_agent",
        instruction=\"\"\"You are an expert web researcher agent. Your goal is to gather information from Google Search,
        analyze the results, and generate concise, professional markdown summaries.
        \"\"\",
        tools=[search_tool, generate_report],
        model=get_adk_model("gemini-3.5-flash")
    )
    return agent

def get_runner(agent) -> Runner:
    return Runner(
        agent=agent,
        app_name="web_researcher_app",
        session_service=InMemorySessionService(),
        auto_create_session=True
    )
"""

    # Multi-Agent Routing Coordinator Team
    elif any(k in prompt_lower for k in ["team", "multi", "coor", "super", "agent team", "reviewer", "editor"]):
        return """import os
import asyncio
from google.adk import Agent, Runner
from google.adk.sessions import InMemorySessionService
from google.adk.models import Gemini
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.genai import types

def get_adk_model(model_name="gemini-3.5-flash"):
    \"\"\"Configures the ADK model wrapper dynamically for Gemini API or Vertex AI.\"\"\"
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

def create_agent() -> Agent:
    model_wrapper = get_adk_model("gemini-3.5-flash")
    
    writer = Agent(
        name="creative_writer",
        instruction="Generate high-quality text or code based on coordinator instructions.",
        model=model_wrapper,
        mode="single_turn"
    )
    
    editor = Agent(
        name="critical_editor",
        instruction="Review the text produced by the creative_writer and suggest improvements or fixes.",
        model=model_wrapper,
        mode="single_turn"
    )
    
    coordinator = Agent(
        name="team_coordinator",
        instruction=\"\"\"You are a team coordinator. Delegate the writing task to creative_writer,
        then pass the result to critical_editor for feedback. Finally, compile and return the final edited version.
        \"\"\",
        sub_agents=[writer, editor],
        model=model_wrapper,
        mode="chat"
    )
    return coordinator

def get_runner(agent) -> Runner:
    return Runner(
        agent=agent,
        app_name="multi_agent_team_app",
        session_service=InMemorySessionService(),
        auto_create_session=True
    )
"""

    # Custom Analytical / Math agent
    else:
        return f"""import os
import asyncio
from google.adk import Agent, Runner
from google.adk.sessions import InMemorySessionService
from google.adk.models import Gemini
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.genai import types

def get_adk_model(model_name="gemini-3.5-flash"):
    \"\"\"Configures the ADK model wrapper dynamically for Gemini API or Vertex AI.\"\"\"
    api_key = os.environ.get("GEMINI_API_KEY")
    project = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GCP_LOCATION") or "us-central1"
    if api_key and api_key.startswith("AQ."):
        creds = OAuthCredentials(token=api_key)
        client_kwargs = {{"vertexai": True, "credentials": creds, "location": location}}
        if project:
            client_kwargs["project"] = project
        return Gemini(model=model_name, client_kwargs=client_kwargs)
    return Gemini(model=model_name)

def calculate_factorial(n: int) -> str:
    \"\"\"Computes the factorial of a non-negative integer n.
    
    Args:
        n: The integer to compute factorial for.
    \"\"\"
    if n < 0:
        return "Error: Factorial requires non-negative integer."
    import math
    return f"The factorial of {{n}} is {{math.factorial(n)}}"

def create_agent() -> Agent:
    agent = Agent(
        name="custom_math_agent",
        instruction=\"\"\"You are a custom assistant configured to solve user queries.
        Description: {prompt.replace('"', '\\"')}
        If the user asks to calculate a factorial, use the custom 'calculate_factorial' tool.
        \"\"\",
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
"""

def load_generated_agent():
    """Dynamically load/import the generated agent from disk."""
    file_path = os.path.join(os.getcwd(), "generated_agent.py")
    if not os.path.exists(file_path):
        return None
    spec = importlib.util.spec_from_file_location("generated_agent", file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["generated_agent"] = module
    spec.loader.exec_module(module)
    return module.create_agent()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    prompt = request.json.get('prompt', '')
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    print(f"Generating agent for prompt: {prompt}")

    generated_code = ""
    try:
        # Build the agent builder using ADK with appropriate model config
        builder = Agent(
            name="AgentBuilder",
            instruction=BUILDER_INSTRUCTION,
            model=get_adk_model("gemini-3.5-flash")
        )

        # Runner setup
        session_service = InMemorySessionService()
        runner = Runner(
            agent=builder,
            app_name="builder_app",
            session_service=session_service,
            auto_create_session=True
        )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def run_generation():
            nonlocal generated_code
            full_response = ""
            async for event in runner.run_async(
                user_id="web_builder_user",
                session_id="builder_session",
                new_message=types.Content(parts=[types.Part(text=prompt)])
            ):
                if event.content and event.content.parts:
                    full_response += "".join(p.text for p in event.content.parts if p.text)
            
            generated_code = extract_code(full_response)

        loop.run_until_complete(run_generation())
        loop.close()
    except Exception as e:
        print(f"LLM generation failed: {str(e)}. Falling back to robust template compiler.")
        # Fall back to generating clean, syntactically correct ADK template
        generated_code = generate_fallback_agent_code(prompt)

    if not generated_code:
        return jsonify({"error": "Failed to generate code"}), 500

    # Write code to file
    file_path = os.path.join(os.getcwd(), "generated_agent.py")
    with open(file_path, "w") as f:
        f.write(generated_code)

    return jsonify({
        "status": "success",
        "code": generated_code
    })

@app.route('/code', methods=['GET'])
def get_code():
    file_path = os.path.join(os.getcwd(), "generated_agent.py")
    if not os.path.exists(file_path):
        return jsonify({"code": "# No agent generated yet."})
    with open(file_path, "r") as f:
        return jsonify({"code": f.read()})

@app.route('/chat/stream')
def chat_stream():
    user_message = request.args.get('message', '')
    if not user_message:
        return "data: {\"error\": \"Message is empty\"}\n\n", 400

    def event_generator():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            agent = load_generated_agent()
            if not agent:
                yield f"data: {json.dumps({'text': 'Error: No agent generated yet. Please generate one first.'})}\n\n"
                return

            runner = Runner(
                agent=agent,
                app_name="generated_agent_app",
                session_service=chat_session_service,
                auto_create_session=True
            )

            async def run_chat():
                async for event in runner.run_async(
                    user_id="end_user",
                    session_id="chat_session",
                    new_message=types.Content(parts=[types.Part(text=user_message)])
                ):
                    yield event

            gen = run_chat()
            while True:
                try:
                    event = loop.run_until_complete(gen.__anext__())
                    text_chunk = ""
                    if event.content and event.content.parts:
                        text_chunk = "".join(p.text for p in event.content.parts if p.text)

                    func_calls = []
                    if event.get_function_calls():
                        for fc in event.get_function_calls():
                            func_calls.append({"name": fc.name, "args": fc.args})

                    data = {
                        "text": text_chunk,
                        "partial": event.partial,
                        "author": event.author,
                        "func_calls": func_calls
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                except StopAsyncIteration:
                    break
                except Exception as e:
                    yield f"data: {json.dumps({'text': f'\\nError during generation: {str(e)}', 'partial': False})}\n\n"
                    break
        except Exception as e:
            yield f"data: {json.dumps({'text': f'Error loading agent: {str(e)}', 'partial': False})}\n\n"
        finally:
            loop.close()

    return Response(event_generator(), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
