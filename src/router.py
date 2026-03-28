"""Incident classifier — uses Groq for fast inference to route incidents to specialists."""

import json
import logging

from openai import OpenAI

from .config import GROQ_API_KEY, GROQ_BASE_URL, GROQ_MODEL, AGENT_CATEGORIES

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
    """Classify an incident description into a category using Groq LLM.

    Returns:
        dict with keys: category, confidence, reasoning, ambiguous (bool)
    """
    client = OpenAI(base_url=GROQ_BASE_URL, api_key=GROQ_API_KEY)

    logger.info(f"Routing incident: {description[:100]}...")

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": description},
        ],
        temperature=0.1,
        max_tokens=256,
    )

    raw = response.choices[0].message.content.strip()
    logger.debug(f"Router raw response: {raw}")

    # Parse JSON robustly
    parsed = _parse_router_response(raw)

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


def _parse_router_response(raw: str) -> dict:
    """Parse the router LLM response, handling markdown fences and malformed output."""
    import re

    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try markdown fence
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try first JSON object
    brace_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    logger.error(f"Could not parse router response: {raw}")
    return {"category": "OUT_OF_SCOPE", "confidence": 0.0, "reasoning": "Failed to parse LLM output"}
