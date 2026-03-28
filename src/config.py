"""Shared configuration — model names, constants. All LLM calls use local Ollama."""

OLLAMA_MODEL = "qwen2.5:14b"
OLLAMA_BASE_URL = "http://localhost:11434"

AGENT_CATEGORIES = ["DATABASE", "NETWORK", "SECURITY", "APPLICATION"]

MAX_TOOL_CALLS_PER_TURN = 5  # safety limit for agent loop
