import unittest
import json
import sys
import os

# Ensure the parent directory is in the path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from state import IncidentState
import tools

class TestIncidentOrchestration(unittest.TestCase):

    def setUp(self):
        self.state = IncidentState(incident_id="INC-UNIT-TEST")

    def test_1_state_initialization(self):
        """Test if the state initializes with correct defaults."""
        self.assertEqual(self.state.incident_id, "INC-UNIT-TEST")
        self.assertEqual(len(self.state.findings), 0)
        self.assertEqual(self.state.severity, "Low")
        self.assertEqual(len(self.state.timeline), 0)

    def test_2_timeline_tracking(self):
        """Test if timeline correctly tracks agent actions and tools."""
        self.state.add_timeline_event("TestAgent", "Checking logs", tool_used="log_search")
        self.assertEqual(len(self.state.timeline), 1)
        self.assertEqual(self.state.timeline[0]["agent"], "TestAgent")
        self.assertEqual(self.state.timeline[0]["tool"], "log_search")

    def test_3_tool_error_handling(self):
        """Test how tools handle non-existent services/metrics."""
        # Querying a non-existent service
        res = tools.metric_query("cpu", "ghost-service")
        self.assertIn("No metrics found for service", res)
        
        # Querying a non-existent metric on a real service
        res = tools.metric_query("non_existent_metric", "db-service")
        self.assertIn("No metric 'non_existent_metric' found", res)

    def test_4_log_search_output_format(self):
        """Verify log_search returns valid JSON when results are found."""
        res = tools.log_search("payment-service")
        # Should be a valid JSON list
        data = json.loads(res)
        self.assertIsInstance(data, list)
        self.assertTrue(len(data) > 0)
        self.assertEqual(data[0]["service"], "payment-service")

    def test_5_severity_persistence(self):
        """Ensure severity updates are correctly stored and reflected in summary."""
        self.state.update_severity("SecurityAgent", "Critical")
        self.assertEqual(self.state.severity, "Critical")
        summary = self.state.get_context_summary()
        self.assertIn("Severity: Critical", summary)

if __name__ == "__main__":
    unittest.main()
