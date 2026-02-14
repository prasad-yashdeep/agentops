"""Configuration from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
MONITORED_APP_PORT = int(os.getenv("MONITORED_APP_PORT", "8001"))

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# Blaxel Sandbox
BLAXEL_API_KEY = os.getenv("BLAXEL_API_KEY", "")
BLAXEL_API_URL = os.getenv("BLAXEL_API_URL", "https://api.blaxel.ai/v1")
BLAXEL_WORKSPACE = os.getenv("BLAXEL_WORKSPACE", os.getenv("BL_WORKSPACE", ""))
USE_LOCAL_SANDBOX = os.getenv("USE_LOCAL_SANDBOX", "true").lower() == "true"

# White Circle AI
WHITECIRCLE_API_KEY = os.getenv("WHITECIRCLE_API_KEY", "")
WHITECIRCLE_API_URL = os.getenv("WHITECIRCLE_API_URL", "https://api.whitecircle.ai/v1")

# ElevenLabs
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel

# Agent Config
MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", "5"))  # seconds
AUTO_FIX_THRESHOLD = float(os.getenv("AUTO_FIX_THRESHOLD", "0.85"))  # confidence threshold for auto-fix
ESCALATION_THRESHOLD = float(os.getenv("ESCALATION_THRESHOLD", "0.5"))  # below this = escalate immediately

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agentops.db")
