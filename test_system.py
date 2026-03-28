from state import IncidentState
from tools import log_search, runbook_lookup, metric_query, check_ssl
import json

def test_state_management():
    print("--- Testing state.py ---")
    state = IncidentState(incident_id="INC-TEST-001")
    
    # Test initial state
    assert state.incident_id == "INC-TEST-001"
    assert len(state.findings) == 0
    assert state.severity == "Low"
    
    # Test adding finding
    state.add_finding("AgentA", "Found a suspicious login")
    assert len(state.findings) == 1
    assert "Found a suspicious login" in state.findings
    
    # Test updating severity
    state.update_severity("AgentA", "High")
    assert state.severity == "High"
    
    # Test timeline
    assert len(state.timeline) == 2 # Finding + Severity update
    print("✓ State management passed.\n")

def test_tools_and_mock_data():
    print("--- Testing tools.py and mock_data.py ---")
    
    # Test log_search
    log_results = log_search("payment-service")
    assert "payment-service" in log_results
    assert "OutOfMemoryError" in log_results
    print("✓ log_search tool passed.")

    # Test runbook_lookup
    runbook = runbook_lookup("OOM_ERROR")
    assert "Restart pod" in runbook
    print("✓ runbook_lookup tool passed.")

    # Test metric_query
    metrics = metric_query("cpu_usage", "api-gateway")
    assert "95" in metrics
    print("✓ metric_query tool passed.")

    # Test check_ssl
    ssl = check_ssl("api.payments.internal")
    assert "Expired" in ssl
    print("✓ check_ssl tool passed.")
    print("\n✓ All tools and mock data tests passed.\n")

if __name__ == "__main__":
    try:
        test_state_management()
        test_tools_and_mock_data()
        print("Final Result: Logic and data components are working correctly.")
    except AssertionError as e:
        print(f"Test Failed: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")
