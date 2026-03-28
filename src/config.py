"""Shared configuration — API keys, model names, constants."""

import os

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

OLLAMA_MODEL = "qwen2.5:14b"
OLLAMA_BASE_URL = "http://localhost:11434"

AGENT_CATEGORIES = ["DATABASE", "NETWORK", "SECURITY", "APPLICATION"]

MAX_TOOL_CALLS_PER_TURN = 5  # safety limit for agent loop
