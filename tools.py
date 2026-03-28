import json
from typing import List, Dict, Any
from mock_data import LOGS, RUNBOOKS, METRICS, SSL_INFO

def log_search(query: str) -> str:
    """Searches through mock logs for a specific query string."""
    matches = [log for log in LOGS if query.lower() in log["message"].lower() or query.lower() in log["service"].lower()]
    if not matches:
        return f"No logs found matching query: '{query}'"
    return json.dumps(matches, indent=2)

def runbook_lookup(incident_type: str) -> str:
    """Retrieves remediation steps from the runbook database."""
    # incident_type can be a partial match
    for key, steps in RUNBOOKS.items():
        if key in incident_type.upper() or incident_type.upper() in key:
            return f"Runbook for {key}: {steps}"
    return f"No runbook found for: {incident_type}. Available types: {', '.join(RUNBOOKS.keys())}"

def metric_query(metric_name: str, service: str) -> str:
    """Queries for a specific metric for a given service."""
    service_data = METRICS.get(service.lower())
    if not service_data:
        return f"No metrics found for service: {service}"
    
    values = service_data.get(metric_name.lower())
    if not values:
        return f"No metric '{metric_name}' found for service '{service}'"
    
    return f"Metric '{metric_name}' for '{service}': {values} (latest value: {values[-1]})"

def check_ssl(domain: str) -> str:
    """Checks the SSL status and expiry date of a domain."""
    info = SSL_INFO.get(domain.lower())
    if not info:
        return f"Domain '{domain}' not found in internal SSL database."
    return f"Domain '{domain}' SSL Status: {info['status']}, Expiry Date: {info['expiry_date']}"

# Example of how these functions would be invoked by an agent tool-calling loop:
# tools = {
#     "log_search": log_search,
#     "runbook_lookup": runbook_lookup,
#     "metric_query": metric_query,
#     "check_ssl": check_ssl
# }
