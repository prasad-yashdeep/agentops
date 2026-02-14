"""
White Circle AI integration for safety checking agent outputs.
Validates proposed fixes before they're applied to production.
"""
import json
import httpx
from typing import Dict, Any
from config import WHITECIRCLE_API_KEY, WHITECIRCLE_API_URL


class SafetyChecker:
    """
    White Circle AI safety layer.
    Tests, protects, observes, and optimizes AI outputs.
    """

    def __init__(self):
        self.api_key = WHITECIRCLE_API_KEY
        self.api_url = WHITECIRCLE_API_URL
        self.checks_run = 0
        self.checks_passed = 0
        self.checks_failed = 0

    async def check_fix(self, incident_context: Dict[str, Any], proposed_fix: str) -> Dict[str, Any]:
        """
        Run safety checks on a proposed fix before deployment.
        Returns safety assessment with pass/fail and reasoning.
        """
        if self.api_key:
            return await self._whitecircle_check(incident_context, proposed_fix)
        return await self._builtin_check(incident_context, proposed_fix)

    async def _whitecircle_check(self, context: Dict, fix: str) -> Dict[str, Any]:
        """Use White Circle AI API for safety validation."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.api_url}/evaluate",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "input": json.dumps(context),
                        "output": fix,
                        "checks": [
                            "no_data_loss",
                            "no_security_regression",
                            "no_destructive_commands",
                            "idempotent_safe",
                            "rollback_possible",
                        ],
                    },
                )
                data = resp.json()
                self.checks_run += 1
                passed = data.get("passed", False)
                if passed:
                    self.checks_passed += 1
                else:
                    self.checks_failed += 1

                return {
                    "passed": passed,
                    "score": data.get("score", 0.0),
                    "checks": data.get("checks", {}),
                    "reasoning": data.get("reasoning", ""),
                    "warnings": data.get("warnings", []),
                    "provider": "whitecircle",
                }
        except Exception as e:
            # Fallback to builtin if API fails
            result = await self._builtin_check(context, fix)
            result["provider_error"] = str(e)
            return result

    async def _builtin_check(self, context: Dict, fix: str) -> Dict[str, Any]:
        """Built-in safety checks when White Circle AI is unavailable."""
        self.checks_run += 1
        warnings = []
        checks = {}
        fix_lower = fix.lower()

        # Check for destructive commands
        destructive_patterns = [
            "rm -rf", "drop table", "drop database", "truncate",
            "format", "fdisk", "mkfs", "dd if=", ":(){ :|:& };:",
        ]
        checks["no_destructive_commands"] = True
        for pattern in destructive_patterns:
            if pattern in fix_lower:
                checks["no_destructive_commands"] = False
                warnings.append(f"Destructive command detected: '{pattern}'")

        # Check for data loss potential
        data_loss_patterns = ["delete from", "drop", "truncate", "remove all", "purge"]
        checks["no_data_loss"] = True
        for pattern in data_loss_patterns:
            if pattern in fix_lower:
                checks["no_data_loss"] = False
                warnings.append(f"Potential data loss: '{pattern}'")

        # Check for security issues
        security_patterns = [
            "chmod 777", "password=", "secret=", "disable_auth",
            "allow_all", "0.0.0.0", "skip-grant-tables",
        ]
        checks["no_security_regression"] = True
        for pattern in security_patterns:
            if pattern in fix_lower:
                checks["no_security_regression"] = False
                warnings.append(f"Security concern: '{pattern}'")

        # Check for credential exposure
        cred_patterns = ["api_key", "aws_secret", "private_key", "BEGIN RSA"]
        checks["no_credential_exposure"] = True
        for pattern in cred_patterns:
            if pattern in fix_lower:
                checks["no_credential_exposure"] = False
                warnings.append(f"Credential exposure risk: '{pattern}'")

        # Rollback assessment
        checks["rollback_possible"] = "restart" in fix_lower or "config" in fix_lower or "revert" in fix_lower

        passed = all(v for k, v in checks.items() if k != "rollback_possible")
        score = sum(1 for v in checks.values() if v) / len(checks)

        if passed:
            self.checks_passed += 1
        else:
            self.checks_failed += 1

        return {
            "passed": passed,
            "score": score,
            "checks": checks,
            "reasoning": "Built-in safety analysis" + (f" — {len(warnings)} warnings" if warnings else " — all clear"),
            "warnings": warnings,
            "provider": "builtin",
        }

    def get_stats(self) -> Dict[str, Any]:
        return {
            "checks_run": self.checks_run,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "pass_rate": self.checks_passed / max(self.checks_run, 1),
        }


safety_checker = SafetyChecker()
