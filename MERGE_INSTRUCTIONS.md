# MERGE TASK: Integrate Git repo code with local files

## Context
The team pulled code from GitHub into this repo. There are now TWO versions of agent_loop and orchestrator:
- **My local versions** (root level): `agent_loop.py`, `orchestrator.py` — these import from `stubs/` package
- **Git repo versions** (src/ package): `src/agent_loop.py`, `src/orchestrator.py` — these import from `src/` package and use a different interface

## What happened
My teammates (Gil, Liron) built their files (`state.py`, `tools.py`, `mock_data.py`, `app.py`, `src/router.py`, `src/agents.py`) and committed them.
Meanwhile I built `agent_loop.py` and `orchestrator.py` locally using stub imports.
Now we need ONE unified codebase that works.

## Critical differences to reconcile

### 1. State interface mismatch
My code (stubs) uses:
```python
state.add_finding(agent, finding_str)
state.set_severity(severity)
state.add_tool_call(agent, tool, args, result)
state.add_timeline_event(event_str)
```

The repo's `state.py` uses:
```python
state.add_finding(agent_name, finding)  # similar
state.update_severity(agent_name, new_severity)  # different name + takes agent_name
state.add_timeline_event(agent_name, description, tool_used=None)  # takes agent_name + description
```

The repo has a `src/state_adapter.py` that bridges this gap. It wraps partner's state.py for the src/ orchestrator.

### 2. Import paths
My files: `from stubs.config import ...`
Repo files: `from .config import ...` (relative imports inside src/ package)

### 3. Tool function signatures
My stubs: `log_search(query, service=None, limit=10)`, `check_ssl(hostname)`
Repo tools.py: `log_search(query)`, `check_ssl(domain)` — different arg names and signatures

### 4. Agent loop interface
My agent_loop uses TOOL_CALL/FINAL_ANSWER text parsing format
Repo's src/agent_loop.py uses JSON action format: `{"action": "tool_call", "tool": "...", "args": {...}}`

### 5. Router
My code calls: `route_incident(description)` returning `{"category", "confidence", "reasoning"}`
Repo's router returns: `{"category", "confidence", "reasoning", "ambiguous"}` — adds ambiguous flag

### 6. Orchestrator interface
My orchestrator: `handle_incident(description, state, on_agent_start=None, on_agent_complete=None, on_tool_call=None)`
Repo orchestrator: `handle_incident(description, state, tool_registry)` — takes tool_registry, no callbacks

## YOUR TASK

Merge into ONE working system. The priority is: **the repo's src/ structure wins for architecture**, but preserve the best ideas from both.

Steps:
1. Read ALL files in both root and src/ directories carefully
2. Compare my agent_loop.py vs src/agent_loop.py — keep the BETTER json parsing (mine has brace-counting + 4-attempt repair) but use the repo's cleaner interface (action-based JSON format)
3. Compare my orchestrator.py vs src/orchestrator.py — keep the repo's version since it already has: escalation queue, synthesis via LLM, state adapter pattern
4. Make sure the final src/agent_loop.py has my robust JSON parsing (extract_balanced_json + _try_parse_json) merged into the repo's extract_json function
5. Update CLAUDE.md to reflect the final merged architecture
6. Delete the stubs/ folder — we don't need it anymore, real files exist
7. Delete root-level agent_loop.py and orchestrator.py — the src/ versions are the canonical ones
8. Delete test_all.py — the repo has tests/test_system.py and tests/hackathon_tests.py
9. Run `python -m pytest tests/test_system.py -v` to verify everything passes
10. Run `streamlit run app.py` to verify the UI works (just start it, don't wait for interaction)

## IMPORTANT
- Do NOT break the app.py Streamlit UI — it imports from src/ and from root state.py/tools.py
- The state_adapter.py bridges partner's state.py to our src/ interface — keep it
- Keep ALL test files in tests/
- After merge, the only Python files at root should be: app.py, state.py, tools.py, mock_data.py, main.py
- All our code (agent_loop, orchestrator, router, agents, config, state_adapter) lives in src/
