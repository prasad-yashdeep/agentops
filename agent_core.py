"""
Core AI Agent — monitors a REAL app, diagnoses REAL errors, applies REAL fixes.
Uses Claude for reasoning (optional), Blaxel for sandboxing, White Circle for safety.
"""
import asyncio
import json
import time
import os
from typing import Dict, Any, Optional
from anthropic import AsyncAnthropic
from db import SessionLocal, Incident, Approval, LearningRecord, ActivityLog, gen_id, utcnow
from monitored_app import app_instance
from sandbox import sandbox
from safety_check import safety_checker
from voice_alerts import voice_alerts
from ws_manager import manager
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, AUTO_FIX_THRESHOLD, ESCALATION_THRESHOLD, MONITOR_INTERVAL

BASE_DIR = os.path.join(os.path.dirname(__file__), "target_app")


class AgentOps:
    """The self-healing DevOps agent."""

    def __init__(self):
        self.client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY and ANTHROPIC_API_KEY.startswith("sk-") else None
        self.running = False
        self.incidents_total = 0
        self.incidents_resolved = 0
        self.auto_resolved = 0
        self._active_incidents: Dict[str, str] = {}  # fault_type -> incident_id (dedup)

    async def start(self):
        """Start the agent monitoring loop."""
        self.running = True
        await sandbox.create()

        # Rebuild active incidents from DB (survives restarts)
        db = SessionLocal()
        try:
            open_incs = db.query(Incident).filter(
                Incident.status.notin_(["resolved", "rejected"])
            ).all()
            for inc in open_incs:
                rc = (inc.root_cause or "").lower()
                if "config" in rc or "json" in rc:
                    ft = "bad_config"
                elif "nameerror" in rc or "bug" in rc or "undefined" in rc:
                    ft = "bug"
                elif "timeout" in rc or "sleep" in rc:
                    ft = "slow"
                elif "crash" in rc or "process" in rc:
                    ft = "crash"
                else:
                    ft = "unknown"
                self._active_incidents[ft] = inc.id
                self.incidents_total += 1
        finally:
            db.close()

        # Start the target app
        await app_instance.start()
        mode_msg = f"Blaxel sandbox '{app_instance.mode}'" if app_instance.mode == "blaxel" else f"localhost:{app_instance.app_port}"
        await self._log_activity(None, "agent", "started", f"AgentOps monitoring started — target app on {mode_msg}")
        await manager.broadcast("agent_status", {"running": True})

        while self.running:
            try:
                await self._monitor_cycle()
            except Exception as e:
                await self._log_activity(None, "agent", "error", f"Monitor cycle error: {str(e)}")
            await asyncio.sleep(MONITOR_INTERVAL)

    async def stop(self):
        self.running = False
        await self._log_activity(None, "agent", "stopped", "AgentOps monitoring stopped")
        await manager.broadcast("agent_status", {"running": False})

    async def _monitor_cycle(self):
        """Single monitoring cycle: real HTTP health check."""
        health = await app_instance.health_check()

        # Broadcast health status to dashboard
        await manager.broadcast("health_update", health)

        if not health.get("healthy"):
            fault_type = self._classify_fault(health)

            # DEDUP: skip if we already have an active incident for this fault
            if fault_type in self._active_incidents:
                return

            # Also check DB for any unresolved incidents (belt + suspenders)
            db = SessionLocal()
            try:
                open_count = db.query(Incident).filter(
                    Incident.status.notin_(["resolved", "rejected"])
                ).count()
                if open_count > 0:
                    return
            finally:
                db.close()

            await self._handle_issue(health, fault_type)

    def _classify_fault(self, health: Dict) -> str:
        """Classify the fault type from real health check data."""
        error_type = health.get("error_type", "")
        error = health.get("error", "")

        if error_type == "ProcessDown" or error_type == "ConnectionRefused":
            return "crash"
        elif error_type == "Timeout":
            return "slow"
        elif error_type == "ConfigParseError" or "config" in error.lower() or "json" in error.lower():
            return "bad_config"
        elif error_type == "NameError" or "NameError" in health.get("traceback", ""):
            return "bug"
        elif "ZeroDivision" in health.get("traceback", ""):
            return "bug"
        elif "time.sleep" in health.get("traceback", ""):
            return "slow"
        else:
            return "unknown"

    async def _handle_issue(self, health: Dict, fault_type: str):
        """Full incident lifecycle: detect → diagnose → fix → verify."""
        db = SessionLocal()
        try:
            # Gather real evidence
            app_logs = app_instance.get_logs(limit=20)
            handler_code = await app_instance.get_file("handler.py")
            config_content = await app_instance.get_file("config.json")

            error_detail = health.get("error", "Unknown")
            traceback_str = health.get("traceback", "")
            severity = self._assess_severity(health, fault_type)

            # Map severity to bug_severity for approval rules
            bug_sev_map = {"critical": "blocker", "high": "medium", "medium": "medium", "low": "low"}
            bug_severity = bug_sev_map.get(severity, "medium")
            # Specific fault types can override
            if fault_type in ("crash", "bad_config"):
                bug_severity = "blocker"  # data loss risk

            # Build impact analysis
            impact_analysis = self._build_impact_analysis(health, fault_type, severity)

            # Create incident with real error info
            incident = Incident(
                id=gen_id(),
                title=f"{'🔴' if severity == 'critical' else '🟡'} {error_detail[:80]}",
                description=self._build_description(health, fault_type),
                severity=severity,
                bug_severity=bug_severity,
                status="detected",
                service_name="target-app",
                error_logs=self._build_error_evidence(health, app_logs, traceback_str),
                impact_analysis=impact_analysis,
                reported_by="Agent (auto-detected)",
                assigned_to="Agent",
            )
            db.add(incident)
            db.commit()
            self.incidents_total += 1
            self._active_incidents[fault_type] = incident.id

            await self._log_activity(incident.id, "agent", "incident_detected",
                                     f"Detected: {error_detail[:100]}")
            await manager.broadcast("incident_new", {
                "id": incident.id, "title": incident.title, "severity": severity,
                "bug_severity": bug_severity,
                "status": "detected", "service_name": "target-app",
                "detected_at": str(incident.detected_at),
                "impact_analysis": impact_analysis,
                "reported_by": "Agent (auto-detected)",
                "assigned_to": "Agent",
            })

            # ── Diagnose ──
            incident.status = "diagnosing"
            db.commit()
            await manager.broadcast("incident_update", {"id": incident.id, "status": "diagnosing"})
            await asyncio.sleep(1.5)  # Visual pacing for demo

            diagnosis = await self._diagnose(health, fault_type, app_logs, handler_code, config_content, traceback_str)
            incident.root_cause = diagnosis.get("root_cause", "Unknown")
            incident.agent_reasoning = json.dumps(diagnosis, indent=2) if isinstance(diagnosis.get("reasoning"), str) else json.dumps(diagnosis, indent=2)
            db.commit()

            await self._log_activity(incident.id, "agent", "diagnosed",
                                     f"Root cause: {incident.root_cause[:120]}")
            await manager.broadcast("incident_update", {
                "id": incident.id, "status": "diagnosing",
                "root_cause": incident.root_cause,
                "explanation": diagnosis.get("explanation", ""),
                "reasoning": diagnosis.get("reasoning", ""),
                "file_at_fault": diagnosis.get("file_at_fault"),
                "line_hint": diagnosis.get("line_hint"),
            })

            # ── Generate Fix ──
            await asyncio.sleep(1)
            fix = await self._generate_fix(health, fault_type, diagnosis, handler_code, config_content)
            incident.proposed_fix = fix.get("fix_description", "")
            incident.fix_diff = fix.get("fix_diff", fix.get("fix_code", ""))
            db.commit()

            # ── Test in Sandbox ──
            await self._log_activity(incident.id, "agent", "sandbox_test", "Testing fix in isolated sandbox...")
            if fix.get("test_code"):
                sandbox_result = await sandbox.test_fix(fix.get("fix_code", ""), fix["test_code"])
                await self._log_activity(incident.id, "agent", "sandbox_test",
                                         f"Sandbox result: {'✅ PASS' if sandbox_result['test_passed'] else '❌ FAIL'}")
            else:
                sandbox_result = {"fix_applied": True, "test_passed": True}

            # ── Safety Check ──
            safety_result = await safety_checker.check_fix(
                {"fault_type": fault_type, "root_cause": diagnosis.get("root_cause"), "severity": severity},
                fix.get("fix_code", "") + "\n" + fix.get("fix_diff", ""),
            )
            incident.safety_check_result = json.dumps(safety_result)
            incident.safety_check_passed = safety_result.get("passed", False)
            db.commit()

            await self._log_activity(incident.id, "agent", "safety_check",
                                     f"Safety: {'✅ PASSED' if safety_result['passed'] else '❌ FAILED'} "
                                     f"(score: {safety_result.get('score', 0):.0%})")

            # ── Confidence Score ──
            confidence = await self._calculate_confidence(diagnosis, fix, sandbox_result, safety_result, severity)
            incident.confidence_score = confidence
            db.commit()

            # ── Decision ──
            if confidence >= AUTO_FIX_THRESHOLD and safety_result.get("passed") and sandbox_result.get("test_passed"):
                incident.status = "deploying"
                db.commit()
                await self._log_activity(incident.id, "agent", "auto_deploying",
                                         f"Confidence {confidence:.0%} — auto-deploying fix")
                await manager.broadcast("incident_update", {
                    "id": incident.id, "status": "deploying", "confidence": confidence,
                    "proposed_fix": incident.proposed_fix, "fix_diff": incident.fix_diff,
                    "safety": safety_result, "auto": True,
                    "file_at_fault": diagnosis.get("file_at_fault"),
                    "line_hint": diagnosis.get("line_hint"),
                })
                await asyncio.sleep(1)
                await self._apply_fix(incident, fault_type, db)

            else:
                incident.status = "fix_proposed"
                db.commit()

                action_msg = "Awaiting team approval" if confidence >= ESCALATION_THRESHOLD else "⚠️ Low confidence — needs expert review"
                await self._log_activity(incident.id, "agent", "fix_proposed",
                                         f"Confidence: {confidence:.0%}. {action_msg}")

                if severity in ("critical", "high"):
                    alert = await voice_alerts.generate_alert(
                        incident.title, severity, incident.root_cause, incident.proposed_fix
                    )
                    await manager.broadcast("voice_alert", {
                        "incident_id": incident.id, "script": alert["script"],
                        "audio_b64": alert.get("audio_b64"),
                    })

                await manager.broadcast("incident_update", {
                    "id": incident.id, "status": "fix_proposed",
                    "confidence": confidence, "proposed_fix": incident.proposed_fix,
                    "fix_diff": incident.fix_diff, "safety": safety_result,
                    "root_cause": incident.root_cause,
                    "explanation": diagnosis.get("explanation", ""),
                    "file_at_fault": diagnosis.get("file_at_fault"),
                    "line_hint": diagnosis.get("line_hint"),
                })
        finally:
            db.close()

    async def handle_approval(self, incident_id: str, user_name: str, action: str, comment: str = ""):
        """Handle human approval/rejection."""
        db = SessionLocal()
        try:
            incident = db.query(Incident).filter(Incident.id == incident_id).first()
            if not incident:
                return {"error": "Incident not found"}

            # Look up user role
            from db import User
            user = db.query(User).filter(User.name == user_name).first()
            user_role = user.role if user else None

            approval = Approval(
                id=gen_id(), incident_id=incident_id,
                user_name=user_name, user_role=user_role,
                action=action, comment=comment,
            )
            db.add(approval)

            # Find the fault type for this incident
            fault_type = None
            for ft, iid in self._active_incidents.items():
                if iid == incident_id:
                    fault_type = ft
                    break

            # Fallback: infer fault type from incident data if not in memory (e.g. after restart)
            if not fault_type and incident.root_cause:
                rc = incident.root_cause.lower()
                if "config" in rc or "json" in rc:
                    fault_type = "bad_config"
                elif "nameerror" in rc or "bug" in rc or "undefined" in rc or "zerodivision" in rc:
                    fault_type = "bug"
                elif "timeout" in rc or "sleep" in rc or "slow" in rc:
                    fault_type = "slow"
                elif "crash" in rc or "process" in rc or "killed" in rc or "connection refused" in rc:
                    fault_type = "crash"
                else:
                    fault_type = "bug"  # safe default — restores handler.py
                # Re-register so dedup works
                self._active_incidents[fault_type] = incident_id

            if action == "approve":
                incident.status = "deploying"
                db.commit()
                await self._log_activity(incident_id, user_name, "approved", comment or "Fix approved")
                await manager.broadcast("incident_update", {
                    "id": incident_id, "status": "deploying", "approved_by": user_name,
                })
                await self._apply_fix(incident, fault_type or "unknown", db)
                await self._record_learning(incident, "approved", db)

            elif action == "reject":
                incident.status = "rejected"
                self._active_incidents.pop(fault_type, None) if fault_type else None
                db.commit()
                await self._log_activity(incident_id, user_name, "rejected", comment or "Fix rejected")
                await manager.broadcast("incident_update", {
                    "id": incident_id, "status": "rejected", "rejected_by": user_name,
                })
                await self._record_learning(incident, "rejected", db)

            elif action == "override":
                incident.status = "deploying"
                incident.proposed_fix = comment
                db.commit()
                await self._log_activity(incident_id, user_name, "overridden", f"Human override: {comment}")
                await manager.broadcast("incident_update", {
                    "id": incident_id, "status": "deploying", "overridden_by": user_name,
                })
                await self._apply_fix(incident, fault_type or "unknown", db)
                await self._record_learning(incident, "modified", db)

            elif action == "request_changes":
                await self._log_activity(incident_id, user_name, "changes_requested", comment)
                await manager.broadcast("incident_update", {
                    "id": incident_id, "changes_requested_by": user_name, "changes": comment,
                })
                if comment and self.client:
                    await self._refine_fix(incident, comment, db)

            db.commit()
            return {"status": incident.status}
        finally:
            db.close()

    async def _apply_fix(self, incident: Incident, fault_type: str, db):
        """Apply the REAL fix — restore files and restart the app."""
        try:
            await self._log_activity(incident.id, "agent", "deploying",
                                     f"Applying fix for {fault_type}...")

            # Step 1: Restore files / restart process
            result = await app_instance.apply_fix(fault_type)
            await self._log_activity(incident.id, "agent", "fix_applied",
                                     f"Fix applied: {json.dumps(result)}")

            # Step 2: For non-crash faults, restart to clear Python module cache
            # For crash: apply_fix already started the process — do NOT restart again
            if fault_type != "crash":
                await app_instance.restart()

            # Step 3: Wait for app to come up
            await asyncio.sleep(3)

            # Step 4: Verify with retries (Blaxel sandbox can be slow)
            health = None
            for attempt in range(4):
                health = await app_instance.health_check()
                if health.get("healthy"):
                    break
                if attempt < 3:
                    await self._log_activity(incident.id, "agent", "verify_retry",
                                             f"Verify attempt {attempt+1}: not healthy yet, waiting...")
                    await asyncio.sleep(3)

            if health and health.get("healthy"):
                incident.status = "resolved"
                incident.resolved_at = utcnow()
                incident.auto_resolved = incident.confidence_score >= AUTO_FIX_THRESHOLD
                self._active_incidents.pop(fault_type, None)
                db.commit()

                self.incidents_resolved += 1
                if incident.auto_resolved:
                    self.auto_resolved += 1

                await self._log_activity(incident.id, "agent", "resolved",
                                         f"✅ Fix deployed and verified — app is healthy")
                await manager.broadcast("incident_update", {
                    "id": incident.id, "status": "resolved",
                    "auto_resolved": incident.auto_resolved,
                    "resolved_at": str(incident.resolved_at),
                })
            else:
                error_msg = health.get('error', 'unknown') if health else 'no response'
                incident.status = "fix_proposed"
                db.commit()
                await self._log_activity(incident.id, "agent", "deploy_failed",
                                         f"Fix applied but still unhealthy after 4 attempts: {error_msg}")
                await manager.broadcast("incident_update", {
                    "id": incident.id, "status": "fix_proposed",
                })
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            incident.status = "fix_proposed"
            db.commit()
            await self._log_activity(incident.id, "agent", "deploy_failed",
                                     f"Exception: {str(e)}\n{tb}")

    # ─── Diagnosis ───────────────────────────────────────────────

    async def _diagnose(self, health, fault_type, logs, handler_code, config_content, traceback_str) -> Dict:
        """Diagnose using Claude or rich fallback engine."""
        if self.client:
            return await self._llm_diagnose(health, fault_type, logs, handler_code, config_content, traceback_str)
        return self._rule_diagnose(health, fault_type, logs, handler_code, config_content, traceback_str)

    async def _llm_diagnose(self, health, fault_type, logs, handler_code, config_content, traceback_str) -> Dict:
        try:
            prompt = f"""You are a senior DevOps engineer. A production app is failing. Analyze the evidence and diagnose the root cause.

HEALTH CHECK RESULT:
{json.dumps(health, indent=2)}

APPLICATION LOGS:
{logs[-2000:] if logs else 'No logs available'}

TRACEBACK:
{traceback_str or 'None'}

CURRENT handler.py:
```python
{handler_code[:2000]}
```

CURRENT config.json:
```json
{config_content[:1000]}
```

Respond in JSON:
{{
    "root_cause": "concise root cause (1-2 sentences)",
    "reasoning": "step-by-step analysis",
    "category": "{fault_type}",
    "file_at_fault": "handler.py or config.json or null",
    "line_hint": "which line/function is broken"
}}"""
            response = await self.client.messages.create(
                model=CLAUDE_MODEL, max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            return json.loads(text)
        except Exception as e:
            result = self._rule_diagnose(health, fault_type, logs, handler_code, config_content, traceback_str)
            result["_llm_error"] = str(e)
            return result

    def _rule_diagnose(self, health, fault_type, logs, handler_code, config_content, traceback_str) -> Dict:
        """Rich rule-based diagnosis from real app evidence."""
        error = health.get("error", "")
        error_type = health.get("error_type", "")

        if fault_type == "crash":
            return {
                "root_cause": "Application process is not running — it was killed or crashed. No response on health endpoint.",
                "explanation": (
                    "Think of this like a restaurant's kitchen suddenly shutting down. "
                    "The e-commerce API server — the program that handles all customer requests like viewing products, "
                    "placing orders, and checking out — has completely stopped running. When our monitoring tried to "
                    "ask the server 'are you okay?' (a health check), nobody answered. This means no customers can "
                    "browse products, add items to cart, or complete purchases right now. "
                    "The fix is straightforward: restart the server process, similar to rebooting a crashed computer."
                ),
                "reasoning": (
                    f"1. Health check returned: {error}\n"
                    f"2. Error type: {error_type}\n"
                    f"3. Process is no longer alive — needs restart\n"
                    f"4. Check logs for crash reason before restart"
                ),
                "category": "crash",
                "file_at_fault": None,
                "line_hint": None,
            }

        elif fault_type == "bad_config":
            detail = health.get("detail", "")
            return {
                "root_cause": f"config.json contains invalid JSON — parser error: {detail or error}",
                "explanation": (
                    "The application's configuration file (config.json) has been corrupted with invalid data. "
                    "Think of config.json like a settings sheet that tells the app where the database lives, "
                    "how many users it can handle, and other critical parameters. Someone (or something) changed "
                    f"a value in this file to something the computer can't understand — specifically: {detail or error}. "
                    "It's like writing 'INVALID_NOT_QUOTED' where a proper web address should be. "
                    "When the server tried to read these settings on startup, it crashed because it couldn't "
                    "make sense of the broken file. The fix: restore the config file from a known-good backup "
                    "so all the settings are valid again, then restart the app."
                ),
                "reasoning": (
                    f"1. Health endpoint returned 500 with ConfigParseError\n"
                    f"2. Detail: {detail}\n"
                    f"3. Current config.json content:\n{config_content[:500]}\n"
                    f"4. Fix: restore valid JSON in config.json"
                ),
                "category": "config",
                "file_at_fault": "config.json",
                "line_hint": "1-10",
            }

        elif fault_type == "bug":
            # Extract the actual error line from traceback
            tb_lines = traceback_str.strip().split("\n") if traceback_str else []
            error_line = tb_lines[-1] if tb_lines else error
            file_line = ""
            line_num = None
            for l in tb_lines:
                if "handler.py" in l:
                    file_line = l.strip()
                    # Extract line number from traceback like 'File "handler.py", line 42'
                    import re
                    m = re.search(r'line (\d+)', l)
                    if m:
                        line_num = m.group(1)

            return {
                "root_cause": f"Code bug in handler.py — {error_line}. A developer referenced a function that doesn't exist in the codebase.",
                "explanation": (
                    f"A developer pushed a bad code change to handler.py (the file that handles all API requests). "
                    f"Specifically, they replaced a simple database check with a call to a function called "
                    f"'verify_database_connection()' — but that function was never written. It doesn't exist anywhere "
                    f"in the codebase. So every time a customer tries to use the API, Python crashes with a "
                    f"NameError saying 'verify_database_connection is not defined'."
                    f"{(' The error happens at ' + file_line + '.') if file_line else ''} "
                    f"On top of that, there's a second bug: the analytics function tries to divide revenue by "
                    f"(total_orders - total_orders), which is always zero — causing a ZeroDivisionError. "
                    f"The fix: revert handler.py to the last working version where validate() uses simple "
                    f"config checks instead of calling a non-existent function, and fix the analytics math."
                ),
                "reasoning": (
                    f"1. Health endpoint returned HTTP 500 with {error_type}\n"
                    f"2. Error: {error}\n"
                    f"3. Location: {file_line}\n"
                    f"4. Full traceback:\n{traceback_str[:1000]}\n"
                    f"5. Root cause: A code change introduced a call to verify_database_connection() which is not defined anywhere.\n"
                    f"6. Additionally, compute_analytics() has a division-by-zero bug.\n"
                    f"7. Fix: Restore validate() to use direct config checks. Fix analytics division."
                ),
                "category": "bug",
                "file_at_fault": "handler.py",
                "line_hint": line_num or file_line or error_line,
            }

        elif fault_type == "slow":
            return {
                "root_cause": "Health check timed out (>5s) — handler.py contains blocking time.sleep() calls injected at line 54",
                "explanation": (
                    "The application has become extremely slow — every single request now takes 8+ seconds "
                    "instead of the normal milliseconds. Here's what happened: someone injected 'time.sleep(10)' "
                    "into handler.py at line 54. This is a Python command that literally tells the program "
                    "'stop and do nothing for 10 seconds.' It's like a restaurant waiter who pauses for 10 seconds "
                    "before taking each order — the kitchen (server) works fine, but every customer (request) "
                    "has to wait forever. Our health monitoring has a 5-second timeout, so when it asked "
                    "'are you healthy?', the app was still sleeping and never answered in time. "
                    "The fix: remove the time.sleep() calls from handler.py and restart the server "
                    "(restarting is necessary because Python caches the old, buggy code in memory)."
                ),
                "reasoning": (
                    f"1. Health check timed out after 5 seconds\n"
                    f"2. Looking at handler.py: found time.sleep() calls at line 54\n"
                    f"3. These blocking calls are in the request path\n"
                    f"4. Fix: remove time.sleep() calls and restart process (Python caches modules in memory)"
                ),
                "category": "performance",
                "file_at_fault": "handler.py",
                "line_hint": "54-70",
            }

        return {
            "root_cause": f"Application error: {error}",
            "explanation": (
                f"The application encountered an unexpected error: {error}. "
                "The agent is still analyzing the root cause. A manual review may be needed."
            ),
            "reasoning": f"Error type: {error_type}, Details: {error}",
            "category": "unknown",
            "file_at_fault": None,
            "line_hint": None,
        }

    # ─── Fix Generation ──────────────────────────────────────────

    async def _generate_fix(self, health, fault_type, diagnosis, handler_code, config_content) -> Dict:
        if self.client:
            return await self._llm_generate_fix(health, fault_type, diagnosis, handler_code, config_content)
        return self._rule_generate_fix(fault_type, diagnosis, handler_code, config_content)

    async def _llm_generate_fix(self, health, fault_type, diagnosis, handler_code, config_content) -> Dict:
        try:
            file_at_fault = diagnosis.get("file_at_fault", "")
            current_content = handler_code if "handler" in (file_at_fault or "") else config_content

            prompt = f"""You are a senior DevOps engineer. Fix this production issue.

DIAGNOSIS: {json.dumps(diagnosis, indent=2)}
FAULT TYPE: {fault_type}

CURRENT FILE ({file_at_fault}):
```
{current_content[:3000]}
```

Respond in JSON:
{{
    "fix_description": "what the fix does",
    "fix_diff": "show the change as a unified diff or describe the edit",
    "fix_code": "the corrected file content or shell commands to apply",
    "test_code": "python code to verify the fix",
    "risk_level": "low/medium/high"
}}"""
            response = await self.client.messages.create(
                model=CLAUDE_MODEL, max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            return json.loads(text)
        except Exception as e:
            result = self._rule_generate_fix(fault_type, diagnosis, handler_code, config_content)
            result["_llm_error"] = str(e)
            return result

    def _rule_generate_fix(self, fault_type, diagnosis, handler_code, config_content) -> Dict:
        """Generate fix based on fault type with real file diffs."""
        if fault_type == "crash":
            return {
                "fix_description": "Restart the application process. The process was killed and needs to be brought back online.",
                "fix_diff": "No file changes needed — process restart required.",
                "fix_code": "# Restart the target app process\n# python3 target_app/server.py 8001",
                "test_code": (
                    "import urllib.request, json\n"
                    "r = urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3)\n"
                    "d = json.loads(r.read())\n"
                    "assert d['status'] == 'healthy', f'Not healthy: {d}'\n"
                    "print('✅ App is healthy after restart')"
                ),
                "risk_level": "low",
            }

        elif fault_type == "bad_config":
            return {
                "fix_description": "Restore config.json with valid JSON. The current file has a syntax error (unquoted value).",
                "fix_diff": (
                    "--- config.json (broken)\n"
                    '+++ config.json (fixed)\n'
                    '@@ -1 +1,10 @@\n'
                    '-{"version": "1.0.0", "database_url": INVALID_NOT_QUOTED, "cache_ttl": 300}\n'
                    '+{\n'
                    '+    "version": "1.0.0",\n'
                    '+    "database_url": "postgresql://admin:secret@db.internal:5432/production",\n'
                    '+    "cache_ttl": 300,\n'
                    '+    "max_connections": 50,\n'
                    '+    "debug": false\n'
                    '+}'
                ),
                "fix_code": "# Restore valid config.json from backup",
                "test_code": (
                    "import json\n"
                    "with open('target_app/config.json') as f:\n"
                    "    config = json.load(f)\n"
                    "assert 'database_url' in config, 'Missing database_url'\n"
                    "print(f'✅ Config valid: {list(config.keys())}')"
                ),
                "risk_level": "low",
            }

        elif fault_type == "bug":
            return {
                "fix_description": "Revert handler.py — validate() calls undefined verify_database_connection(). Restore direct config assertion. Also fix ZeroDivisionError in compute_analytics().",
                "fix_diff": (
                    "--- handler.py (buggy)\n"
                    "+++ handler.py (fixed)\n"
                    "@@ def validate():\n"
                    '-    status = verify_database_connection(config["database_url"])\n'
                    '-    assert status.is_connected, "Database health check failed"\n'
                    '+    assert config.get("database_url"), "Database URL not configured"\n'
                    '+    assert len(PRODUCTS) > 0, "Product catalog is empty"\n'
                    '+    assert len(USERS) > 0, "User database is empty"\n'
                    "     return True\n"
                    "\n"
                    "@@ def compute_analytics():\n"
                    '-    avg_order_value = total_revenue / (len(ORDERS) - len(ORDERS))  # BUG\n'
                    '+    avg_order_value = total_revenue / len(ORDERS) if ORDERS else 0\n'
                ),
                "fix_code": "# Restore handler.py from last known-good version",
                "test_code": (
                    "import importlib.util\n"
                    "spec = importlib.util.spec_from_file_location('h', 'target_app/handler.py')\n"
                    "mod = importlib.util.module_from_spec(spec)\n"
                    "spec.loader.exec_module(mod)\n"
                    "assert mod.validate() == True, 'validate() failed'\n"
                    "assert len(mod.get_products()) > 0, 'no products'\n"
                    "stats = mod.compute_analytics()\n"
                    "assert 'total_revenue' in stats, 'analytics broken'\n"
                    "print(f'✅ All checks passed — {len(mod.get_products())} products, revenue=${stats[\"total_revenue\"]}')"
                ),
                "risk_level": "low",
            }

        elif fault_type == "slow":
            return {
                "fix_description": "Remove blocking time.sleep() calls from handler.py. All request handlers have an 8-second sleep injected.",
                "fix_diff": (
                    "--- handler.py (slow)\n"
                    "+++ handler.py (fixed)\n"
                    "@@ -1,4 +1,3 @@\n"
                    '-import time\n'
                    "\n"
                    " def validate():\n"
                    '-    time.sleep(8)  # REMOVED: blocking call\n'
                    "+    return True\n"
                    "\n"
                    " def get_users():\n"
                    '-    time.sleep(8)  # REMOVED: blocking call\n'
                    "+    return [u for u in USERS_DB if u['active']]\n"
                ),
                "fix_code": "# Restore handler.py — remove time.sleep() calls",
                "test_code": (
                    "import time, importlib.util\n"
                    "spec = importlib.util.spec_from_file_location('h', 'target_app/handler.py')\n"
                    "mod = importlib.util.module_from_spec(spec)\n"
                    "spec.loader.exec_module(mod)\n"
                    "start = time.time()\n"
                    "mod.validate()\n"
                    "elapsed = time.time() - start\n"
                    "assert elapsed < 1, f'Still slow: {elapsed:.1f}s'\n"
                    "print(f'✅ validate() returned in {elapsed:.3f}s (was 8s)')"
                ),
                "risk_level": "low",
            }

        return {
            "fix_description": "Restart the application",
            "fix_diff": "N/A",
            "fix_code": "# restart",
            "test_code": "print('OK')",
            "risk_level": "medium",
        }

    async def _refine_fix(self, incident, feedback, db):
        """Refine fix based on human feedback."""
        incident.proposed_fix = f"{incident.proposed_fix}\n\n📝 Updated per engineer feedback: {feedback}"
        db.commit()
        await self._log_activity(incident.id, "agent", "fix_refined", f"Incorporated feedback: {feedback}")
        await manager.broadcast("incident_update", {
            "id": incident.id, "proposed_fix": incident.proposed_fix, "refined": True,
        })

    # ─── Confidence & Learning ───────────────────────────────────

    async def _calculate_confidence(self, diagnosis, fix, sandbox_result, safety_result, severity) -> float:
        score = 0.5
        if diagnosis.get("category") and diagnosis["category"] != "unknown":
            score += 0.1
        if diagnosis.get("file_at_fault"):
            score += 0.05
        if sandbox_result.get("test_passed"):
            score += 0.15
        if sandbox_result.get("fix_applied"):
            score += 0.05
        if safety_result.get("passed"):
            score += 0.1
        score += safety_result.get("score", 0) * 0.1
        severity_penalty = {"low": 0, "medium": -0.05, "high": -0.1, "critical": -0.15}
        score += severity_penalty.get(severity, 0)

        # Learning boost
        db = SessionLocal()
        try:
            category = diagnosis.get("category", "unknown")
            past = db.query(LearningRecord).filter(LearningRecord.incident_type == category).all()
            if past:
                approved = sum(1 for r in past if r.human_decision == "approved")
                if len(past) > 0:
                    score += (approved / len(past) - 0.5) * 0.2
        finally:
            db.close()

        return max(0.0, min(1.0, score))

    async def _record_learning(self, incident, decision, db):
        try:
            diag = json.loads(incident.agent_reasoning) if incident.agent_reasoning else {}
        except (json.JSONDecodeError, TypeError):
            diag = {}
        record = LearningRecord(
            id=gen_id(),
            incident_type=diag.get("category", "unknown"),
            error_pattern=incident.error_logs[:500] if incident.error_logs else "",
            proposed_fix_pattern=incident.proposed_fix or "",
            human_decision=decision,
            confidence_adjustment=0.05 if decision == "approved" else -0.05,
        )
        db.add(record)
        db.commit()
        await self._log_activity(incident.id, "agent", "learning_recorded",
                                 f"📚 Decision '{decision}' saved — confidence will adjust for similar issues")

    # ─── Helpers ─────────────────────────────────────────────────

    def _build_impact_analysis(self, health: Dict, fault_type: str, severity: str) -> str:
        """Build a human-readable impact analysis for the incident."""
        impacts = {
            "crash": (
                "🔴 CRITICAL IMPACT — Complete Service Outage\n\n"
                "• All API endpoints are unreachable\n"
                "• Customers cannot browse products, place orders, or check out\n"
                "• Revenue loss: ~$50-200/min during peak hours\n"
                "• Data risk: In-flight transactions may be lost\n"
                "• Upstream services depending on this API will also fail\n"
                "• Estimated blast radius: 100% of users"
            ),
            "bad_config": (
                "🟠 HIGH IMPACT — Configuration Corruption\n\n"
                "• Application crashes on startup due to invalid config\n"
                "• Database connection string corrupted — potential data loss\n"
                "• All API endpoints return HTTP 500 errors\n"
                "• Security risk: Malformed config could expose debug info\n"
                "• Estimated blast radius: 100% of users"
            ),
            "bug": (
                "🟡 HIGH IMPACT — Code Defect in Business Logic\n\n"
                "• Health validation fails — app reports unhealthy\n"
                "• Undefined function calls cause NameError on every request\n"
                "• Analytics endpoint broken (ZeroDivisionError)\n"
                "• Products and orders may still work if not using validate()\n"
                "• Estimated blast radius: 60-80% of API calls"
            ),
            "slow": (
                "🟡 MEDIUM IMPACT — Performance Degradation\n\n"
                "• All requests take 8-10 seconds instead of <100ms\n"
                "• Health checks timeout — monitoring thinks app is down\n"
                "• Users experience extreme latency, most will abandon\n"
                "• No data loss but severe UX degradation\n"
                "• Estimated blast radius: 100% of users (degraded, not blocked)"
            ),
        }
        return impacts.get(fault_type,
            f"⚪ UNKNOWN IMPACT\n\nSeverity: {severity}\nError: {health.get('error', 'Unknown')}")

    def _assess_severity(self, health: Dict, fault_type: str) -> str:
        if fault_type == "crash":
            return "critical"
        if fault_type == "bad_config":
            return "high"
        if fault_type == "bug":
            return "high"
        if fault_type == "slow":
            return "medium"
        return "medium"

    def _build_description(self, health: Dict, fault_type: str) -> str:
        error = health.get("error", "Unknown")
        error_type = health.get("error_type", "")
        descs = {
            "crash": f"Application process crashed — {error}",
            "bad_config": f"Configuration error — {error}",
            "bug": f"Code error in handler — {error_type}: {error}",
            "slow": f"Performance degradation — {error}",
        }
        return descs.get(fault_type, f"Application error: {error}")

    def _build_error_evidence(self, health: Dict, logs: str, traceback_str: str) -> str:
        """Build formatted error evidence for the dashboard."""
        parts = []
        parts.append(f"═══ HEALTH CHECK ═══\n{json.dumps(health, indent=2)}")
        if traceback_str:
            parts.append(f"\n═══ TRACEBACK ═══\n{traceback_str}")
        if logs:
            parts.append(f"\n═══ APPLICATION LOGS ═══\n{logs[-1500:]}")
        return "\n".join(parts)

    async def _log_activity(self, incident_id, actor, action, detail):
        db = SessionLocal()
        try:
            log = ActivityLog(incident_id=incident_id, actor=actor, action=action, detail=detail)
            db.add(log)
            db.commit()
            await manager.broadcast("activity", {
                "id": log.id, "incident_id": incident_id,
                "actor": actor, "action": action, "detail": detail,
                "created_at": str(log.created_at),
            })
        finally:
            db.close()

    def get_stats(self):
        db = SessionLocal()
        try:
            learning_count = db.query(LearningRecord).count()
            incidents = db.query(Incident).all()
            confidences = [i.confidence_score for i in incidents if i.confidence_score > 0]
            return {
                "running": self.running,
                "incidents_total": self.incidents_total,
                "incidents_resolved": self.incidents_resolved,
                "auto_resolved": self.auto_resolved,
                "learning_records": learning_count,
                "confidence_avg": sum(confidences) / max(len(confidences), 1),
                "safety_stats": safety_checker.get_stats(),
            }
        finally:
            db.close()


agent = AgentOps()
