# HaMenate'ach — Multi-Agent Incident Response Orchestrator

## Project Overview
Multi-agent system for FlowStack's AI-powered incident response platform.
Incoming incidents get classified by a Router, dispatched to specialist agents (DATABASE, NETWORK, SECURITY, APPLICATION), and synthesized into a final report by an Orchestrator.

**No frameworks.** No LangChain, CrewAI, LangGraph, or AutoGen. Raw Python only.

## Architecture Flow
```
INCIDENT (free text)
    │
    ▼
ROUTER (Ollama qwen2.5:14b)
    → Returns: { category: str, confidence: float }
    │
    ▼
ORCHESTRATOR
    → Dispatches to specialist based on category
    → Detects if handoff to second agent is needed
    → Synthesizes final report from all agent findings
    │
    ▼
SPECIALIST AGENT (Ollama qwen2.5:14b)
    → Has domain-specific system prompt
    → Runs agent loop: LLM call → parse tool calls → execute → loop
    → Writes findings to shared state
    │
    ▼
SHARED STATE (Python dict)
    → All agents read/write findings here
    → { incident_id, findings: [...], severity, timeline }
```

## LLM Configuration
- **ALL agents use Ollama** with model `qwen2.5:14b` (no Groq — no API key available)
- Ollama runs locally, accessed via `ollama` Python package or OpenAI-compatible API at `http://localhost:11434/v1`

## File Structure (post-merge)

