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
        self.last_audio_b64: Optional[str] = None

    async def generate_alert(self, incident_title: str, severity: str,
                              root_cause: str = "", proposed_fix: str = "") -> dict:
        """Generate a voice alert for an incident."""
        # Build the alert script
        if severity == "critical":
            script = f"Critical alert. {incident_title}. "
        elif severity == "high":
            script = f"High priority incident. {incident_title}. "
        else:
            script = f"New incident detected. {incident_title}. "

        if root_cause:
            script += f"Root cause: {root_cause}. "

        if proposed_fix:
            script += f"Proposed fix: {proposed_fix}. Awaiting your approval."
        else:
            script += "Investigation in progress."

        # Generate audio
        audio_b64 = await self._synthesize(script)

        return {
            "script": script,
            "audio_b64": audio_b64,
            "has_audio": audio_b64 is not None,
        }

    async def _synthesize(self, text: str) -> Optional[str]:
        """Call ElevenLabs TTS API."""
        if not self.api_key:
            return None

        try:
            async with httpx.AsyncClient(timeout=15) as client:
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
                            "stability": 0.6,
                            "similarity_boost": 0.8,
                        },
                    },
                )
                if resp.status_code == 200:
                    audio_b64 = base64.b64encode(resp.content).decode()
                    self.last_audio_b64 = audio_b64
                    return audio_b64
                return None
        except Exception:
            return None

    async def generate_summary(self, incidents_resolved: int, auto_resolved: int,
                                 avg_time: float) -> dict:
        """Generate a voice summary of agent performance."""
        script = (
            f"AgentOps status report. "
            f"{incidents_resolved} incidents resolved in this session. "
            f"{auto_resolved} were auto-resolved by the agent. "
            f"Average resolution time: {avg_time:.0f} seconds. "
            f"All systems operational."
        )
        audio_b64 = await self._synthesize(script)
        return {"script": script, "audio_b64": audio_b64, "has_audio": audio_b64 is not None}


voice_alerts = VoiceAlerts()
