"""Adapter bridging partner's IncidentState to the interface our orchestrator expects.

Partner's IncidentState (state.py):
  - __init__(incident_id)
  - add_finding(agent_name: str, finding: str)
  - update_severity(agent_name: str, new_severity: str)
  - add_timeline_event(agent_name: str, description: str, tool_used: str | None)
  - get_context_summary() -> str

Our orchestrator expects:
  - create_incident(description) -> str
  - add_finding(incident_id, agent, finding_dict)
  - get_findings(incident_id) -> list[dict]
  - set_severity(incident_id, severity)
  - get_state(incident_id) -> dict
  - add_timeline_event(incident_id, event_str)
"""

import json
import random
from typing import Any


class StateAdapter:
    """Wraps the partner's IncidentState to match our orchestrator's interface."""

    def __init__(self, incident_state_cls: type):
        self._cls = incident_state_cls
        self._incidents: dict[str, Any] = {}
        self._findings: dict[str, list[dict]] = {}

    def create_incident(self, description: str) -> str:
        incident_id = f"INC-{random.randint(1000, 9999)}"
        state = self._cls(incident_id=incident_id)
        self._incidents[incident_id] = state
        self._findings[incident_id] = []
        return incident_id

    def add_finding(self, incident_id: str, agent: str, finding: dict):
        state = self._incidents[incident_id]
        # Store structured finding for our orchestrator
        self._findings[incident_id].append({"agent": agent, **finding})
        # Also push to partner's state as a readable string
        summary = finding.get("root_cause", json.dumps(finding, default=str))
        state.add_finding(agent, summary)

    def get_findings(self, incident_id: str) -> list[dict]:
        return self._findings.get(incident_id, [])

    def set_severity(self, incident_id: str, severity: str):
        state = self._incidents[incident_id]
        state.update_severity("orchestrator", severity)

    def get_state(self, incident_id: str) -> dict:
        state = self._incidents[incident_id]
        return {
            "description": "",
            "findings": self._findings.get(incident_id, []),
            "severity": state.severity,
            "timeline": [
                e["description"] for e in state.timeline
            ],
        }

    def add_timeline_event(self, incident_id: str, event: str):
        state = self._incidents[incident_id]
        state.add_timeline_event("system", event)

    def get_partner_state(self, incident_id: str) -> Any:
        """Access the raw partner IncidentState for UI rendering."""
        return self._incidents.get(incident_id)
