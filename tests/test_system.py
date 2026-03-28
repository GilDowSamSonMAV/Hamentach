"""
Integration tests for the SRE multi-agent incident response system.
Covers all 7 hackathon brief scenarios + the surprise cascading failure twist.

Run with: pytest tests/test_system.py -v
"""

import json
import pytest
from unittest.mock import patch, MagicMock, call

from src.config import AGENT_CATEGORIES
from src.router import route_incident
from src.agents import AGENTS
from src.agent_loop import run_agent_loop, extract_json
from src.orchestrator import handle_incident


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class FakeState:
    """Minimal IncidentState stub for testing."""

    def __init__(self):
        self.incidents: dict[str, dict] = {}
        self._counter = 0

    def create_incident(self, description: str) -> str:
        self._counter += 1
        iid = f"INC-{self._counter:04d}"
        self.incidents[iid] = {
            "description": description,
            "findings": [],
            "severity": None,
            "timeline": [],
        }
        return iid

    def add_finding(self, incident_id: str, agent: str, finding: dict):
        self.incidents[incident_id]["findings"].append({"agent": agent, **finding})

    def get_findings(self, incident_id: str) -> list[dict]:
        return self.incidents[incident_id]["findings"]

    def set_severity(self, incident_id: str, severity: str):
        self.incidents[incident_id]["severity"] = severity

    def get_state(self, incident_id: str) -> dict:
        return self.incidents[incident_id]

    def add_timeline_event(self, incident_id: str, event: str):
        self.incidents[incident_id]["timeline"].append(event)


@pytest.fixture
def state():
    return FakeState()


@pytest.fixture
def tool_registry():
    """Mock tool registry — records all calls for assertion."""
    registry = {}
    for name in ["log_search", "runbook_lookup", "metric_query", "check_ssl"]:
        mock_fn = MagicMock(name=name, return_value={"status": "ok", "data": f"mock result from {name}"})
        registry[name] = mock_fn
    return registry


def _ollama_response(content: str):
    """Build a mock Ollama chat response."""
    return {"message": {"content": content}}


# ---------------------------------------------------------------------------
# Unit tests for extract_json
# ---------------------------------------------------------------------------

class TestExtractJson:
    def test_plain_json(self):
        assert extract_json('{"action": "final_answer", "severity": "HIGH"}') == {
            "action": "final_answer",
            "severity": "HIGH",
        }

    def test_markdown_fence(self):
        text = "Here is my response:\n```json\n{\"action\": \"tool_call\", \"tool\": \"log_search\"}\n```"
        result = extract_json(text)
        assert result["action"] == "tool_call"

    def test_prose_around_json(self):
        text = "I think this is the answer:\n{\"action\": \"final_answer\", \"severity\": \"LOW\"}\nDone."
        result = extract_json(text)
        assert result["severity"] == "LOW"

    def test_garbage_returns_none(self):
        assert extract_json("no json here at all") is None


# ---------------------------------------------------------------------------
# Router tests (mock Ollama)
# ---------------------------------------------------------------------------

class TestRouter:
    @patch("src.router.ollama")
    def test_1_postgres_connection_pool(self, mock_ollama):
        mock_ollama.chat.return_value = _ollama_response(
            '{"category": "DATABASE", "confidence": 0.92, "reasoning": "PostgreSQL connection pool exhaustion is a database issue."}'
        )
        result = route_incident("PostgreSQL connection pool exhausted — all 100 connections in use")
        assert result["category"] == "DATABASE"
        assert result["confidence"] >= 0.6
        assert result["ambiguous"] is False

    @patch("src.router.ollama")
    def test_2_ssl_cert_expiring(self, mock_ollama):
        mock_ollama.chat.return_value = _ollama_response(
            '{"category": "NETWORK", "confidence": 0.95, "reasoning": "SSL certificate expiry is a network/TLS issue."}'
        )
        result = route_incident("SSL certificate for api.example.com expires in 2 days")
        assert result["category"] == "NETWORK"

    @patch("src.router.ollama")
    def test_3_ssh_brute_force(self, mock_ollama):
        mock_ollama.chat.return_value = _ollama_response(
            '{"category": "SECURITY", "confidence": 0.97, "reasoning": "SSH brute force is a security incident."}'
        )
        result = route_incident("Detected 5000+ failed SSH login attempts from 203.0.113.42 in the last hour")
        assert result["category"] == "SECURITY"

    @patch("src.router.ollama")
    def test_4_ambiguous_users_cant_login(self, mock_ollama):
        mock_ollama.chat.return_value = _ollama_response(
            '{"category": "APPLICATION", "confidence": 0.45, "reasoning": "Vague — could be auth service, database, or network."}'
        )
        result = route_incident("Users can't log in.")
        assert result["ambiguous"] is True or result["confidence"] < 0.6

    @patch("src.router.ollama")
    def test_5_out_of_scope(self, mock_ollama):
        mock_ollama.chat.return_value = _ollama_response(
            '{"category": "OUT_OF_SCOPE", "confidence": 0.99, "reasoning": "Not a production incident."}'
        )
        result = route_incident("When is the company all-hands meeting?")
        assert result["category"] == "OUT_OF_SCOPE"

    @patch("src.router.ollama")
    def test_6_multi_domain(self, mock_ollama):
        mock_ollama.chat.return_value = _ollama_response(
            '{"category": "APPLICATION", "confidence": 0.72, "reasoning": "API latency with DB CPU spike — app layer is primary but database is involved."}'
        )
        result = route_incident("API latency spiking to 12s p99 while database CPU is at 98%")
        assert result["category"] in AGENT_CATEGORIES

    @patch("src.router.ollama")
    def test_7_memory_leak(self, mock_ollama):
        mock_ollama.chat.return_value = _ollama_response(
            '{"category": "APPLICATION", "confidence": 0.93, "reasoning": "Memory leak in a service is an application issue."}'
        )
        result = route_incident("Memory leak in payment-service — RSS growing 50MB/hour")
        assert result["category"] == "APPLICATION"


