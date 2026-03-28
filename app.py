import streamlit as st
import logging
from state import IncidentState
from tools import log_search, runbook_lookup, metric_query, check_ssl
from src.orchestrator import handle_incident
from src.state_adapter import StateAdapter

# Configure logging so agent activity shows in the terminal
logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")

# Page config
st.set_page_config(page_title="HaMenate'ach — Incident Response", layout="wide")

# Build the real tool registry from partner's tools.py
TOOL_REGISTRY = {
    "log_search": log_search,
    "runbook_lookup": runbook_lookup,
    "metric_query": metric_query,
    "check_ssl": check_ssl,
}

# Initialize session state
if "adapter" not in st.session_state:
    st.session_state.adapter = StateAdapter(IncidentState)
if "reports" not in st.session_state:
    st.session_state.reports = []
if "messages" not in st.session_state:
    st.session_state.messages = []


def run_real_orchestration(user_input: str) -> dict:
    """Run the actual LLM-powered multi-agent orchestration pipeline."""
    report = handle_incident(
        description=user_input,
        state=st.session_state.adapter,
        tool_registry=TOOL_REGISTRY,
    )
    st.session_state.reports.append(report)
    return report


def format_report(report: dict) -> str:
    """Format the orchestrator report into readable markdown."""
    if report.get("incident_id") is None:
        return report["synthesis"]["summary"]

    routing = report["routing"]
    lines = [
        f"**Incident** `{report['incident_id']}` | **Severity: {report['overall_severity']}**",
        f"**Routed to:** {routing['category']} (confidence: {routing['confidence']:.0%})",
        "",
    ]

    if routing.get("ambiguous"):
        lines.append("> Routing was ambiguous — confidence below 60%")
        lines.append("")

    # Agents dispatched
    lines.append(f"**Agents dispatched:** {', '.join(report['agents_dispatched'])}")
    lines.append("")

    # Synthesis
    synth = report.get("synthesis", {})
    if synth.get("summary"):
        lines.append(f"### Summary\n{synth['summary']}")
    if synth.get("root_cause"):
        lines.append(f"\n**Root cause:** {synth['root_cause']}")
    if synth.get("causal_chain"):
        lines.append(f"\n**Causal chain:** {synth['causal_chain']}")

    # Remediation
    steps = synth.get("remediation_steps", [])
    if steps:
        lines.append("\n### Remediation")
        for i, step in enumerate(steps, 1):
            lines.append(f"{i}. {step}")

    # Prevention
    prevention = synth.get("prevention", [])
    if prevention:
        lines.append("\n### Prevention")
        for p in prevention:
            lines.append(f"- {p}")

    return "\n".join(lines)


# --- Sidebar: Orchestration Trace ---
with st.sidebar:
    st.header("Orchestration Trace")
    st.info("Real-time agent handoffs and tool executions")

    for report in st.session_state.reports:
        if report.get("timeline"):
            iid = report.get("incident_id", "?")
            with st.expander(f"**{iid}** — {report.get('overall_severity', '?')}", expanded=True):
                for event in report["timeline"]:
                    st.write(f"- {event}")

    if st.button("Reset"):
        st.session_state.adapter = StateAdapter(IncidentState)
        st.session_state.reports = []
        st.session_state.messages = []
        st.rerun()

# --- Main UI ---
st.title("HaMenate'ach — Incident Response Orchestrator")
st.caption("Multi-agent SRE system with automatic cross-domain escalation")

# Display conversation
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# User input
if prompt := st.chat_input("Report an incident (e.g., 'PostgreSQL connection pool exhausted')"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Routing and dispatching agents..."):
            report = run_real_orchestration(prompt)
            response = format_report(report)
        st.markdown(response)
        st.session_state.messages.append({"role": "assistant", "content": response})

# Findings display
if st.session_state.reports:
    st.divider()
    latest = st.session_state.reports[-1]
    if latest.get("findings"):
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Key Findings")
            for finding in latest["findings"]:
                agent = finding.get("agent", "unknown")
                root = finding.get("root_cause", str(finding))
                sev = finding.get("severity", "?")
                st.success(f"**{agent}** [{sev}]: {root}")
        with col2:
            st.subheader("Timeline")
            for event in latest.get("timeline", []):
                st.write(f"- {event}")
