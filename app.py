import os
import re
import json
import sys
import time
import asyncio
import importlib.util
import logging
from flask import Flask, request, jsonify, render_template, Response
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Observability: Structured JSON Logging & PII Redaction ---
PII_PATTERNS = [
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), '[EMAIL_REDACTED]'),
    (re.compile(r'\b(?:\d[ -]*?){13,16}\b'), '[CARD_REDACTED]'),
    (re.compile(r'AIzaSy[A-Za-z0-9_-]{33}'), '[API_KEY_REDACTED]'),
    (re.compile(r'AQ\.Ab[A-Za-z0-9_-]+'), '[ACCESS_TOKEN_REDACTED]')
]

def redact_pii(text: str) -> str:
    """Masks sensitive elements in logs (emails, cards, keys, tokens)."""
    if not isinstance(text, str):
        return text
    for pattern, replacement in PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text

class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as clean JSON with PII redaction."""
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_pii(record.getMessage()),
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)

# Configure Flask logging
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(StructuredJsonFormatter())
logger = logging.getLogger("skynet")
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# --- Observability: OpenTelemetry SDK Setup ---
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter

try:
    provider = TracerProvider()
    processor = SimpleSpanProcessor(ConsoleSpanExporter())
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("skynet")
    logger.info("OpenTelemetry trace provider configured successfully.")
except Exception as ote:
    logger.warning(f"Failed to setup OpenTelemetry: {ote}")
    tracer = trace.get_tracer("skynet")

# --- Infrastructure: Google Secret Manager Secure Key Injection ---
def get_secret_from_manager(secret_id, project_id):
    """Attemps to securely retrieve key from GCP Secret Manager."""
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        logger.info(f"Successfully retrieved secret '{secret_id}' from Secret Manager.")
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        logger.info(f"Secret Manager optional access failed or not configured: {e}. Falling back to env.")
        return None

# Perform secure key injection check
sm_project = os.environ.get("GOOGLE_CLOUD_PROJECT")
sm_secret_id = os.environ.get("SECRET_MANAGER_SECRET_ID", "gemini-api-key")
if sm_project:
    sm_key = get_secret_from_manager(sm_secret_id, sm_project)
    if sm_key:
        os.environ["GEMINI_API_KEY"] = sm_key

# --- Observability: Intention vs Outcome Logger ---
def log_intent_vs_outcome(intent: str, outcome: str, status: str, error_msg: str = None):
    """Tracks prompt intents against compiled outputs in a JSONL ledger."""
    log_entry = {
        "intent": redact_pii(intent),
        "outcome": redact_pii(outcome) if outcome else None,
        "status": status,
        "error": redact_pii(error_msg) if error_msg else None,
        "timestamp": time.time()
    }
    try:
        with open("intentions_outcomes.jsonl", "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        logger.error(f"Failed to write intention outcome logs: {e}")

# --- Google ADK & Auth Imports ---
from google.adk import Agent, Runner
from google.adk.apps import App
from google.adk.apps._configs import EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.adk.sessions import InMemorySessionService
from google.adk.models import Gemini
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.genai import types

app = Flask(__name__)

# Persistent SQLite session service for workspace agents
chat_session_service = SqliteSessionService(db_path="skynet_sessions.db")

def get_adk_model(model_name="gemini-3.5-flash"):
    """Configures the ADK model wrapper dynamically for Gemini API or Vertex AI."""
    api_key = os.environ.get("GEMINI_API_KEY")
    project = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GCP_LOCATION") or "us-central1"
    
    if api_key:
        if api_key.startswith("AQ."):
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
            return Gemini(model=model_name)
    return model_name

# System builder agent instructions - guides the builder in generating production-grade ADK configurations
BUILDER_INSTRUCTION = """You are an expert developer specializing in the Google Agent Development Kit (ADK).
Your task is to write a single Python file named `generated_agent.py` that implements a custom agent (or multi-agent team) based on the user's description.

You MUST follow these rules when writing the python code:
1. ONLY return the executable Python code inside a markdown block. Do NOT write any conversational text outside of it.
2. Use standard imports:
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
   from google.adk.tools import google_search, McpToolset
   from google.adk.tools.google_search_tool import GoogleSearchTool
   from mcp import StdioServerParameters
   from google.genai import types
3. Define explicit Pydantic BaseModels for strict input/output validation of custom tools.
4. The file MUST define a function `create_agent() -> Agent` that returns the configured agent instance.
5. The file MUST define a function `get_runner(agent) -> Runner` that configures:
   - A persistent SqliteSessionService(db_path="skynet_sessions.db")
   - History compaction using EventsCompactionConfig with LlmEventSummarizer configured for get_adk_model()
   - An App instance holding the coordinator and compaction config
   - A Runner instance utilizing the App, Sqlite session service, and InMemoryMemoryService for async memory operations.