# ---------------------------------------------------------------------------
# Agent loop tests (mock Ollama)
# ---------------------------------------------------------------------------

class TestAgentLoop:
    @patch("src.agent_loop.ollama")
    def test_agent_calls_tool_then_final_answer(self, mock_ollama, state, tool_registry):
        incident_id = state.create_incident("test incident")
        mock_ollama.chat.side_effect = [
            _ollama_response('{"action": "tool_call", "tool": "log_search", "args": {"query": "error", "service": "db"}}'),
            _ollama_response('{"action": "final_answer", "severity": "HIGH", "root_cause": "Connection pool exhausted", "evidence": ["error logs found"], "remediation": ["Increase pool size"], "escalate_to": null}'),
        ]
        result = run_agent_loop(
            system_prompt="You are a DB specialist.",
            incident_description="test incident",
            tool_registry=tool_registry,
            allowed_tools=["log_search", "runbook_lookup", "metric_query"],
            state=state, incident_id=incident_id, agent_name="DATABASE_agent",
        )
        assert result["severity"] == "HIGH"
        assert result["root_cause"] == "Connection pool exhausted"
        assert len(result["evidence"]) > 0
        tool_registry["log_search"].assert_called_once()

    @patch("src.agent_loop.ollama")
    def test_agent_respects_allowed_tools(self, mock_ollama, state, tool_registry):
        incident_id = state.create_incident("test incident")
        mock_ollama.chat.side_effect = [
            _ollama_response('{"action": "tool_call", "tool": "check_ssl", "args": {"domain": "example.com"}}'),
            _ollama_response('{"action": "final_answer", "severity": "LOW", "root_cause": "N/A", "evidence": [], "remediation": [], "escalate_to": null}'),
        ]
        run_agent_loop(
            system_prompt="You are a DB specialist.",
            incident_description="test",
            tool_registry=tool_registry,
            allowed_tools=["log_search"],
            state=state, incident_id=incident_id, agent_name="DATABASE_agent",
        )
        tool_registry["check_ssl"].assert_not_called()

    @patch("src.agent_loop.ollama")
    def test_agent_escalation(self, mock_ollama, state, tool_registry):
        incident_id = state.create_incident("test incident")
        mock_ollama.chat.return_value = _ollama_response(
            '{"action": "final_answer", "severity": "CRITICAL", "root_cause": "Unauthorized ALTER TABLE", "evidence": ["replication slot dropped"], "remediation": ["Revoke permissions"], "escalate_to": "SECURITY"}'
        )
        result = run_agent_loop(
            system_prompt="You are a DB specialist.",
            incident_description="test",
            tool_registry=tool_registry,
            allowed_tools=["log_search"],
            state=state, incident_id=incident_id, agent_name="DATABASE_agent",
        )
        assert result["escalate_to"] == "SECURITY"


# ---------------------------------------------------------------------------
# Full orchestration tests (mock Ollama everywhere)
# ---------------------------------------------------------------------------

