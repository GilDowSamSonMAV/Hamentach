# Static Mock Data for Incident Response Orchestration System

# 1. Fake Log Entries
LOGS = [
    {"timestamp": "2024-03-28 10:05:01", "service": "payment-service", "level": "ERROR", "message": "java.lang.OutOfMemoryError: Java heap space"},
    {"timestamp": "2024-03-28 10:05:45", "service": "auth-service", "level": "WARN", "message": "Failed SSH login attempt for user 'admin' from IP 192.168.1.10"},
    {"timestamp": "2024-03-28 10:06:12", "service": "db-service", "level": "ERROR", "message": "PostgreSQL connection pool exhausted. active_conns=500, max_conns=500"},
    {"timestamp": "2024-03-28 10:07:30", "service": "api-gateway", "level": "INFO", "message": "Route /v1/checkout returning 504 Gateway Timeout"},
    {"timestamp": "2024-03-28 10:08:15", "service": "auth-service", "level": "WARN", "message": "Repeated failed SSH login attempts for 'root' from 10.0.0.5"},
]

# 2. Runbook Database (Remediation steps)
RUNBOOKS = {
    "OOM_ERROR": "1. Identify leaking service. 2. Restart pod. 3. Check memory limits and increase if necessary.",
    "DB_CONN_EXHAUSTED": "1. Check for long-running queries. 2. Increase max_connections in postgresql.conf. 3. Scale up DB instance.",
    "SSH_BRUTE_FORCE": "1. Identify source IP. 2. Add IP to firewall blocklist. 3. Force password reset for target user.",
    "SSL_EXPIRY": "1. Generate new CSR. 2. Request certificate from CA. 3. Update secret in Kubernetes or Load Balancer."
}

# 3. Time Series Metric Data (service: {metric_name: [values]})
METRICS = {
    "api-gateway": {
        "latency": [120, 145, 180, 450, 900, 1200],  # ms
        "cpu_usage": [15, 20, 25, 60, 85, 95]       # percentage
    },
    "db-service": {
        "connections": [450, 480, 500, 500, 500],
        "cpu_usage": [40, 45, 80, 90, 95]
    },
    "payment-service": {
        "memory_mb": [1024, 2048, 4096, 4096, 4096],
        "errors_per_min": [0, 0, 5, 25, 150]
    }
}

# 4. Domain / SSL Info
SSL_INFO = {
    "api.payments.internal": {"status": "Expired", "expiry_date": "2024-03-20"},
    "auth.internal": {"status": "Valid", "expiry_date": "2024-12-31"},
    "db.internal": {"status": "Valid", "expiry_date": "2024-09-15"}
}
