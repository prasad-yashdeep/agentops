"""
Sandbox interface for testing fixes.
Uses Blaxel SDK for persistent cloud sandboxes, with local subprocess fallback.
"""
import asyncio
import os
from typing import Dict, Any
from config import BLAXEL_API_KEY, BLAXEL_WORKSPACE, USE_LOCAL_SANDBOX


class SandboxResult:
    def __init__(self, success: bool, output: str, error: str = "", exit_code: int = 0):
        self.success = success
        self.output = output
        self.error = error
        self.exit_code = exit_code

    def to_dict(self):
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "exit_code": self.exit_code,
        }


class BlaxelSandbox:
    """Blaxel persistent sandbox for running and testing code."""

    def __init__(self):
        self.sandbox_instance = None
        self.sandbox_name = "agentops-sandbox"

    async def create(self) -> str:
        """Create or connect to a Blaxel persistent sandbox."""
        if USE_LOCAL_SANDBOX or not BLAXEL_API_KEY:
            return "local-sandbox"

        try:
            # Set auth env vars for Blaxel SDK
            os.environ["BL_API_KEY"] = BLAXEL_API_KEY
            if BLAXEL_WORKSPACE:
                os.environ["BL_WORKSPACE"] = BLAXEL_WORKSPACE

            from blaxel.core.sandbox import SandboxInstance

            self.sandbox_instance = await SandboxInstance.create_if_not_exists({
                "name": self.sandbox_name,
            })
            print(f"[AgentOps] Blaxel sandbox ready: {self.sandbox_name}")
            return self.sandbox_name
        except Exception as e:
            print(f"[AgentOps] Blaxel sandbox creation failed ({e}), falling back to local")
            self.sandbox_instance = None
            return "local-sandbox"

    async def execute(self, code: str, language: str = "python") -> SandboxResult:
        """Execute code in the sandbox."""
        if self.sandbox_instance and not USE_LOCAL_SANDBOX:
            return await self._blaxel_execute(code, language)
        return await self._local_execute(code, language)

    async def _blaxel_execute(self, code: str, language: str) -> SandboxResult:
        """Execute in Blaxel cloud sandbox using SDK."""
        try:
            if language == "python":
                command = f"python3 -c {_shell_quote(code)}"
            elif language == "bash":
                command = code
            else:
                return SandboxResult(success=False, output="", error=f"Unsupported language: {language}")

            result = await self.sandbox_instance.process.exec({
                "name": f"agentops-fix-{id(code) % 10000}",
                "command": command,
                "wait_for_completion": True,
                "timeout": 15,
            })

            exit_code = getattr(result, 'exit_code', None) or 0
            stdout = ""
            stderr = ""

            # Extract logs if available
            logs = getattr(result, 'logs', None)
            if logs:
                stdout = getattr(logs, 'stdout', '') or ''
                stderr = getattr(logs, 'stderr', '') or ''

            return SandboxResult(
                success=exit_code == 0,
                output=stdout[:5000],
                error=stderr[:5000],
                exit_code=exit_code,
            )
        except Exception as e:
            # Fallback to local on any Blaxel error
            print(f"[AgentOps] Blaxel exec failed ({e}), falling back to local")
            return await self._local_execute(code, language)

    async def _local_execute(self, code: str, language: str) -> SandboxResult:
        """Execute locally as fallback."""
        try:
            if language == "python":
                proc = await asyncio.create_subprocess_exec(
                    "python3", "-c", code,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            elif language == "bash":
                proc = await asyncio.create_subprocess_shell(
                    code,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            else:
                return SandboxResult(success=False, output="", error=f"Unsupported language: {language}")

            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            return SandboxResult(
                success=proc.returncode == 0,
                output=stdout.decode()[:5000],
                error=stderr.decode()[:5000],
                exit_code=proc.returncode or 0,
            )
        except asyncio.TimeoutError:
            return SandboxResult(success=False, output="", error="Execution timed out (15s)")
        except Exception as e:
            return SandboxResult(success=False, output="", error=str(e))

    async def test_fix(self, fix_code: str, test_code: str) -> Dict[str, Any]:
        """Apply a fix and run tests in the sandbox."""
        # First apply the fix
        fix_result = await self.execute(fix_code)
        if not fix_result.success:
            return {
                "fix_applied": False,
                "test_passed": False,
                "fix_output": fix_result.to_dict(),
                "test_output": None,
            }

        # Then run tests
        test_result = await self.execute(test_code)
        return {
            "fix_applied": True,
            "test_passed": test_result.success,
            "fix_output": fix_result.to_dict(),
            "test_output": test_result.to_dict(),
        }


def _shell_quote(s: str) -> str:
    """Simple shell quoting."""
    return "'" + s.replace("'", "'\\''") + "'"


sandbox = BlaxelSandbox()
