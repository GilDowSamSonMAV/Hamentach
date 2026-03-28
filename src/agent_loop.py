"""Generic agent execution engine — the ReAct loop powering every specialist agent."""

import json
import logging
import re
from typing import Any, Callable

import ollama

from .config import OLLAMA_MODEL, MAX_TOOL_CALLS_PER_TURN

logger = logging.getLogger(__name__)


def extract_json(text: str) -> dict | None:
    """Extract a JSON object from LLM output, handling markdown fences and prose."""
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code fences
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding first { ... } block (greedy match for outermost braces)
    brace_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def run_agent_loop(
    system_prompt: str,
    incident_description: str,
    tool_registry: dict[str, Callable],
    allowed_tools: list[str],
    state: Any,
    incident_id: str,
    agent_name: str,
    max_iterations: int | None = None,
) -> dict:
    """Run a specialist agent through the observe-think-act loop.

    The agent converses with the local LLM, calling tools until it reaches
    a final answer or hits the iteration limit.

    Returns:
        dict with keys: severity, root_cause, evidence, remediation, escalate_to
    """
    if max_iterations is None:
        max_iterations = MAX_TOOL_CALLS_PER_TURN

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Incident report:\n{incident_description}"},
    ]

    state.add_timeline_event(incident_id, f"Agent '{agent_name}' started analysis")

    for iteration in range(max_iterations):
        logger.info(f"[{agent_name}] iteration {iteration + 1}/{max_iterations}")

        response = ollama.chat(model=OLLAMA_MODEL, messages=messages)
        raw_content = response["message"]["content"]
        logger.debug(f"[{agent_name}] raw LLM response: {raw_content[:300]}")

        parsed = extract_json(raw_content)

        if parsed is None:
            logger.warning(f"[{agent_name}] Could not parse JSON from LLM output, requesting retry")
            messages.append({"role": "assistant", "content": raw_content})
            messages.append({
                "role": "user",
                "content": (
                    "Your response was not valid JSON. "
                    "Please respond with ONLY a JSON object: "
                    'either {"action": "tool_call", "tool": "...", "args": {...}} '
                    'or {"action": "final_answer", "severity": "...", "root_cause": "...", '
                    '"evidence": [...], "remediation": [...], "escalate_to": null}'
                ),
            })
            continue

        action = parsed.get("action")

        # --- FINAL ANSWER ---
        if action == "final_answer":
            result = {
                "severity": parsed.get("severity", "MEDIUM"),
                "root_cause": parsed.get("root_cause", "Unknown"),
                "evidence": parsed.get("evidence", []),
                "remediation": parsed.get("remediation", []),
                "escalate_to": parsed.get("escalate_to"),
            }
            state.add_finding(incident_id, agent_name, result)
            state.add_timeline_event(
                incident_id,
                f"Agent '{agent_name}' completed — severity: {result['severity']}",
            )
            logger.info(f"[{agent_name}] final answer: severity={result['severity']}")
            return result

        # --- TOOL CALL ---
        if action == "tool_call":
            tool_name = parsed.get("tool", "")
            tool_args = parsed.get("args", {})

            if tool_name not in allowed_tools:
                error_msg = f"Tool '{tool_name}' is not allowed. Allowed tools: {allowed_tools}"
                logger.warning(f"[{agent_name}] {error_msg}")
                messages.append({"role": "assistant", "content": raw_content})
                messages.append({"role": "user", "content": error_msg})
                continue

            if tool_name not in tool_registry:
                error_msg = f"Tool '{tool_name}' not found in registry."
                logger.warning(f"[{agent_name}] {error_msg}")
                messages.append({"role": "assistant", "content": raw_content})
                messages.append({"role": "user", "content": error_msg})
                continue

            logger.info(f"[{agent_name}] calling tool '{tool_name}' with args {tool_args}")
            state.add_timeline_event(incident_id, f"Agent '{agent_name}' called tool: {tool_name}")

            try:
                tool_result = tool_registry[tool_name](**tool_args)
            except Exception as e:
                tool_result = f"Tool execution error: {e}"
                logger.error(f"[{agent_name}] tool '{tool_name}' failed: {e}")

            messages.append({"role": "assistant", "content": raw_content})
            messages.append({
                "role": "user",
                "content": f"Tool '{tool_name}' returned:\n{json.dumps(tool_result, default=str)}",
            })
            continue

        # --- UNRECOGNISED ACTION ---
        logger.warning(f"[{agent_name}] unrecognised action: {action}")
        messages.append({"role": "assistant", "content": raw_content})
        messages.append({
            "role": "user",
            "content": (
                f"Unrecognised action '{action}'. "
                "Use 'tool_call' to call a tool or 'final_answer' to give your analysis."
            ),
        })

    # --- ITERATION LIMIT REACHED — force a final answer ---
    logger.warning(f"[{agent_name}] hit iteration limit ({max_iterations}), forcing final answer")
    state.add_timeline_event(incident_id, f"Agent '{agent_name}' reached iteration limit — forcing answer")

    messages.append({
        "role": "user",
        "content": (
            "You have used all available tool calls. "
            "You MUST now respond with your final_answer JSON based on the evidence gathered so far."
        ),
    })

    response = ollama.chat(model=OLLAMA_MODEL, messages=messages)
    raw_content = response["message"]["content"]
    parsed = extract_json(raw_content)

    if parsed and parsed.get("action") == "final_answer":
        result = {
            "severity": parsed.get("severity", "MEDIUM"),
            "root_cause": parsed.get("root_cause", "Unknown"),
            "evidence": parsed.get("evidence", []),
            "remediation": parsed.get("remediation", []),
            "escalate_to": parsed.get("escalate_to"),
        }
    else:
        result = {
            "severity": "MEDIUM",
            "root_cause": "Agent could not determine root cause within iteration limit",
            "evidence": [],
            "remediation": ["Manual investigation required"],
            "escalate_to": None,
        }

    state.add_finding(incident_id, agent_name, result)
    state.add_timeline_event(
        incident_id,
        f"Agent '{agent_name}' completed (forced) — severity: {result['severity']}",
    )
    return result
