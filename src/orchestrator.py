"""Main orchestration engine — manages the full incident response pipeline."""

import json
import logging
from typing import Any, Callable

import ollama

from .config import OLLAMA_MODEL
from .router import route_incident
from .agents import AGENTS
from .agent_loop import run_agent_loop, extract_json

logger = logging.getLogger(__name__)

MAX_ESCALATIONS = 3  # safety limit for escalation chains

SYNTHESIS_SYSTEM_PROMPT = """\
You are an SRE incident synthesis engine. Given findings from one or more specialist agents,
produce a unified incident report.

Your output must be ONLY this JSON — no extra text:
{
  "summary": "<2-3 sentence executive summary of the incident>",
  "root_cause": "<single clear root cause statement>",
  "causal_chain": "<if this is a cascading failure, describe the chain of events in order; otherwise null>",
  "overall_severity": "LOW|MEDIUM|HIGH|CRITICAL",
  "remediation_steps": ["<ordered list of actions to resolve>"],
  "prevention": ["<list of changes to prevent recurrence>"]
}

Rules:
- The overall_severity is the HIGHEST severity across all agent findings.
- If multiple agents contributed findings, identify causal relationships between them.
- Remediation steps should be ordered by urgency (most critical first).
- Be specific — reference actual services, metrics, and evidence from the findings.
"""


def handle_incident(
    description: str,
    state: Any,
    tool_registry: dict[str, Callable],
) -> dict:
    """Execute the full incident response pipeline.

    Pipeline:
    1. Route incident to category
    2. Reject if OUT_OF_SCOPE
    3. Create incident in shared state
    4. Dispatch specialist agent(s) with escalation support
    5. Synthesize final report

    Returns:
        Full incident report dict.
    """
    logger.info(f"=== Handling incident: {description[:100]}... ===")

    # --- Step 1: Route ---
    routing = route_incident(description)
    category = routing["category"]

    # --- Step 2: Reject out-of-scope ---
    if category == "OUT_OF_SCOPE":
        logger.info("Incident classified as OUT_OF_SCOPE — no agent dispatched")
        return {
            "incident_id": None,
            "routing": routing,
            "agents_dispatched": [],
            "findings": [],
            "synthesis": {
                "summary": "This does not appear to be a production incident. No investigation was performed.",
                "root_cause": None,
                "causal_chain": None,
                "overall_severity": None,
                "remediation_steps": [],
                "prevention": [],
            },
            "timeline": [],
            "overall_severity": None,
        }

    # --- Step 3: Create incident ---
    incident_id = state.create_incident(description)
    state.add_timeline_event(incident_id, f"Incident created — routed to {category}")
    if routing["ambiguous"]:
        state.add_timeline_event(incident_id, f"Routing is ambiguous (confidence={routing['confidence']:.2f})")

    # --- Step 4: Dispatch agents with escalation chain ---
    agents_dispatched: list[str] = []
    dispatched_categories: set[str] = set()
    escalation_queue: list[str] = [category]

    while escalation_queue and len(dispatched_categories) < MAX_ESCALATIONS:
        current_category = escalation_queue.pop(0)

        if current_category in dispatched_categories:
            logger.info(f"Skipping duplicate dispatch for {current_category}")
            continue

        if current_category not in AGENTS:
            logger.warning(f"No agent defined for category '{current_category}', skipping")
            continue

        dispatched_categories.add(current_category)
        agent_def = AGENTS[current_category]
        agent_name = f"{current_category}_agent"
        agents_dispatched.append(agent_name)

        logger.info(f"Dispatching {agent_name}")
        state.add_timeline_event(incident_id, f"Dispatched {agent_name}")

        # Build context that includes prior findings for multi-agent handoff
        context = description
        prior_findings = state.get_findings(incident_id)
        if prior_findings:
            context += "\n\n--- Prior agent findings ---\n"
            for f in prior_findings:
                context += json.dumps(f, default=str) + "\n"

        result = run_agent_loop(
            system_prompt=agent_def["system_prompt"],
            incident_description=context,
            tool_registry=tool_registry,
            allowed_tools=agent_def["allowed_tools"],
            state=state,
            incident_id=incident_id,
            agent_name=agent_name,
        )

        # Set severity on state
        if result.get("severity"):
            state.set_severity(incident_id, result["severity"])

        # Check for escalation
        escalate_to = result.get("escalate_to")
        if escalate_to and escalate_to in AGENTS and escalate_to not in dispatched_categories:
            logger.info(f"{agent_name} escalated to {escalate_to}")
            state.add_timeline_event(incident_id, f"{agent_name} escalated to {escalate_to}")
            escalation_queue.append(escalate_to)

    # --- Step 5: Collect findings and synthesize ---
    findings = state.get_findings(incident_id)
    full_state = state.get_state(incident_id)
    timeline = full_state.get("timeline", [])

    synthesis = _synthesize_report(description, findings, agents_dispatched)

    # Determine overall severity (highest across all findings)
    severity_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    overall_severity = "LOW"
    for finding in findings:
        sev = finding.get("severity", "LOW") if isinstance(finding, dict) else "LOW"
        if severity_order.get(sev, 0) > severity_order.get(overall_severity, 0):
            overall_severity = sev

    report = {
        "incident_id": incident_id,
        "routing": routing,
        "agents_dispatched": agents_dispatched,
        "findings": findings,
        "synthesis": synthesis,
        "timeline": timeline,
        "overall_severity": overall_severity,
    }

    logger.info(f"=== Incident {incident_id} complete — severity: {overall_severity} ===")
    return report


def _synthesize_report(
    description: str,
    findings: list[dict],
    agents_dispatched: list[str],
) -> dict:
    """Use local Ollama to synthesize a unified report from all agent findings."""
    user_content = (
        f"Incident description:\n{description}\n\n"
        f"Agents dispatched: {', '.join(agents_dispatched)}\n\n"
        f"Agent findings:\n{json.dumps(findings, indent=2, default=str)}"
    )

    logger.info("Synthesizing final report via Ollama")

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )

    raw = response["message"]["content"].strip()
    logger.debug(f"Synthesis raw response: {raw}")

    parsed = extract_json(raw)
    if parsed:
        return parsed

    logger.error(f"Could not parse synthesis response: {raw}")
    return {
        "summary": raw[:500],
        "root_cause": "See agent findings",
        "causal_chain": None,
        "overall_severity": "MEDIUM",
        "remediation_steps": ["Review agent findings manually"],
        "prevention": [],
    }
