# Skynet: Google ADK Agent Builder & Workspace

Skynet is a Flask-based web application that dynamically generates, loads, and executes custom AI agent prototypes using the **Google Agent Development Kit (ADK)**. 

This project demonstrates core concepts and best practices from the **Google 5-Day AI Agents Intensive Course** on Kaggle.

---

## Features

1. **Dynamic Agent Generator**: Enter any prompt describing an agent's capability (e.g., "A researcher that searches the web and formats markdown summaries"), and the system will write `generated_agent.py` on disk.
2. **Robust Fallback Compiler**: If model calls fail due to missing or misconfigured credentials, a rule-based compiler automatically generates a production-ready ADK template agent based on keyword analysis of your prompt.
3. **Dual-Auth Environment Resolver**: Configures the ADK model wrapper dynamically to use either the **Google AI Studio (Gemini API)** or **Vertex AI (Google Cloud)** based on the type of key provided in your `.env`.
4. **Real-time SSE Chat Stream**: Chat with your newly generated agent in real-time. Responses stream into the UI token-by-token alongside live tool call indicator chips.
5. **Kaggle 5-Day Course Patterns Implemented**:
   - **Day 1**: System Instructions & Persona definition.
   - **Day 2**: Tool calling (using python functions and built-in tools like `GoogleSearchTool`).
   - **Day 3**: Multi-agent delegation (parent coordinator managing creative writer and editor sub-agents).
   - **Day 4**: Model Context Protocol (MCP) integrating `@modelcontextprotocol/server-filesystem` via `McpToolset`.
   - **Day 5**: Session State and Runner orchestration (`InMemorySessionService` & `Runner`).

---

## Getting Started

### Prerequisites
Make sure you have `uv` installed. If not, follow the setup instructions or run:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Installation
Sync project dependencies:
```bash
uv sync
```

### Environment Configuration
Create a `.env` file in the root directory:

**For Google AI Studio (Gemini API):**
```env
GEMINI_API_KEY=AIzaSy...
```

**For Vertex AI (Google Cloud):**
```env
GEMINI_API_KEY=AQ.Ab... # Your GCP/Vertex access token
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GCP_LOCATION=us-central1 # Defaults to us-central1 if omitted
```

### Running the Web Server
Launch the Flask development server:
```bash
uv run python app.py
```
Open your browser and navigate to **`http://localhost:5000`** to start building and chatting with your AI agent prototypes!
