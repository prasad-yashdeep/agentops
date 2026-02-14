"""
ElevenLabs voice alerts for critical incidents.
Generates spoken alerts that engineers can listen to.
"""
import base64
import httpx
from typing import Optional
from config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID


class VoiceAlerts:
    """ElevenLabs-powered voice alerts for incident notifications."""

    def __init__(self):
        self.api_key = ELEVENLABS_API_KEY
        self.voice_id = ELEVENLABS_VOICE_ID

    async def generate_alert(self, incident_title: str, severity: str,
                              root_cause: str = "", proposed_fix: str = "") -> dict:
        """Generate a voice alert for an incident."""
        # Clean emoji out of title for TTS
        clean_title = incident_title.replace("🔴", "").replace("🟡", "").strip()

        if severity == "critical":
            script = f"Critical alert! {clean_title}. "
        elif severity == "high":
            script = f"High priority incident. {clean_title}. "
        else:
            script = f"New incident detected. {clean_title}. "

        if root_cause:
            # Keep root cause short for TTS
            short_cause = root_cause[:150].rsplit(" ", 1)[0] if len(root_cause) > 150 else root_cause
            script += f"Root cause analysis: {short_cause}. "

        if proposed_fix:
            short_fix = proposed_fix[:120].rsplit(" ", 1)[0] if len(proposed_fix) > 120 else proposed_fix
            script += f"Proposed fix: {short_fix}. Awaiting your approval on the dashboard."
        else:
            script += "The agent is investigating. Stand by."

        audio_b64 = await self._synthesize(script)
        return {"script": script, "audio_b64": audio_b64, "has_audio": audio_b64 is not None}

    async def generate_summary(self, stats: dict) -> dict:
        """Generate a voice summary from full agent stats."""
        total = stats.get("incidents_total", 0)
        resolved = stats.get("incidents_resolved", 0)
        auto = stats.get("auto_resolved", 0)
        learned = stats.get("learning_records", 0)
        avg_conf = stats.get("confidence_avg", 0)
        safety = stats.get("safety_stats", {})

        if total == 0:
            script = "AgentOps status report. No incidents detected yet. All monitored services are healthy. The agent is standing by."
        else:
            parts = [f"AgentOps status report. {total} incident{'s' if total != 1 else ''} detected."]
            if resolved:
                parts.append(f"{resolved} resolved.")
            if auto:
                parts.append(f"{auto} were fixed automatically by the agent without human intervention.")
            if resolved and not auto:
                parts.append(f"All fixes were approved by the engineering team.")
            if avg_conf > 0:
                parts.append(f"Average agent confidence: {avg_conf*100:.0f} percent.")
            if safety.get("checks_run", 0) > 0:
                parts.append(f"{safety['checks_passed']} of {safety['checks_run']} safety checks passed.")
            if learned:
                parts.append(f"The agent has {learned} learning records from human decisions, improving future responses.")

            pending = total - resolved
            if pending > 0:
                parts.append(f"{pending} incident{'s' if pending != 1 else ''} still pending review.")
            else:
                parts.append("All systems are now operational.")

            script = " ".join(parts)

        audio_b64 = await self._synthesize(script)
        return {"script": script, "audio_b64": audio_b64, "has_audio": audio_b64 is not None}

    async def _synthesize(self, text: str) -> Optional[str]:
        """Call ElevenLabs TTS API."""
        if not self.api_key:
            return None

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}",
                    headers={
                        "xi-api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "text": text,
                        "model_id": "eleven_flash_v2_5",
                        "voice_settings": {
                            "stability": 0.5,
                            "similarity_boost": 0.75,
                        },
                    },
                )
                if resp.status_code == 200:
                    return base64.b64encode(resp.content).decode()
                else:
                    print(f"[ElevenLabs] TTS failed: {resp.status_code} {resp.text[:100]}")
                    return None
        except Exception as e:
            print(f"[ElevenLabs] TTS error: {e}")
            return None


voice_alerts = VoiceAlerts()
