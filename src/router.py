"""Incident classifier — uses local Ollama for routing incidents to specialists."""

import logging

import ollama

from .config import OLLAMA_MODEL, AGENT_CATEGORIES
from .agent_loop import extract_json

logger = logging.getLogger(__name__)

ROUTER_SYSTEM_PROMPT = """\
You are an expert SRE incident classifier. Your job is to categorize production incidents
into exactly one of these categories:

- DATABASE: Issues involving databases (PostgreSQL, MySQL, Redis, replication, connection pools, queries, etc.)
- NETWORK: Issues involving networking (SSL/TLS, DNS, load balancers, connectivity, latency between services, firewalls, etc.)
- SECURITY: Issues involving security (unauthorized access, brute force, CVEs, permission escalation, data breach, etc.)
- APPLICATION: Issues involving application code (memory leaks, crashes, high latency in app layer, deployment failures, OOM, etc.)
- OUT_OF_SCOPE: The input is clearly NOT a production incident (meeting questions, general knowledge, chit-chat, etc.)

Rules:
1. Choose exactly ONE primary category.
2. Assign a confidence score between 0.0 and 1.0.
3. If the incident spans multiple domains (e.g., "API latency + database CPU spike"), pick the MOST LIKELY root-cause domain as the primary category but note the multi-domain nature in your reasoning.
4. If the description is vague and could fit multiple categories, pick your best guess but set confidence below 0.6.
5. Respond with ONLY this JSON — no extra text:

{"category": "<CATEGORY>", "confidence": <float>, "reasoning": "<one sentence>"}
"""


def route_incident(description: str) -> dict:
    """Classify an incident description into a category using local Ollama.

    Returns:
        dict with keys: category, confidence, reasoning, ambiguous (bool)
    """
    logger.info(f"Routing incident: {description[:100]}...")

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": description},
        ],
    )

    raw = response["message"]["content"].strip()
    logger.debug(f"Router raw response: {raw}")

    # Parse JSON robustly (reuse extract_json from agent_loop)
    parsed = extract_json(raw)
    if parsed is None:
        logger.error(f"Could not parse router response: {raw}")
        parsed = {"category": "OUT_OF_SCOPE", "confidence": 0.0, "reasoning": "Failed to parse LLM output"}

    # Validate and normalise
    category = parsed.get("category", "OUT_OF_SCOPE").upper()
    if category not in AGENT_CATEGORIES and category != "OUT_OF_SCOPE":
        logger.warning(f"Router returned unknown category '{category}', falling back to OUT_OF_SCOPE")
        category = "OUT_OF_SCOPE"

    confidence = float(parsed.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))

    reasoning = parsed.get("reasoning", "No reasoning provided")
    ambiguous = confidence < 0.6

    result = {
        "category": category,
        "confidence": confidence,
        "reasoning": reasoning,
        "ambiguous": ambiguous,
    }

    logger.info(f"Routing result: {category} (confidence={confidence:.2f}, ambiguous={ambiguous})")
    return result
