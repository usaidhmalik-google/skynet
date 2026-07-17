# Skynet: Google ADK Agent Builder & Workspace

Skynet is an enterprise-grade Flask web application designed to dynamically generate, load, and execute custom AI agent prototypes using the **Google Agent Development Kit (ADK)**. 

This project incorporates the best practices from the **Google 5-Day AI Agents Intensive Course** on Kaggle, fully aligned with production rubrics for observability, safety, and persistent memory.

---

## Production-Grade Architecture

1. **Tool & Interface Design**: Custom tools utilize strict Pydantic `BaseModel` schemas for argument validation, preventing malformed inputs and ensuring strict JSON schema conformance.
2. **Persistent Context & Compact Memory**:
   - Swaps out basic in-memory session mapping for a robust **`SqliteSessionService`** (`skynet_sessions.db`) to persist states across restarts.
   - Implements **events history compaction** (`EventsCompactionConfig`) using a dynamic `LlmEventSummarizer` to prevent prompt context bloat.
   - Integrates async memory indexes via `InMemoryMemoryService`.
3. **Orchestration & Safety Logic**:
   - **Strategic Model Routing**: Dispatches lightweight routing/coordinating tasks to `gemini-3.5-flash` while reserving resource-intensive reviewing and analysis tasks for `gemini-3.5-pro`.
   - **Human-in-the-Loop (HITL)**: Utilizes a custom `before_tool_callback` validation hook to review and approve tool executions.
   - **Guardrails**: Implements inputs/outputs validation callbacks (`before_agent_callback` / `after_agent_callback`).
4. **observability & Tracing**:
   - **Distributed Tracing**: Configured with the **OpenTelemetry SDK** to record transaction spans.
   - **Structured JSON Logging**: Custom Python log handler formats output as structured JSON.
   - **PII Redaction**: Automatically filters credit cards, emails, Gemini API keys, and GCP access tokens from log outputs.
   - **Intention vs Outcome Tracker**: Tracks prompts and outcomes in a persistent `intentions_outcomes.jsonl` ledger.
5. **Enterprise Infrastructure**:
   - **Secure Key Injection**: Integrates optional GCP **Secret Manager** retrieval.
   - **Terraform IaC**: Infrastructure as Code ([infra/main.tf](infra/main.tf)) to deploy the server on Google Cloud Run with Secret Manager and public IAM bindings.
   - **Automated Test Suite**: Automated evaluation suite ([tests/test_evaluation.py](tests/test_evaluation.py)) validating syntax, contracts, and schema generation.

---

## Setup Instructions

### Installation
Sync project dependencies:
```bash
uv sync
```

### Environment Configuration
Create a `.env` file in the root directory:
```env
GEMINI_API_KEY=AQ.Ab... # Your GCP/Vertex access token or AI Studio key
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GCP_LOCATION=us-central1 # Defaults to us-central1 if omitted
```

### Running the Web Server
Launch the Flask development server:
```bash
uv run python app.py
```
Open your browser and navigate to **`http://localhost:5000`** to start building and chatting with your AI agent prototypes!

### Running the Tests
Execute the automated evaluation suite:
```bash
uv run python -m unittest tests/test_evaluation.py
```