class TestOrchestrator:
    @patch("src.agent_loop.ollama")
    @patch("src.orchestrator.ollama")
    @patch("src.router.ollama")
    def test_1_postgres_full_pipeline(self, mock_router, mock_synth, mock_agent, state, tool_registry):
        """Test 1: PostgreSQL connection pool → DATABASE agent."""
        mock_router.chat.return_value = _ollama_response(
            '{"category": "DATABASE", "confidence": 0.92, "reasoning": "DB connection pool issue."}'
        )
        mock_synth.chat.return_value = _ollama_response(
            '{"summary": "Connection pool exhausted.", "root_cause": "Too many connections.", "causal_chain": null, "overall_severity": "HIGH", "remediation_steps": ["Increase pool"], "prevention": ["Add monitoring"]}'
        )
        mock_agent.chat.side_effect = [
            _ollama_response('{"action": "tool_call", "tool": "log_search", "args": {"query": "connection pool", "service": "postgres"}}'),
            _ollama_response('{"action": "tool_call", "tool": "runbook_lookup", "args": {"topic": "connection pool exhaustion"}}'),
            _ollama_response('{"action": "final_answer", "severity": "HIGH", "root_cause": "Connection pool exhausted", "evidence": ["Log shows 100/100 connections"], "remediation": ["Increase max_connections"], "escalate_to": null}'),
        ]
        report = handle_incident("PostgreSQL connection pool exhausted — all 100 connections in use", state, tool_registry)
        assert report["routing"]["category"] == "DATABASE"
        assert "DATABASE_agent" in report["agents_dispatched"]
        assert report["overall_severity"] == "HIGH"
        tool_registry["log_search"].assert_called()
        tool_registry["runbook_lookup"].assert_called()

    @patch("src.agent_loop.ollama")
    @patch("src.orchestrator.ollama")
    @patch("src.router.ollama")
    def test_2_ssl_cert(self, mock_router, mock_synth, mock_agent, state, tool_registry):
        """Test 2: SSL cert expiring → NETWORK agent, calls check_ssl."""
        mock_router.chat.return_value = _ollama_response(
            '{"category": "NETWORK", "confidence": 0.95, "reasoning": "SSL cert issue."}'
        )
        mock_synth.chat.return_value = _ollama_response(
            '{"summary": "SSL cert expiring.", "root_cause": "Cert not renewed.", "causal_chain": null, "overall_severity": "HIGH", "remediation_steps": ["Renew cert"], "prevention": ["Auto-renew"]}'
        )
        mock_agent.chat.side_effect = [
            _ollama_response('{"action": "tool_call", "tool": "check_ssl", "args": {"domain": "api.example.com"}}'),
            _ollama_response('{"action": "final_answer", "severity": "HIGH", "root_cause": "SSL cert expiring", "evidence": ["check_ssl shows expiry"], "remediation": ["Renew certificate"], "escalate_to": null}'),
        ]
        report = handle_incident("SSL certificate for api.example.com expires in 2 days", state, tool_registry)
        assert report["routing"]["category"] == "NETWORK"
        tool_registry["check_ssl"].assert_called()

    @patch("src.agent_loop.ollama")
    @patch("src.orchestrator.ollama")
    @patch("src.router.ollama")
    def test_3_ssh_brute_force(self, mock_router, mock_synth, mock_agent, state, tool_registry):
        """Test 3: SSH brute force → SECURITY agent, severity HIGH."""
        mock_router.chat.return_value = _ollama_response(
            '{"category": "SECURITY", "confidence": 0.97, "reasoning": "Brute force attack."}'
        )
        mock_synth.chat.return_value = _ollama_response(
            '{"summary": "SSH brute force detected.", "root_cause": "External attack.", "causal_chain": null, "overall_severity": "HIGH", "remediation_steps": ["Block IP"], "prevention": ["Fail2ban"]}'
        )
        mock_agent.chat.side_effect = [
            _ollama_response('{"action": "tool_call", "tool": "log_search", "args": {"query": "failed SSH login", "service": "sshd"}}'),
            _ollama_response('{"action": "final_answer", "severity": "HIGH", "root_cause": "SSH brute force from 203.0.113.42", "evidence": ["5000+ failed logins"], "remediation": ["Block IP", "Enable fail2ban"], "escalate_to": null}'),
        ]
        report = handle_incident("Detected 5000+ failed SSH login attempts from 203.0.113.42", state, tool_registry)
        assert report["routing"]["category"] == "SECURITY"
        assert report["overall_severity"] in ("HIGH", "CRITICAL")
        tool_registry["log_search"].assert_called()

    @patch("src.router.ollama")
    def test_4_ambiguous_login(self, mock_ollama):
        """Test 4: 'Users can't log in' → ambiguous flag or low confidence."""
        mock_ollama.chat.return_value = _ollama_response(
            '{"category": "APPLICATION", "confidence": 0.45, "reasoning": "Vague report."}'
        )
        result = route_incident("Users can't log in.")
        assert result["ambiguous"] is True or result["confidence"] < 0.6

    @patch("src.router.ollama")
    def test_5_out_of_scope_no_agent(self, mock_ollama, state, tool_registry):
        """Test 5: 'When is the all-hands?' → OUT_OF_SCOPE, no agent dispatched."""
        mock_ollama.chat.return_value = _ollama_response(
            '{"category": "OUT_OF_SCOPE", "confidence": 0.99, "reasoning": "Not an incident."}'
        )
        report = handle_incident("When is the company all-hands meeting?", state, tool_registry)
        assert report["routing"]["category"] == "OUT_OF_SCOPE"
        assert report["agents_dispatched"] == []
        assert report["incident_id"] is None

    @patch("src.agent_loop.ollama")
    @patch("src.orchestrator.ollama")
    @patch("src.router.ollama")
    def test_6_multi_domain(self, mock_router, mock_synth, mock_agent, state, tool_registry):
        """Test 6: API latency + DB CPU → multi-domain, APPLICATION + DATABASE dispatched."""
        mock_router.chat.return_value = _ollama_response(
            '{"category": "APPLICATION", "confidence": 0.72, "reasoning": "App latency with DB involvement."}'
        )
        mock_synth.chat.return_value = _ollama_response(
            '{"summary": "Cascading failure.", "root_cause": "DB CPU spike causing app latency.", "causal_chain": "DB CPU → slow queries → app timeout", "overall_severity": "HIGH", "remediation_steps": ["Scale DB"], "prevention": ["Query optimization"]}'
        )
        mock_agent.chat.side_effect = [
            _ollama_response('{"action": "tool_call", "tool": "metric_query", "args": {"metric": "latency_p99", "service": "api"}}'),
            _ollama_response('{"action": "final_answer", "severity": "HIGH", "root_cause": "App latency caused by slow DB queries", "evidence": ["p99 latency 12s"], "remediation": ["Investigate DB"], "escalate_to": "DATABASE"}'),
            _ollama_response('{"action": "tool_call", "tool": "metric_query", "args": {"metric": "cpu_usage", "service": "postgres"}}'),
            _ollama_response('{"action": "final_answer", "severity": "HIGH", "root_cause": "DB CPU at 98%", "evidence": ["CPU at 98%"], "remediation": ["Kill slow queries"], "escalate_to": null}'),
        ]
        report = handle_incident("API latency spiking to 12s p99 while database CPU is at 98%", state, tool_registry)
        assert len(report["agents_dispatched"]) >= 2
        assert any("APPLICATION" in n for n in report["agents_dispatched"])
        assert any("DATABASE" in n for n in report["agents_dispatched"])

    @patch("src.agent_loop.ollama")
    @patch("src.orchestrator.ollama")
    @patch("src.router.ollama")
    def test_7_memory_leak(self, mock_router, mock_synth, mock_agent, state, tool_registry):
        """Test 7: Memory leak in payment-service → APPLICATION, calls log_search + metric_query."""
        mock_router.chat.return_value = _ollama_response(
            '{"category": "APPLICATION", "confidence": 0.93, "reasoning": "Memory leak."}'
        )
        mock_synth.chat.return_value = _ollama_response(
            '{"summary": "Memory leak in payment-service.", "root_cause": "Unbounded cache growth.", "causal_chain": null, "overall_severity": "HIGH", "remediation_steps": ["Restart service"], "prevention": ["Add memory limits"]}'
        )
        mock_agent.chat.side_effect = [
            _ollama_response('{"action": "tool_call", "tool": "log_search", "args": {"query": "OOM memory", "service": "payment-service"}}'),
            _ollama_response('{"action": "tool_call", "tool": "metric_query", "args": {"metric": "memory_rss", "service": "payment-service"}}'),
            _ollama_response('{"action": "final_answer", "severity": "HIGH", "root_cause": "Memory leak — RSS growing 50MB/hour", "evidence": ["RSS growing linearly", "OOM warnings"], "remediation": ["Restart pod", "Profile heap"], "escalate_to": null}'),
        ]
        report = handle_incident("Memory leak in payment-service — RSS growing 50MB/hour", state, tool_registry)
        assert report["routing"]["category"] == "APPLICATION"
        tool_registry["log_search"].assert_called()
        tool_registry["metric_query"].assert_called()

    @patch("src.agent_loop.ollama")
    @patch("src.orchestrator.ollama")
    @patch("src.router.ollama")
    def test_8_surprise_cascading_failure(self, mock_router, mock_synth, mock_agent, state, tool_registry):
        """Test 8: Surprise Twist — DATABASE → escalate to SECURITY."""
        description = (
            "Database queries are returning stale data. Investigation shows the read replica "
            "is 47 minutes behind primary. Cause: the replication slot was dropped after an "
            "unauthorized ALTER TABLE command executed by user 'analytics_bot' — an account "
            "that should only have SELECT permissions."
        )
        mock_router.chat.return_value = _ollama_response(
            '{"category": "DATABASE", "confidence": 0.88, "reasoning": "Replication lag and stale data are database issues."}'
        )
        mock_synth.chat.return_value = _ollama_response(
            '{"summary": "Security breach caused database replication failure.", "root_cause": "Privilege escalation on analytics_bot account.", '
            '"causal_chain": "Unauthorized ALTER TABLE → replication slot dropped → replica 47min behind → stale reads", '
            '"overall_severity": "CRITICAL", "remediation_steps": ["Recreate replication slot", "Revoke privileges", "Rotate credentials"], '
            '"prevention": ["Enforce least-privilege", "Add DDL audit logging"]}'
        )
        mock_agent.chat.side_effect = [
            # DATABASE agent tool calls
            _ollama_response('{"action": "tool_call", "tool": "log_search", "args": {"query": "replication slot", "service": "postgres"}}'),
            _ollama_response('{"action": "tool_call", "tool": "metric_query", "args": {"metric": "replication_lag", "service": "postgres"}}'),
            # DATABASE agent final answer with escalation
            _ollama_response('{"action": "final_answer", "severity": "CRITICAL", "root_cause": "Replication slot dropped by unauthorized ALTER TABLE from analytics_bot", "evidence": ["Replica 47min behind", "ALTER TABLE in logs"], "remediation": ["Recreate replication slot"], "escalate_to": "SECURITY"}'),
            # SECURITY agent tool calls
            _ollama_response('{"action": "tool_call", "tool": "log_search", "args": {"query": "analytics_bot ALTER TABLE", "service": "postgres"}}'),
            _ollama_response('{"action": "tool_call", "tool": "runbook_lookup", "args": {"topic": "privilege escalation response"}}'),
            # SECURITY agent final answer
            _ollama_response('{"action": "final_answer", "severity": "CRITICAL", "root_cause": "analytics_bot had elevated privileges allowing ALTER TABLE — should only have SELECT", "evidence": ["ALTER TABLE executed by analytics_bot", "Account only authorized for SELECT"], "remediation": ["Revoke privileges", "Rotate credentials", "Audit account activity"], "escalate_to": null}'),
        ]
        report = handle_incident(description, state, tool_registry)

        # DATABASE dispatched first
        assert report["agents_dispatched"][0] == "DATABASE_agent"
        # SECURITY dispatched via escalation
        assert "SECURITY_agent" in report["agents_dispatched"]
        assert len(report["agents_dispatched"]) >= 2
        # Findings from BOTH agents
        assert len(report["findings"]) >= 2
        agents_in_findings = [f.get("agent") for f in report["findings"]]
        assert "DATABASE_agent" in agents_in_findings
        assert "SECURITY_agent" in agents_in_findings
        # Overall severity is CRITICAL
        assert report["overall_severity"] == "CRITICAL"
        # Timeline records escalation
        timeline_text = " ".join(report["timeline"])
        assert "escalat" in timeline_text.lower()


# ---------------------------------------------------------------------------
# Agent definitions tests
# ---------------------------------------------------------------------------

class TestAgentDefinitions:
    def test_all_categories_have_agents(self):
        for cat in AGENT_CATEGORIES:
            assert cat in AGENTS, f"Missing agent definition for {cat}"

    def test_agents_have_required_keys(self):
        for name, agent in AGENTS.items():
            assert "system_prompt" in agent, f"{name} missing system_prompt"
            assert "allowed_tools" in agent, f"{name} missing allowed_tools"
            assert len(agent["system_prompt"]) > 50, f"{name} system_prompt too short"
            assert len(agent["allowed_tools"]) > 0, f"{name} has no allowed tools"

    def test_system_prompts_include_tool_format(self):
        for name, agent in AGENTS.items():
            prompt = agent["system_prompt"]
            assert "tool_call" in prompt, f"{name} prompt missing tool_call format"
            assert "final_answer" in prompt, f"{name} prompt missing final_answer format"
