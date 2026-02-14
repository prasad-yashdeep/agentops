"""
Real monitored application manager.
Runs target_app/server.py as a subprocess and provides real fault injection
by modifying actual source files and config.
"""
import asyncio
import json
import os
import shutil
import signal
import time
from typing import Dict, Any

import httpx

BASE_DIR = os.path.join(os.path.dirname(__file__), "target_app")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
CONFIG_BACKUP = os.path.join(BASE_DIR, "config.json.bak")
HANDLER_PATH = os.path.join(BASE_DIR, "handler.py")
HANDLER_BACKUP = os.path.join(BASE_DIR, "handler.py.bak")
LOG_PATH = os.path.join(BASE_DIR, "app.log")
SERVER_PATH = os.path.join(BASE_DIR, "server.py")

TARGET_PORT = 8001
HEALTH_URL = f"http://127.0.0.1:{TARGET_PORT}/health"


class MonitoredApp:
    """Manages the real target application process."""

    def __init__(self):
        self.process = None
        self.active_fault = None
        self.fault_start = None
        self._starting = False

    async def start(self):
        """Start the target app as a subprocess."""
        if self.process and self.process.returncode is None:
            return  # Already running
        self._starting = True
        # Clear old log
        if os.path.exists(LOG_PATH):
            open(LOG_PATH, "w").close()

        self.process = await asyncio.create_subprocess_exec(
            "python3", SERVER_PATH, str(TARGET_PORT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=BASE_DIR,
        )
        # Wait for it to be ready
        for _ in range(20):
            await asyncio.sleep(0.3)
            try:
                async with httpx.AsyncClient(timeout=2) as c:
                    r = await c.get(HEALTH_URL)
                    if r.status_code == 200:
                        self._starting = False
                        return
            except Exception:
                pass
        self._starting = False

    async def stop(self):
        """Stop the target app."""
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
        self.process = None

    async def restart(self):
        """Restart the target app."""
        await self.stop()
        await asyncio.sleep(0.5)
        await self.start()

    def is_running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def health_check(self) -> Dict[str, Any]:
        """Do a real HTTP health check against the target app."""
        if self._starting:
            return {"healthy": True, "status": "starting"}

        if not self.is_running():
            return {
                "healthy": False,
                "error": "Process not running (crashed or killed)",
                "error_type": "ProcessDown",
                "status_code": None,
            }

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                start = time.time()
                resp = await client.get(HEALTH_URL)
                elapsed_ms = (time.time() - start) * 1000

                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "healthy": True,
                        "response_time_ms": elapsed_ms,
                        "data": data,
                    }
                else:
                    error_data = resp.json()
                    return {
                        "healthy": False,
                        "status_code": resp.status_code,
                        "error": error_data.get("error", "Unknown error"),
                        "error_type": error_data.get("type", "HTTPError"),
                        "traceback": error_data.get("traceback", ""),
                        "detail": error_data.get("detail", ""),
                        "response_time_ms": elapsed_ms,
                    }

        except httpx.ConnectError:
            return {
                "healthy": False,
                "error": f"Connection refused on port {TARGET_PORT}",
                "error_type": "ConnectionRefused",
            }
        except httpx.ReadTimeout:
            return {
                "healthy": False,
                "error": f"Health check timed out (>5s)",
                "error_type": "Timeout",
                "response_time_ms": 5000,
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
                "error_type": type(e).__name__,
            }

    def get_logs(self, limit: int = 30) -> str:
        """Read real logs from the target app."""
        if not os.path.exists(LOG_PATH):
            return ""
        with open(LOG_PATH) as f:
            lines = f.readlines()
        return "".join(lines[-limit:])

    def get_file(self, filename: str) -> str:
        """Read a source file from the target app."""
        path = os.path.join(BASE_DIR, filename)
        if os.path.exists(path):
            with open(path) as f:
                return f.read()
        return ""

    def write_file(self, filename: str, content: str):
        """Write a source file in the target app."""
        path = os.path.join(BASE_DIR, filename)
        with open(path, "w") as f:
            f.write(content)

    # ─── Fault Injection ─────────────────────────────────────────

    async def inject_fault(self, fault_type: str) -> Dict[str, Any]:
        """Inject a real fault into the running app."""
        self.active_fault = fault_type
        self.fault_start = time.time()

        if fault_type == "crash":
            # Kill the process
            if self.process and self.process.returncode is None:
                self.process.kill()
            return {
                "fault": "crash",
                "detail": "Process killed (simulating OOM kill)",
                "file_modified": None,
            }

        elif fault_type == "bad_config":
            # Corrupt config.json with invalid JSON
            self.write_file("config.json", '{"version": "1.0.0", "database_url": INVALID_NOT_QUOTED, "cache_ttl": 300}')
            return {
                "fault": "bad_config",
                "detail": "config.json corrupted with invalid JSON",
                "file_modified": "config.json",
            }

        elif fault_type == "bug":
            # Inject a real Python bug into handler.py
            buggy_handler = '''"""
Business logic handler — BUGGY VERSION (injected fault)
"""

USERS_DB = [
    {"id": 1, "name": "Alice Chen", "role": "engineer", "active": True},
    {"id": 2, "name": "Bob Smith", "role": "designer", "active": True},
    {"id": 3, "name": "Carol Williams", "role": "manager", "active": True},
    {"id": 4, "name": "Dave Johnson", "role": "engineer", "active": False},
]


def validate():
    """Health check — this will crash due to undefined variable."""
    return check_database_connection  # NameError: undefined variable


def get_users():
    return [u for u in USERS_DB if u["active"]]


def compute_stats():
    total = len(USERS_DB)
    active = len([u for u in USERS_DB if u["active"]])
    # Bug: division by zero when no inactive users
    inactive_ratio = total / (total - active)
    return {"total": total, "active": active, "ratio": inactive_ratio}


def process_data(data):
    value = data.get("value", 0)
    return value * 2
'''
            self.write_file("handler.py", buggy_handler)
            return {
                "fault": "bug",
                "detail": "handler.py replaced with buggy version (NameError in validate())",
                "file_modified": "handler.py",
            }

        elif fault_type == "slow":
            # Inject time.sleep into handler
            slow_handler = '''"""
Business logic handler — SLOW VERSION (injected fault)
"""
import time

USERS_DB = [
    {"id": 1, "name": "Alice Chen", "role": "engineer", "active": True},
    {"id": 2, "name": "Bob Smith", "role": "designer", "active": True},
    {"id": 3, "name": "Carol Williams", "role": "manager", "active": True},
    {"id": 4, "name": "Dave Johnson", "role": "engineer", "active": False},
]


def validate():
    """Simulating slow database connection check."""
    time.sleep(8)  # Blocking call — should be async or cached
    return True


def get_users():
    time.sleep(8)
    return [u for u in USERS_DB if u["active"]]


def compute_stats():
    time.sleep(8)
    return {"total": len(USERS_DB), "active": 3}


def process_data(data):
    time.sleep(8)
    return data.get("value", 0) * 2
'''
            self.write_file("handler.py", slow_handler)
            return {
                "fault": "slow",
                "detail": "handler.py injected with time.sleep(8) in all functions",
                "file_modified": "handler.py",
            }

        return {"error": f"Unknown fault type: {fault_type}"}

    async def apply_fix(self, fault_type: str) -> Dict[str, Any]:
        """Apply the real fix — restore files and restart."""
        if fault_type in ("crash",):
            # Just restart the process
            await self.restart()
            self.active_fault = None
            return {"fixed": True, "action": "process_restarted"}

        elif fault_type in ("bad_config",):
            # Restore config from backup
            if os.path.exists(CONFIG_BACKUP):
                shutil.copy2(CONFIG_BACKUP, CONFIG_PATH)
            else:
                # Write a valid config
                self.write_file("config.json", json.dumps({
                    "version": "1.0.0",
                    "database_url": "postgresql://admin:secret@db.internal:5432/production",
                    "cache_ttl": 300,
                    "max_connections": 50,
                    "debug": False,
                    "feature_flags": {"new_dashboard": True, "beta_api": False}
                }, indent=4))
            self.active_fault = None
            return {"fixed": True, "action": "config_restored", "file": "config.json"}

        elif fault_type in ("bug", "slow"):
            # Restore handler from backup
            if os.path.exists(HANDLER_BACKUP):
                shutil.copy2(HANDLER_BACKUP, HANDLER_PATH)
            self.active_fault = None
            return {"fixed": True, "action": "handler_restored", "file": "handler.py"}

        return {"fixed": False, "error": "Unknown fault type"}


# Global instance
app_instance = MonitoredApp()