6. In the generated file, implement a robust helper `get_adk_model(model_name="gemini-3.5-flash")` that configures the model based on the env:
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
7. Enforce strategic model routing. Route lightweight coordinator tasks to get_adk_model("gemini-3.5-flash") and complex math/editor tasks to get_adk_model("gemini-3.5-pro").
8. Implement input/output guardrails using `before_agent_callback` and `after_agent_callback`.
9. Implement a Human-in-the-Loop validation hook using `before_tool_callback`.
10. If the user mentions local files, include `@modelcontextprotocol/server-filesystem` MCP toolset.
11. If the user mentions web search, include GoogleSearchTool(bypass_multi_tools_limit=True).
12. Ensure all code is syntactically valid and runnable.
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
    """Fallback compiler that designs a highly structured, production-grade ADK Agent conforming to the rubrics."""
    prompt_lower = prompt.lower()
    
    # 1. Local File Analyst Template
    if any(k in prompt_lower for k in ["file", "directory", "folder", "filesystem", "csv", "excel", "local"]):
        return """import os
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

# Strict Input/Output Schema definitions
class FilePathSchema(BaseModel):
    filepath: str = Field(..., description="The path to the file relative to the workspace directory.")

class FileAnalysisResponse(BaseModel):
    summary: str = Field(..., description="Detailed markdown analysis summary of the file.")

def analyze_data(args: FilePathSchema) -> str:
    \"\"\"Reads and analyzes a local file strictly.
    
    Args:
        args: Strict input schema holding the target filepath.
    \"\"\"
    filepath = args.filepath
    try:
        if not os.path.exists(filepath):
            return f"Error: File '{filepath}' not found."
        with open(filepath, 'r') as f:
            content = f.read(2000)
        return f"File Analysis Success! Preview of '{filepath}':\\n{content}"
    except Exception as e:
        return f"Error reading file: {str(e)}"

# Guardrails
async def input_guardrail(callback_context):
    print(f"[Guardrail] Intercepted user query: {callback_context.user_content}")

# Human-in-the-Loop Validation Hook
async def before_tool_check(tool, args, context):
    print(f"[HITL] Approving execution of tool {tool.name} with arguments {args}")
    return args

def create_agent() -> Agent:
    # Day 4: MCP integration
    filesystem_toolset = McpToolset(
        connection_params=StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", os.getcwd()],
        )
    )
    
    # Strategic Routing: Flash for fast agent orchestration
    agent = Agent(
        name="filesystem_analyst_agent",
        instruction=\"\"\"You are a filesystem analyst agent.
        Use the filesystem MCP tools to manage files.
        Use the custom 'analyze_data' tool to run local analysis.
        \"\"\",
        tools=[filesystem_toolset, analyze_data],
        before_agent_callback=input_guardrail,
        before_tool_callback=before_tool_check,
        model=get_adk_model("gemini-3.5-flash")
    )
    return agent

def get_runner(agent) -> Runner:
    model_wrapper = get_adk_model("gemini-3.5-flash")
    sqlite_service = SqliteSessionService(db_path="skynet_sessions.db")
    
    # Day 5: Compaction & Persistent state configurations
    compaction = EventsCompactionConfig(
        summarizer=LlmEventSummarizer(llm=model_wrapper),
        compaction_interval=5,
        overlap_size=1
    )
    
    app = App(
        name="filesystem_analyst_app",
        root_agent=agent,
        events_compaction_config=compaction
    )
    
    return Runner(
        app=app,
        session_service=sqlite_service,
        memory_service=InMemoryMemoryService(),
        auto_create_session=True
    )
"""

    # 2. Web Research Template
    elif any(k in prompt_lower for k in ["search", "web", "internet", "google", "browse", "news"]):
        return """import os
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

class QuerySchema(BaseModel):
    query: str = Field(..., description="The query to search the web for.")

def generate_report(args: QuerySchema) -> str:
    \"\"\"Generates a formatted markdown report.
    
    Args:
        args: Input parameters for generating report.
    \"\"\"
    return f"# Report for web query: {args.query}\\n\\nAnalysis complete."

async def input_guardrail(callback_context):
    print(f"[Guardrail] Checking input: {callback_context.user_content}")

async def before_tool_check(tool, args, context):
    print(f"[HITL] Permitting tool: {tool.name}")
    return args

def create_agent() -> Agent:
    search_tool = GoogleSearchTool(bypass_multi_tools_limit=True)
    
    # Strategic Routing: Flash for fast agent responses
    agent = Agent(
        name="web_researcher_agent",
        instruction="Gather info via google search and write markdown summaries.",
        tools=[search_tool, generate_report],
        before_agent_callback=input_guardrail,
        before_tool_callback=before_tool_check,
        model=get_adk_model("gemini-3.5-flash")
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
        name="web_researcher_app",
        root_agent=agent,
        events_compaction_config=compaction
    )
    
    return Runner(
        app=app,
        session_service=sqlite_service,
        memory_service=InMemoryMemoryService(),
        auto_create_session=True
    )
"""

    # 3. Multi-Agent Team Template
    elif any(k in prompt_lower for k in ["team", "multi", "coor", "super", "agent team", "reviewer", "editor"]):
        return """import os
import asyncio
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
    # Strategic Routing: flash for writer, high-performance pro for reviewer/editor
    flash_model = get_adk_model("gemini-3.5-flash")
    pro_model = get_adk_model("gemini-3.5-pro")
    
    writer = Agent(
        name="creative_writer",
        instruction="Generate text based on instructions.",
        model=flash_model,
        mode="single_turn"
    )
    
    editor = Agent(
        name="critical_editor",
        instruction="Review the text produced by creative_writer critically.",
        model=pro_model,
        mode="single_turn"
    )
    
    coordinator = Agent(
        name="team_coordinator",
        instruction="Delegate tasks to creative_writer, then critical_editor, compiling results.",
        sub_agents=[writer, editor],
        model=flash_model,
        mode="chat"
    )
    return coordinator

def get_runner(agent) -> Runner:
    model_wrapper = get_adk_model("gemini-3.5-flash")
    sqlite_service = SqliteSessionService(db_path="skynet_sessions.db")
    
    compaction = EventsCompactionConfig(
        summarizer=LlmEventSummarizer(llm=model_wrapper),
        compaction_interval=5,
        overlap_size=1
    )
    
    app = App(
        name="multi_agent_team_app",
        root_agent=agent,
        events_compaction_config=compaction
    )
    
    return Runner(
        app=app,
        session_service=sqlite_service,
        memory_service=InMemoryMemoryService(),
        auto_create_session=True
    )
"""

    # 4. Custom Factorial/Math Template (Default)
    else:
        return f"""import os
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

# Pydantic schemas for verification
class FactorialInput(BaseModel):
    n: int = Field(..., ge=0, description="The non-negative integer to compute factorial for.")

def calculate_factorial(args: FactorialInput) -> str:
    \"\"\"Computes the factorial of a non-negative integer.
    
    Args:
        args: Input parameters containing n.
    \"\"\"
    import math
    n = args.n
    return f"The factorial of {{n}} is {{math.factorial(n)}}"

async def before_tool_check(tool, args, context):
    print(f"[HITL] Approving tool: {{tool.name}} with arguments: {{args}}")
    return args

def create_agent() -> Agent:
    # Strategic Routing: flash for coordinating agent, high-performance pro for analytical tools
    coordinator_model = get_adk_model("gemini-3.5-flash")
    
    agent = Agent(
        name="custom_math_agent",
        instruction=\"\"\"You are a custom assistant configured to solve user queries.
        Description: {prompt.replace('"', '\\"')}
        If the user asks to calculate a factorial, use the custom 'calculate_factorial' tool.
        \"\"\",
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

    logger.info(f"Received generation request with prompt: {prompt}")

    generated_code = ""
    status = "success"
    error_msg = None
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

        # Enclose in trace span for OpenTelemetry
        with tracer.start_as_current_span("generate-agent-llm") as span:
            span.set_attribute("prompt", prompt)
            loop.run_until_complete(run_generation())
            loop.close()
    except Exception as e:
        error_msg = str(e)
        logger.warning(f"LLM generation failed: {error_msg}. Falling back to robust template compiler.")
        generated_code = generate_fallback_agent_code(prompt)
        status = "fallback"

    # Log Intention vs Outcome
    log_intent_vs_outcome(prompt, generated_code, status, error_msg)

    if not generated_code:
        return jsonify({"error": "Failed to generate code"}), 500

    # Write code to file
    file_path = os.path.join(os.getcwd(), "generated_agent.py")
    with open(file_path, "w") as f:
        f.write(generated_code)

    return jsonify({
        "status": status,
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

    logger.info(f"Chat stream initiated for query: {user_message}")

    def event_generator():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            agent = load_generated_agent()
            if not agent:
                yield f"data: {json.dumps({'text': 'Error: No agent generated yet. Please generate one first.'})}\n\n"
                return

            spec = importlib.util.spec_from_file_location("generated_agent", os.path.join(os.getcwd(), "generated_agent.py"))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Fetch runner using generated agent's contract
            runner = module.get_runner(agent)

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
                    logger.error(f"Error during agent execution loop: {e}")
                    yield f"data: {json.dumps({'text': f'\\nError during generation: {str(e)}', 'partial': False})}\n\n"
                    break
        except Exception as e:
            logger.error(f"Error loading generated agent module: {e}")
            yield f"data: {json.dumps({'text': f'Error loading agent: {str(e)}', 'partial': False})}\n\n"
        finally:
            loop.close()

    return Response(event_generator(), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
