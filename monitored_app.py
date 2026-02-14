"""
Monitored application running inside a Blaxel sandbox.
All operations (health check, file read/write, process control) go through Blaxel SDK.
Falls back to local subprocess if Blaxel is unavailable.
"""
import asyncio
import json
import os
import shutil
import time
from typing import Dict, Any

import httpx

from config import BLAXEL_API_KEY, BLAXEL_WORKSPACE, USE_LOCAL_SANDBOX

# Local paths (fallback mode)
LOCAL_BASE = os.path.join(os.path.dirname(__file__), "target_app")
LOCAL_CONFIG = os.path.join(LOCAL_BASE, "config.json")
LOCAL_CONFIG_BAK = os.path.join(LOCAL_BASE, "config.json.bak")
LOCAL_HANDLER = os.path.join(LOCAL_BASE, "handler.py")
LOCAL_HANDLER_BAK = os.path.join(LOCAL_BASE, "handler.py.bak")
LOCAL_LOG = os.path.join(LOCAL_BASE, "app.log")
LOCAL_SERVER = os.path.join(LOCAL_BASE, "server.py")

# Blaxel paths
BL_APP_DIR = "/app"
BL_SANDBOX_NAME = "agentops-ecom"
BL_APP_PORT = 3000
LOCAL_APP_PORT = 8001

HEALTH_URL_LOCAL = f"http://127.0.0.1:{LOCAL_APP_PORT}/health"


