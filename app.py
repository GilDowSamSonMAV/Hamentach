import streamlit as st
import time
import random
from state import IncidentState
from tools import log_search, runbook_lookup, metric_query, check_ssl

# Page config
st.set_page_config(page_title="Incident Response Orchestrator", layout="wide")

# Initialize session state for incident context and trace
if "incident_state" not in st.session_state:
    st.session_state.incident_state = IncidentState(incident_id=f"INC-{random.randint(1000, 9999)}")
if "trace" not in st.session_state:
    st.session_state.trace = []
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Mock Orchestration Loop ---
def mock_orchestration_loop(user_input: str):
    """
    Simulates the agent orchestration loop (Router -> Specialist -> Remediation).
    This will be replaced by actual LLM logic later.
    """
    state = st.session_state.incident_state
    
    # 1. Router Agent Active
    with st.status("🤖 Router Agent analyzing incident...", expanded=True) as status:
        time.sleep(1)
        st.write("Analyzing user report...")
        state.add_timeline_event("Router", "Received incident report", tool_used=None)
        st.session_state.trace.append({"agent": "Router", "action": "Classification", "detail": "Classified as Infrastructure/Database issue"})
        status.update(label="Router Agent: Handoff to Database Specialist", state="complete")

    # 2. Database Specialist Agent Active
    with st.status("🔍 DB Specialist investigating...", expanded=True) as status:
        time.sleep(1.5)
        st.write("Searching logs for database errors...")
        log_results = log_search("db-service")
        state.add_finding("DB Specialist", "Found log entry: PostgreSQL connection pool exhausted")
        state.add_timeline_event("DB Specialist", "Searched logs", tool_used="log_search")
        st.session_state.trace.append({"agent": "DB Specialist", "action": "Log Search", "detail": "Found connection pool exhaustion in db-service"})
        
        st.write("Checking connection metrics...")
        metric_results = metric_query("connections", "db-service")
        state.add_finding("DB Specialist", "Current connections at 500/500 (100% usage)")
        state.add_timeline_event("DB Specialist", "Queried metrics", tool_used="metric_query")
        st.session_state.trace.append({"agent": "DB Specialist", "action": "Metric Query", "detail": "Connections at max capacity (500)"})
        
        state.update_severity("DB Specialist", "High")
        status.update(label="DB Specialist: Investigation Complete", state="complete")

    # 3. Remediation Agent Active
    with st.status("🛠️ Remediation Agent active...", expanded=True) as status:
        time.sleep(1)
        st.write("Looking up remediation runbook...")
        runbook = runbook_lookup("DB_CONN_EXHAUSTED")
        state.add_finding("Remediation Agent", f"Following runbook: {runbook}")
        state.add_timeline_event("Remediation Agent", "Found runbook", tool_used="runbook_lookup")
        st.session_state.trace.append({"agent": "Remediation Agent", "action": "Runbook Lookup", "detail": "Retrieved DB_CONN_EXHAUSTED steps"})
        
        time.sleep(1)
        st.write("Drafting remediation plan...")
        status.update(label="Remediation Agent: Plan Ready", state="complete")

    return "Investigation complete. I've identified a database connection pool exhaustion in the 'db-service'. Severity has been upgraded to High. Remediation steps involve increasing max_connections and checking for long-running queries."

# --- Sidebar: Orchestration Trace ---
with st.sidebar:
    st.header("🕵️ Orchestration Trace")
    st.info("Real-time agent handoffs and tool executions")
    
    for entry in st.session_state.trace:
        with st.expander(f"**{entry['agent']}** - {entry['action']}", expanded=False):
            st.write(f"*Detail:* {entry['detail']}")
    
    if st.button("Reset State"):
        st.session_state.incident_state = IncidentState(incident_id=f"INC-{random.randint(1000, 9999)}")
        st.session_state.trace = []
        st.session_state.messages = []
        st.rerun()

# --- Main UI ---
st.title("🛡️ Incident Response Orchestrator")
st.caption(f"Connected to Shared Incident Context: **{st.session_state.incident_state.incident_id}**")

# Display Conversation
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# User Input
if prompt := st.chat_input("Report an incident (e.g., 'The payment service is down')"):
    # Add user message to chat
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Run Mock Orchestration
    with st.chat_message("assistant"):
        response = mock_orchestration_loop(prompt)
        st.markdown(response)
        st.session_state.messages.append({"role": "assistant", "content": response})

# Findings & Timeline Display (Bottom of Page)
st.divider()
col1, col2 = st.columns(2)

with col1:
    st.subheader("📋 Key Findings")
    for finding in st.session_state.incident_state.findings:
        st.success(finding)

with col2:
    st.subheader("⏳ Incident Timeline")
    for event in reversed(st.session_state.incident_state.timeline):
        st.write(f"**{event['timestamp']}** | **{event['agent']}**: {event['description']} " + 
                 (f"*(Tool: `{event['tool']}`)*" if event['tool'] else ""))
