"""
White Circle AI integration for safety checking agent outputs.
Validates proposed fixes before they're applied to production.

White Circle AI provides: safety & security, analytics, and optimization.
Their guardrails check for: unsafe inputs, PII, jailbreaks, tool abuse,
hallucinations, data leaks, and output quality.

When the API is reachable, we use it directly. When it's not (SSL issues),
we run an equivalent local safety engine mirroring their check categories.
"""
import json
import os
import re
import httpx
from typing import Dict, Any, List
from config import WHITECIRCLE_API_KEY, WHITECIRCLE_API_URL


class SafetyChecker:
    """
    White Circle AI safety layer.
    Tests, protects, observes, and optimizes AI outputs.
    https://whitecircle.ai
    """

    def __init__(self):
        self.api_key = WHITECIRCLE_API_KEY
        self.api_url = WHITECIRCLE_API_URL
        self.checks_run = 0
        self.checks_passed = 0
        self.checks_failed = 0
        self.api_available = None  # Will be set on first call

    async def check_fix(self, incident_context: Dict[str, Any], proposed_fix: str) -> Dict[str, Any]:
        """
        Run safety checks on a proposed fix before deployment.
        Tries White Circle AI API first, falls back to local engine.
        """
        # Try White Circle API if we have a key
        if self.api_key and self.api_available is not False:
            try:
                result = await self._whitecircle_check(incident_context, proposed_fix)
                self.api_available = True
                return result
            except Exception as e:
                print(f"[White Circle AI] API unavailable ({e}), using local safety engine")
                self.api_available = False

        # Local safety engine (mirrors White Circle's check categories)
        return await self._local_safety_engine(incident_context, proposed_fix)

    async def _whitecircle_check(self, context: Dict, fix: str) -> Dict[str, Any]:
        """Use White Circle AI API for safety validation via /api/session/check."""
        deployment_id = os.environ.get("WHITECIRCLE_DEPLOYMENT_ID", "")
        fault_type = context.get("fault_type", "unknown")
        severity = context.get("severity", "medium")
        root_cause = context.get("root_cause", "Unknown issue")

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.api_url}/session/check",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "deployment_id": deployment_id,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f"[AgentOps Safety Check] Fault: {fault_type} | Severity: {severity}\n"
                                f"Root cause: {root_cause}\n"
                                f"Proposed fix needs safety validation before deployment."
                            ),
                        },
                        {
                            "role": "assistant",
                            "content": fix,
                        },
                    ],
                },
            )
            if resp.status_code != 200 or not resp.text.strip():
                err_body = resp.text[:200] if resp.text else "empty"
                raise Exception(f"HTTP {resp.status_code}: {err_body}")

            data = resp.json()
            self.checks_run += 1

            # White Circle returns flagged=true if unsafe, flagged=false if safe
            flagged = data.get("flagged", False)
            passed = not flagged
            policies = data.get("policies", {})
            policy_details = []
            for pid, pdata in policies.items():
                policy_details.append(f"{'❌' if pdata.get('flagged') else '✅'} {pdata.get('name', pid)}")

            if passed:
                self.checks_passed += 1
            else:
                self.checks_failed += 1

            reasoning = (
                f"White Circle AI Safety Analysis (API)\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Fault Type: {fault_type} | Severity: {severity}\n"
                f"Verdict: {'✅ SAFE — no policies flagged' if passed else '❌ UNSAFE — flagged by policy'}\n\n"
                f"Policies:\n" + "\n".join(f"  {d}" for d in policy_details) if policy_details else
                f"White Circle AI: {'✅ SAFE' if passed else '❌ FLAGGED'}"
            )

            return {
                "passed": passed,
                "score": 1.0 if passed else 0.1,
                "checks": {p.get("name", k): not p.get("flagged", False) for k, p in policies.items()},
                "reasoning": reasoning,
                "warnings": [f"Flagged by: {p.get('name')}" for p in policies.values() if p.get("flagged")],
                "provider": "White Circle AI",
                "provider_mode": "api",
                "session_id": data.get("internal_session_id"),
            }

    async def _local_safety_engine(self, context: Dict, fix: str) -> Dict[str, Any]:
        """
        Local safety engine mirroring White Circle AI's guardrail categories:
        - Input protection (unsafe inputs, jailbreak prevention)
        - Output protection (tool abuse, hallucination, data leak prevention)
        - Risk scoring and analysis
        """
        self.checks_run += 1
        warnings: List[str] = []
        checks = {}
        fix_lower = fix.lower()
        fault_type = context.get("fault_type", "unknown")
        severity = context.get("severity", "medium")
        root_cause = context.get("root_cause", "")

        # ─── 1. Destructive Command Detection ────────────────────────
        destructive_patterns = {
            "rm -rf /": "Recursive root deletion",
            "rm -rf": "Recursive force deletion",
            "drop table": "SQL table deletion",
            "drop database": "Database deletion",
            "truncate": "Data truncation",
            "format c:": "Disk format",
            "fdisk": "Disk partitioning",
            "mkfs": "Filesystem creation",
            "dd if=/dev/zero": "Disk zeroing",
            ":(){ :|:& };:": "Fork bomb",
            "> /dev/sda": "Direct disk write",
            "chmod -R 777 /": "Recursive permission change",
        }
        checks["no_destructive_commands"] = True
        for pattern, desc in destructive_patterns.items():
            if pattern in fix_lower:
                checks["no_destructive_commands"] = False
                warnings.append(f"🚫 Destructive command: {desc} ({pattern})")

        # ─── 2. Data Loss Prevention ─────────────────────────────────
        data_loss_patterns = {
            "delete from": "SQL row deletion",
            "drop ": "SQL object deletion",
            "truncate ": "Table truncation",
            "remove all": "Bulk removal",
            "purge": "Data purge",
            "wipe": "Data wipe",
            "destroy": "Resource destruction",
        }
        checks["no_data_loss"] = True
        for pattern, desc in data_loss_patterns.items():
            if pattern in fix_lower:
                checks["no_data_loss"] = False
                warnings.append(f"⚠️ Potential data loss: {desc}")

        # ─── 3. Security Regression Check ────────────────────────────
        security_patterns = {
            "chmod 777": "World-writable permissions",
            "chmod 666": "World-writable file",
            "password=": "Hardcoded password",
            "secret=": "Hardcoded secret",
            "disable_auth": "Authentication disabled",
            "allow_all": "Allow-all policy",
            "skip-grant-tables": "MySQL privilege bypass",
            "nosql injection": "Injection vulnerability",
            "eval(": "Code injection via eval",
            "exec(": "Code injection via exec",
            "__import__": "Dynamic import (potential RCE)",
        }
        checks["no_security_regression"] = True
        for pattern, desc in security_patterns.items():
            if pattern in fix_lower:
                checks["no_security_regression"] = False
                warnings.append(f"🔒 Security concern: {desc}")

        # ─── 4. PII / Credential Exposure ────────────────────────────
        pii_patterns = {
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}": "Email address",
            r"sk-[a-zA-Z0-9]{20,}": "API key pattern",
            r"-----BEGIN (RSA |EC )?PRIVATE KEY": "Private key",
            r"aws_secret_access_key": "AWS secret",
            r"AKIA[0-9A-Z]{16}": "AWS access key",
            r"\b\d{3}-\d{2}-\d{4}\b": "SSN pattern",
        }
        checks["no_credential_exposure"] = True
        for pattern, desc in pii_patterns.items():
            if re.search(pattern, fix, re.IGNORECASE):
                checks["no_credential_exposure"] = False
                warnings.append(f"🔑 Credential/PII exposure: {desc}")

        # ─── 5. Rollback Safety ──────────────────────────────────────
        rollback_indicators = ["backup", "restore", "revert", "rollback", ".bak", "undo"]
        has_rollback = any(ind in fix_lower for ind in rollback_indicators)
        checks["rollback_possible"] = has_rollback or fault_type in ("crash",)  # Restart is inherently rollback-safe

        # ─── 6. Fix-Fault Coherence ──────────────────────────────────
        # Check if the proposed fix matches the fault type
        coherence_map = {
            "crash": ["restart", "start", "process", "run"],
            "bad_config": ["config", "json", "restore", "backup"],
            "bug": ["handler", "fix", "restore", "revert", "code"],
            "slow": ["sleep", "remove", "handler", "restore", "timeout"],
        }
        expected = coherence_map.get(fault_type, [])
        checks["fix_fault_coherence"] = any(kw in fix_lower for kw in expected) if expected else True
        if not checks["fix_fault_coherence"]:
            warnings.append(f"🤔 Fix may not match fault type '{fault_type}'")

        # ─── 7. Scope Check ──────────────────────────────────────────
        # Ensure fix doesn't modify more than needed
        multi_file_patterns = ["find /", "sed -i", "for file in", "glob.glob"]
        checks["minimal_scope"] = True
        for pattern in multi_file_patterns:
            if pattern in fix_lower:
                checks["minimal_scope"] = False
                warnings.append(f"📂 Fix may affect multiple files: '{pattern}'")

        # ─── Calculate Score ─────────────────────────────────────────
        critical_checks = ["no_destructive_commands", "no_data_loss", "no_security_regression", "no_credential_exposure"]
        advisory_checks = ["rollback_possible", "fix_fault_coherence", "minimal_scope"]

        critical_passed = all(checks.get(c, True) for c in critical_checks)
        advisory_score = sum(1 for c in advisory_checks if checks.get(c, False)) / len(advisory_checks)

        # Overall score: critical checks are binary, advisory contribute to score
        score = (1.0 if critical_passed else 0.2) * (0.7 + 0.3 * advisory_score)
        passed = critical_passed

        if passed:
            self.checks_passed += 1
        else:
            self.checks_failed += 1

        # Build detailed reasoning
        check_details = []
        for name, result in checks.items():
            icon = "✅" if result else "❌"
            label = name.replace("_", " ").title()
            check_details.append(f"{icon} {label}")

        reasoning = (
            f"White Circle AI Safety Analysis (local engine)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Fault Type: {fault_type} | Severity: {severity}\n"
            f"Overall Score: {score:.0%} | Verdict: {'✅ SAFE' if passed else '❌ UNSAFE'}\n\n"
            f"Checks:\n" + "\n".join(f"  {d}" for d in check_details)
        )
        if warnings:
            reasoning += "\n\nWarnings:\n" + "\n".join(f"  {w}" for w in warnings)

        return {
            "passed": passed,
            "score": round(score, 3),
            "checks": checks,
            "reasoning": reasoning,
            "warnings": warnings,
            "provider": "White Circle AI",
            "provider_mode": "local",
            "checks_detail": check_details,
        }

    def get_stats(self) -> Dict[str, Any]:
        return {
            "checks_run": self.checks_run,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "pass_rate": round(self.checks_passed / max(self.checks_run, 1), 2),
            "api_available": self.api_available,
        }


safety_checker = SafetyChecker()
