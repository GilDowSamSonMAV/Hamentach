from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional

@dataclass
class IncidentState:
    """
    Shared incident context that allows multiple agents to read and 
    update the state of an investigation.
    """
    incident_id: str
    findings: List[str] = field(default_factory=list)
    severity: str = "Low"
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "Active"

    def add_finding(self, agent_name: str, finding: str):
        """Appends a new finding to the state and logs it in the timeline."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.findings.append(finding)
        self.add_timeline_event(agent_name, f"New Finding: {finding}")

    def update_severity(self, agent_name: str, new_severity: str):
        """Updates the incident severity."""
        self.severity = new_severity
        self.add_timeline_event(agent_name, f"Severity updated to: {new_severity}")

    def add_timeline_event(self, agent_name: str, description: str, tool_used: Optional[str] = None):
        """Records an event in the incident timeline."""
        event = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "agent": agent_name,
            "description": description,
            "tool": tool_used
        }
        self.timeline.append(event)

    def get_context_summary(self) -> str:
        """Returns a string representation of the state for LLM context."""
        return (
            f"Incident ID: {self.incident_id}\n"
            f"Severity: {self.severity}\n"
            f"Findings: {', '.join(self.findings) if self.findings else 'None'}\n"
            f"Status: {self.status}"
        )