class MonitoredApp:
    """Manages the target app — either in Blaxel sandbox or locally."""

    def __init__(self):
        self.sandbox = None  # Blaxel SandboxInstance
        self.local_process = None
        self.active_fault = None
        self.fault_start = None
        self._starting = False
        self.mode = "local"  # "blaxel" or "local"

    @property
    def app_port(self):
        return BL_APP_PORT if self.mode == "blaxel" else LOCAL_APP_PORT

    async def start(self):
        """Start the target app."""
        if not USE_LOCAL_SANDBOX and BLAXEL_API_KEY and BLAXEL_WORKSPACE:
            try:
                await self._start_blaxel()
                return
            except Exception as e:
                print(f"[AgentOps] Blaxel start failed ({e}), falling back to local")

        await self._start_local()

    async def _start_blaxel(self):
        """Connect to the Blaxel sandbox and ensure the app is running."""
        os.environ["BL_API_KEY"] = BLAXEL_API_KEY
        os.environ["BL_WORKSPACE"] = BLAXEL_WORKSPACE

        from blaxel.core.sandbox import SandboxInstance

        self.sandbox = await SandboxInstance.get(BL_SANDBOX_NAME)
        self.mode = "blaxel"

        # Check if app is already running
        r = await self.sandbox.process.exec({
            "command": f"curl -s http://127.0.0.1:{BL_APP_PORT}/health 2>/dev/null || echo NOTRUNNING",
            "wait_for_completion": True, "timeout": 5,
        })
        if "healthy" in (r.logs or ""):
            print(f"[AgentOps] Blaxel sandbox '{BL_SANDBOX_NAME}' — app already running")
            return

        # Start the app
        try:
            await self.sandbox.process.kill("ecommerce-api")
        except:
            pass
        await asyncio.sleep(0.5)

        await self.sandbox.process.exec({
            "name": "ecommerce-api",
            "command": f"cd {BL_APP_DIR} && python3 server.py {BL_APP_PORT}",
            "wait_for_completion": False,
        })
        await asyncio.sleep(2)
        print(f"[AgentOps] Blaxel mode — app running in sandbox '{BL_SANDBOX_NAME}' on port {BL_APP_PORT}")

    async def _start_local(self):
        """Start as local subprocess."""
        self.mode = "local"
        if self.local_process and self.local_process.returncode is None:
            return
        self._starting = True
        if os.path.exists(LOCAL_LOG):
            open(LOCAL_LOG, "w").close()

        self.local_process = await asyncio.create_subprocess_exec(
            "python3", LOCAL_SERVER, str(LOCAL_APP_PORT),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=LOCAL_BASE,
        )
        for _ in range(20):
            await asyncio.sleep(0.3)
            try:
                async with httpx.AsyncClient(timeout=2) as c:
                    r = await c.get(HEALTH_URL_LOCAL)
                    if r.status_code == 200:
                        self._starting = False
                        print(f"[AgentOps] Local mode — app running on port {LOCAL_APP_PORT}")
                        return
            except:
                pass
        self._starting = False

    async def stop(self):
        if self.mode == "blaxel" and self.sandbox:
            try:
                await self.sandbox.process.kill("ecommerce-api")
            except:
                pass
        elif self.local_process and self.local_process.returncode is None:
            self.local_process.terminate()
            try:
                await asyncio.wait_for(self.local_process.wait(), timeout=5)
            except:
                self.local_process.kill()
        self.local_process = None

    async def restart(self):
        """Kill and restart the app process (clears Python module cache)."""
        if self.mode == "blaxel" and self.sandbox:
            try:
                await self.sandbox.process.kill("ecommerce-api")
            except:
                pass
            await asyncio.sleep(1)
            await self.sandbox.process.exec({
                "name": "ecommerce-api",
                "command": f"cd {BL_APP_DIR} && python3 server.py {BL_APP_PORT}",
                "wait_for_completion": False,
            })
            await asyncio.sleep(2)
            print("[AgentOps] Blaxel app restarted")
        else:
            await self.stop()
            await asyncio.sleep(0.5)
            await self._start_local()

    def is_running(self) -> bool:
        if self.mode == "blaxel":
            return self.sandbox is not None
        return self.local_process is not None and self.local_process.returncode is None

    # ─── Health Check ─────────────────────────────────────────────

    async def health_check(self) -> Dict[str, Any]:
        """Real health check — runs inside Blaxel sandbox or locally."""
        if self._starting:
            return {"healthy": True, "status": "starting"}

        if self.mode == "blaxel":
            return await self._blaxel_health()
        return await self._local_health()

    async def _blaxel_health(self) -> Dict[str, Any]:
        try:
            r = await self.sandbox.process.exec({
                "command": f"curl -s -m 5 http://127.0.0.1:{BL_APP_PORT}/health",
                "wait_for_completion": True, "timeout": 8,
            })
            logs = r.logs or ""
            if not logs or "NOTRUNNING" in logs:
                return {"healthy": False, "error": "Process not running in sandbox", "error_type": "ProcessDown"}
            try:
                data = json.loads(logs)
                if data.get("status") == "healthy":
                    return {"healthy": True, "response_time_ms": 0, "data": data, "sandbox": BL_SANDBOX_NAME}
                else:
                    return {
                        "healthy": False,
                        "status_code": 500,
                        "error": data.get("error", "Unknown"),
                        "error_type": data.get("type", "HTTPError"),
                        "traceback": data.get("traceback", ""),
                        "detail": data.get("detail", ""),
                    }
            except json.JSONDecodeError:
                return {"healthy": False, "error": logs[:200], "error_type": "UnexpectedResponse"}
        except Exception as e:
            return {"healthy": False, "error": str(e), "error_type": type(e).__name__}

    async def _local_health(self) -> Dict[str, Any]:
        if not self.is_running():
            return {"healthy": False, "error": "Process not running (crashed or killed)", "error_type": "ProcessDown"}
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                start = time.time()
                resp = await client.get(HEALTH_URL_LOCAL)
                elapsed = (time.time() - start) * 1000
                if resp.status_code == 200:
                    return {"healthy": True, "response_time_ms": elapsed, "data": resp.json()}
                else:
                    d = resp.json()
                    return {"healthy": False, "status_code": resp.status_code, "error": d.get("error", ""), "error_type": d.get("type", ""), "traceback": d.get("traceback", ""), "detail": d.get("detail", "")}
        except httpx.ConnectError:
            return {"healthy": False, "error": f"Connection refused on port {LOCAL_APP_PORT}", "error_type": "ConnectionRefused"}
        except httpx.ReadTimeout:
            return {"healthy": False, "error": "Health check timed out (>5s)", "error_type": "Timeout", "response_time_ms": 5000}
        except Exception as e:
            return {"healthy": False, "error": str(e), "error_type": type(e).__name__}

    # ─── File Operations ──────────────────────────────────────────

    async def get_file(self, filename: str) -> str:
        if self.mode == "blaxel":
            return await self.sandbox.fs.read(f"{BL_APP_DIR}/{filename}")
        path = os.path.join(LOCAL_BASE, filename)
        return open(path).read() if os.path.exists(path) else ""

    async def write_file(self, filename: str, content: str):
        if self.mode == "blaxel":
            await self.sandbox.fs.write(f"{BL_APP_DIR}/{filename}", content)
        else:
            with open(os.path.join(LOCAL_BASE, filename), "w") as f:
                f.write(content)

    def get_logs(self, limit: int = 30) -> str:
        if self.mode == "blaxel":
            return "(logs from Blaxel sandbox)"
        if not os.path.exists(LOCAL_LOG):
            return ""
        with open(LOCAL_LOG) as f:
            return "".join(f.readlines()[-limit:])

    # ─── Fault Injection ──────────────────────────────────────────

    async def inject_fault(self, fault_type: str) -> Dict[str, Any]:
        self.active_fault = fault_type
        self.fault_start = time.time()

        if fault_type == "crash":
            if self.mode == "blaxel":
                try:
                    await self.sandbox.process.kill("ecommerce-api")
                except:
                    pass
            elif self.local_process and self.local_process.returncode is None:
                self.local_process.kill()
            return {"fault": "crash", "detail": "Process killed (simulating OOM kill)", "file_modified": None}

        elif fault_type == "bad_config":
            await self.write_file("config.json", '{"version": "2.3.1", "database_url": INVALID_NOT_QUOTED, "cache_ttl": 300}')
            return {"fault": "bad_config", "detail": "config.json corrupted with invalid JSON", "file_modified": "config.json"}

        elif fault_type == "bug":
            handler = await self.get_file("handler.py")
            buggy = handler.replace(
                '    assert config.get("database_url"), "Database URL not configured"',
                '    status = verify_database_connection(config["database_url"])\n    assert status.is_connected, "Database health check failed"'
            ).replace(
                '    avg_order_value = total_revenue / len(ORDERS) if ORDERS else 0',
                '    avg_order_value = total_revenue / (len(ORDERS) - len(ORDERS))  # BUG: always zero'
            )
            await self.write_file("handler.py", buggy)
            return {"fault": "bug", "detail": "handler.py corrupted — NameError in validate() + ZeroDivisionError in analytics", "file_modified": "handler.py"}

        elif fault_type == "slow":
            handler = await self.get_file("handler.py")
            slow = handler.replace(
                'def validate():\n    """Health check — verifies all subsystems are operational."""\n    config = _load_config()',
                'def validate():\n    """Health check — verifies all subsystems are operational."""\n    import time\n    time.sleep(10)  # BUG: debug sleep left in production\n    config = _load_config()'
            )
            await self.write_file("handler.py", slow)
            return {"fault": "slow", "detail": "handler.py injected with time.sleep(10) — debug code in production", "file_modified": "handler.py"}

        return {"error": f"Unknown fault: {fault_type}"}

    # ─── Apply Fix ────────────────────────────────────────────────

    async def apply_fix(self, fault_type: str) -> Dict[str, Any]:
        if fault_type == "crash":
            if self.mode == "blaxel":
                await self.sandbox.process.exec({
                    "name": "ecommerce-api",
                    "command": f"cd {BL_APP_DIR} && python3 server.py {BL_APP_PORT}",
                    "wait_for_completion": False,
                })
                await asyncio.sleep(2)
            else:
                await self.restart()
            self.active_fault = None
            return {"fixed": True, "action": "process_restarted"}

        elif fault_type == "bad_config":
            backup = await self.get_file("config.json.bak")
            if backup:
                await self.write_file("config.json", backup)
            self.active_fault = None
            return {"fixed": True, "action": "config_restored", "file": "config.json"}

        elif fault_type in ("bug", "slow"):
            backup = await self.get_file("handler.py.bak")
            if backup:
                await self.write_file("handler.py", backup)
            self.active_fault = None
            return {"fixed": True, "action": "handler_restored", "file": "handler.py"}

        return {"fixed": False, "error": f"Unknown fault: {fault_type}"}


app_instance = MonitoredApp()
TARGET_PORT = LOCAL_APP_PORT  # for main.py imports