### Root level (partner-owned — do not modify):
- `state.py` — `IncidentState` dataclass (partner's interface)
- `tools.py` — Tool implementations: `log_search()`, `runbook_lookup()`, `metric_query()`, `check_ssl()`
- `mock_data.py` — Fake log entries, runbook database, metric time series
- `app.py` — Streamlit UI (imports from `src/` and root `state.py`/`tools.py`)
- `main.py` — CLI entry point

### src/ package (canonical — all our code lives here):
- `src/config.py` — `OLLAMA_MODEL`, `MAX_TOOL_CALLS_PER_TURN`, `AGENT_CATEGORIES`
- `src/agent_loop.py` — ReAct loop: LLM call → `extract_json` → tool execute → repeat
- `src/orchestrator.py` — Full pipeline: route → escalation queue → synthesize
- `src/router.py` — LLM-powered incident classifier (returns `ambiguous` flag)
- `src/agents.py` — `AGENTS` dict: system prompts + `allowed_tools` per domain (Gil's)
- `src/state_adapter.py` — Bridges partner's `IncidentState` to our orchestrator interface

### tests/:
- `tests/test_system.py` — 25 pytest tests (all mocked, no Ollama needed)
- `tests/hackathon_tests.py` — Integration tests using real `state.py`/`tools.py`

## Interface Contracts

### config.py (shared)
```python
OLLAMA_MODEL = "qwen2.5:14b"
OLLAMA_BASE_URL = "http://localhost:11434/v1"

AGENT_CATEGORIES = ["DATABASE", "NETWORK", "SECURITY", "APPLICATION"]

# Tool registry: maps tool name → callable
TOOL_REGISTRY = {
    "log_search": tools.log_search,
    "runbook_lookup": tools.runbook_lookup,
    "metric_query": tools.metric_query,
    "check_ssl": tools.check_ssl,
}
```

### state.py (Partner owns — you import)
```python
class IncidentState:
    """Shared incident context. All agents read/write here."""
    
    def __init__(self, incident_id: str, description: str):
        self.incident_id = incident_id
        self.description = description
        self.findings = []        # List of { agent: str, finding: str, timestamp: str }
        self.severity = None      # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
        self.timeline = []        # Chronological events
        self.active_agent = None  # Currently running agent name
        self.tool_calls = []      # Log of tool calls made
        self.status = "OPEN"      # "OPEN" | "INVESTIGATING" | "RESOLVED"
    
    def add_finding(self, agent: str, finding: str): ...
    def add_tool_call(self, agent: str, tool: str, args: dict, result: str): ...
    def set_severity(self, severity: str): ...
    def add_timeline_event(self, event: str): ...
    def to_dict(self) -> dict: ...
```

### router.py (Gil owns — you call from orchestrator)
```python
def route_incident(description: str) -> dict:
    """
    Classifies an incident into a category.
    
    Returns:
        {
            "category": "DATABASE" | "NETWORK" | "SECURITY" | "APPLICATION" | "OUT_OF_SCOPE",
            "confidence": 0.0-1.0,
            "reasoning": "Brief explanation of classification"
        }
    """
```

### agents.py (Gil owns — you call from orchestrator)
```python
# Each specialist agent config
SPECIALIST_AGENTS = {
    "DATABASE": {
        "system_prompt": "...",
        "tools": ["log_search", "runbook_lookup", "metric_query"],
    },
    "NETWORK": {
        "system_prompt": "...",
        "tools": ["check_ssl", "log_search", "metric_query"],
    },
    "SECURITY": {
        "system_prompt": "...",
        "tools": ["log_search", "metric_query"],
    },
    "APPLICATION": {
        "system_prompt": "...",
        "tools": ["log_search", "runbook_lookup", "metric_query"],
    },
}

def get_agent_config(category: str) -> dict:
    """Returns the agent config for a given category."""
    return SPECIALIST_AGENTS.get(category)
```

### tools.py (Partner owns — agent_loop executes these)
```python
def log_search(query: str, service: str = None, limit: int = 10) -> str:
    """Search logs by keyword. Returns matching log entries as formatted string."""

def runbook_lookup(topic: str) -> str:
    """Look up runbook by topic. Returns runbook steps as formatted string."""

def metric_query(metric_name: str, service: str = None, time_range: str = "1h") -> str:
    """Query metrics. Returns metric data as formatted string."""

def check_ssl(hostname: str) -> str:
    """Check SSL certificate status. Returns cert info as formatted string."""
```

## YOUR FILE: agent_loop.py

### Purpose
Generic agent execution engine. ANY agent (router or specialist) uses this to:
1. Send messages to LLM
2. Parse structured tool calls from LLM response
3. Execute the tools
4. Feed results back to LLM
5. Loop until LLM gives a final answer (no more tool calls)

### Key Design Decisions
- Tool calls are parsed from LLM text output (not native function calling — Ollama qwen2.5 may not support it reliably)
- Use a structured format in the system prompt to instruct the LLM to output tool calls as JSON
- Maximum loop iterations: 5 (prevent infinite loops)
- Each iteration updates the shared state with tool call logs

### Expected Interface
```python
def run_agent_loop(
    system_prompt: str,
    user_message: str,
    available_tools: dict,     # { "tool_name": callable }
    state: IncidentState,      # shared state to read/write
    agent_name: str,           # e.g. "DATABASE", "SECURITY"
    max_iterations: int = 5,
) -> dict:
    """
    Runs the agent loop until the LLM produces a final answer.
    
    Returns:
        {
            "analysis": str,           # The agent's final analysis
            "severity": str,           # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
            "root_cause": str,         # Root cause hypothesis
            "remediation": list[str],  # Recommended remediation steps
            "tool_calls_made": list,   # Log of tools called
            "handoff_needed": str|None # If agent detects another domain issue, returns category
        }
    """
```

### Tool Call Format (instruct LLM to use this)
```
TOOL_CALL: {"tool": "log_search", "args": {"query": "postgres", "service": "db-primary"}}
```

### Final Answer Format (instruct LLM to use this)
```
FINAL_ANSWER: {
    "analysis": "...",
    "severity": "HIGH",
    "root_cause": "...",
    "remediation": ["Step 1", "Step 2"],
    "handoff_needed": null
}
```

## YOUR FILE: orchestrator.py

### Purpose
The conductor. Manages the full incident lifecycle:
1. Receive incident description
2. Call router to classify it
3. Dispatch to the correct specialist agent
4. Collect results
5. **Detect if handoff to a second agent is needed** (CRITICAL for surprise twist)
6. If handoff: dispatch to second agent
7. Synthesize a final unified report from all agent findings

### Key Design Decisions
- Support multi-hop agent chains (Agent A → detects security issue → handoff to Agent B)
- The `handoff_needed` field in agent_loop output triggers automatic dispatch to another specialist
- Maximum chain depth: 3 (prevent infinite handoff loops)
- Out-of-scope incidents: return a polite message, do NOT route to any agent
- Ambiguous incidents (low confidence from router): route with a flag, don't hallucinate certainty

### Expected Interface
```python
def handle_incident(
    description: str,
    state: IncidentState,
    on_agent_start: callable = None,   # UI callback: agent started
    on_agent_complete: callable = None, # UI callback: agent finished
    on_tool_call: callable = None,      # UI callback: tool was called
) -> dict:
    """
    Full orchestration flow for an incident.
    
    Returns:
        {
            "incident_id": str,
            "classification": { "category": str, "confidence": float },
            "agents_dispatched": list[str],
            "findings": list[dict],
            "synthesized_report": str,    # Final unified analysis
            "severity": str,
            "timeline": list[str],
            "status": str,
        }
    """
```

### Orchestration Flow (pseudocode)
```
1. route_result = route_incident(description)
2. IF route_result.category == "OUT_OF_SCOPE":
       return "Not a production incident" message
3. IF route_result.confidence < 0.5:
       flag as uncertain, still dispatch but note low confidence
4. agent_config = get_agent_config(route_result.category)
5. result = run_agent_loop(agent_config, description, tools, state)
6. IF result.handoff_needed:
       second_config = get_agent_config(result.handoff_needed)
       second_result = run_agent_loop(second_config, description, tools, state)
       merge both results
7. synthesize final report from all findings in state
8. return full incident report
```

## Test Scenarios (validate against these)

| # | Input | Expected Routing | Key Checks |
|---|-------|-----------------|------------|
| 1 | "PostgreSQL connection pool exhausted. Active connections: 500/500." | DATABASE | Calls log_search("postgres"), runbook_lookup("connection_pool") |
| 2 | "SSL certificate for api.prod.flowstack.io expires in 2 hours." | NETWORK | Calls check_ssl("api.prod.flowstack.io") |
| 3 | "Unauthorized SSH login attempts from 45.33.92.* — 3,400 attempts." | SECURITY | Calls log_search("ssh"), severity HIGH |
| 4 | "Users can't log in." | APPLICATION (low confidence) | Does NOT hallucinate confident diagnosis |
| 5 | "When is the company all-hands meeting?" | OUT_OF_SCOPE | Returns "not a production incident" |
| 6 | "API latency p99 jumped to 4.2s. Correlated with database CPU spike." | Multi: APP + DB | Dispatches to BOTH agents, synthesizes |
| 7 | "Memory leak in payment-service pod. OOMKilled 3x in 1 hour." | APPLICATION | Calls log_search + metric_query |

## Surprise Twist (implement at 3:15)
**Cascading failure incident:**
"Database queries are returning stale data. Read replica is 47 minutes behind primary. Cause: replication slot dropped after unauthorized ALTER TABLE by user 'analytics_bot' — should only have SELECT permissions."

This MUST trigger:
1. Route to DATABASE first
2. DATABASE agent finds the unauthorized DDL command
3. Agent returns `handoff_needed: "SECURITY"`
4. Orchestrator auto-dispatches to SECURITY agent
5. Final report merges BOTH analyses with chronological timeline

## Coding Standards
- Type hints on all function signatures
- Docstrings on all public functions
- No external frameworks (no LangChain, CrewAI, etc.)
- Use `ollama` Python package or `openai` with base_url pointing to Ollama
- Handle errors gracefully — never crash on bad LLM output, retry or return partial results
- Print/log agent activity for the Streamlit UI to pick up

## Task Order
1. **First:** Build `agent_loop.py` — this is the foundation everything else depends on
2. **Second:** Build `orchestrator.py` — this wires everything together
3. **Third:** Test with mock interfaces (stub the imports if teammates' files aren't ready yet)
