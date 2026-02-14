"""
Simulated monitored application with injectable faults.
This represents the production app that AgentOps monitors.
"""
import asyncio
import random
import time
from typing import Dict, Any
from dataclasses import dataclass, field

@dataclass
class ServiceState:
    healthy: bool = True
    fault_type: str | None = None
    fault_start: float | None = None
    response_time_ms: float = 50.0
    error_rate: float = 0.0
    memory_usage_mb: float = 256.0
    logs: list = field(default_factory=list)

class MonitoredApp:
    """Simulates a microservice application with multiple services."""

    def __init__(self):
        self.services: Dict[str, ServiceState] = {
            "api": ServiceState(),
            "database": ServiceState(),
            "auth": ServiceState(),
            "cache": ServiceState(),
            "worker": ServiceState(),
        }
        self._running = True

    def inject_fault(self, fault_type: str, service: str = "api") -> Dict[str, Any]:
        """Inject a fault into a service."""
        if service not in self.services:
            return {"error": f"Unknown service: {service}"}

        svc = self.services[service]
        svc.fault_type = fault_type
        svc.fault_start = time.time()

        if fault_type == "crash":
            svc.healthy = False
            svc.error_rate = 1.0
            svc.logs.append({
                "timestamp": time.time(),
                "level": "ERROR",
                "message": f"FATAL: {service} process crashed with exit code 137 (OOMKilled)",
                "stack_trace": (
                    "Traceback (most recent call last):\n"
                    f"  File \"/app/{service}/main.py\", line 42, in handle_request\n"
                    "    result = process_data(payload)\n"
                    f"  File \"/app/{service}/processor.py\", line 128, in process_data\n"
                    "    buffer = allocate_buffer(size=BUFFER_SIZE)\n"
                    "MemoryError: Unable to allocate 2.0 GiB for array\n"
                ),
            })
            svc.logs.append({
                "timestamp": time.time(),
                "level": "ERROR",
                "message": f"Health check failed for {service}: Connection refused on port {5000 + list(self.services.keys()).index(service)}",
            })

        elif fault_type == "slow":
            svc.response_time_ms = 5000.0
            svc.error_rate = 0.3
            svc.logs.append({
                "timestamp": time.time(),
                "level": "WARN",
                "message": f"Slow query detected in {service}: SELECT * FROM users JOIN orders took 4823ms",
            })
            svc.logs.append({
                "timestamp": time.time(),
                "level": "WARN",
                "message": f"Connection pool exhausted for {service}: 50/50 connections in use",
            })

        elif fault_type == "bad_config":
            svc.healthy = False
            svc.error_rate = 1.0
            svc.logs.append({
                "timestamp": time.time(),
                "level": "ERROR",
                "message": f"Configuration error in {service}: Invalid DATABASE_URL - password contains unescaped '@' character",
                "stack_trace": (
                    "sqlalchemy.exc.OperationalError: (psycopg2.OperationalError)\n"
                    "could not connect to server: Connection refused\n"
                    "Is the server running on host \"@production-db\" and accepting\n"
                    "TCP/IP connections on port 5432?\n"
                ),
            })

        elif fault_type == "memory_leak":
            svc.memory_usage_mb = 3800.0
            svc.error_rate = 0.1
            svc.logs.append({
                "timestamp": time.time(),
                "level": "WARN",
                "message": f"Memory usage critical for {service}: 3800MB / 4096MB (92.8%)",
            })
            svc.logs.append({
                "timestamp": time.time(),
                "level": "WARN",
                "message": f"GC overhead limit exceeded in {service}: 98% of time spent in garbage collection",
            })

        elif fault_type == "dependency_down":
            svc.healthy = False
            svc.error_rate = 0.8
            svc.logs.append({
                "timestamp": time.time(),
                "level": "ERROR",
                "message": f"Dependency failure in {service}: upstream service 'payment-gateway' returned 503",
                "stack_trace": (
                    "requests.exceptions.ConnectionError: HTTPSConnectionPool(\n"
                    "host='payment-gateway.internal', port=443):\n"
                    "Max retries exceeded with url: /v1/charge\n"
                    "Caused by: NewConnectionError: Failed to establish connection\n"
                ),
            })

        return {
            "injected": fault_type,
            "service": service,
            "timestamp": time.time(),
        }

    def clear_fault(self, service: str) -> Dict[str, Any]:
        """Clear faults from a service (simulate fix applied)."""
        if service not in self.services:
            return {"error": f"Unknown service: {service}"}

        svc = self.services[service]
        old_fault = svc.fault_type
        svc.healthy = True
        svc.fault_type = None
        svc.fault_start = None
        svc.response_time_ms = 50.0
        svc.error_rate = 0.0
        svc.memory_usage_mb = 256.0
        svc.logs.append({
            "timestamp": time.time(),
            "level": "INFO",
            "message": f"Service {service} recovered. Previous fault: {old_fault}",
        })
        return {"cleared": old_fault, "service": service}

    def get_health(self) -> Dict[str, Any]:
        """Get health status of all services."""
        result = {}
        for name, svc in self.services.items():
            result[name] = {
                "healthy": svc.healthy,
                "fault_type": svc.fault_type,
                "response_time_ms": svc.response_time_ms + random.uniform(-10, 10),
                "error_rate": svc.error_rate,
                "memory_usage_mb": svc.memory_usage_mb + random.uniform(-5, 5),
                "uptime_seconds": time.time() - (svc.fault_start or time.time()),
            }
        return result

    def get_logs(self, service: str | None = None, limit: int = 50) -> list:
        """Get logs, optionally filtered by service."""
        all_logs = []
        for name, svc in self.services.items():
            if service and name != service:
                continue
            for log in svc.logs:
                all_logs.append({**log, "service": name})

        all_logs.sort(key=lambda x: x["timestamp"], reverse=True)
        return all_logs[:limit]

    def get_metrics(self, service: str) -> Dict[str, Any]:
        """Get detailed metrics for a service."""
        if service not in self.services:
            return {"error": f"Unknown service: {service}"}
        svc = self.services[service]
        return {
            "service": service,
            "healthy": svc.healthy,
            "fault_type": svc.fault_type,
            "response_time_ms": svc.response_time_ms,
            "error_rate": svc.error_rate,
            "memory_usage_mb": svc.memory_usage_mb,
            "log_count": len(svc.logs),
        }


# Global instance
app_instance = MonitoredApp()
