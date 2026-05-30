import os
import logging
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)


def _get_secret(project_id: str, secret_name: str) -> str:
    """Fetch a secret from Google Cloud Secret Manager."""
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


@dataclass
class Settings:
    environment: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_webhook_secret: str = ""
    elevenlabs_agent_id_maya: str = ""
    elevenlabs_agent_id_barnaby: str = ""
    elevenlabs_agent_id_consultant: str = ""
    elevenlabs_agent_id_rutger: str = ""
    elevenlabs_agent_id: str = ""  # backward-compat: set to maya's ID in __post_init__
    google_cloud_project: str = ""
    google_api_key: str = ""
    deep_max_studies: int = 6
    deep_max_rounds: int = 3
    deep_max_concurrent_studies: int = 3
    gcs_results_bucket: str = ""
    openai_api_key: str = ""
    grok_api_key: str = ""
    newsapi_key: str = ""
    alpha_vantage_api_key: str = ""
    crunchbase_api_key: str = ""
    podcast_voice_id_maya: str = ""
    podcast_voice_id_barnaby: str = ""
    podcast_voice_id_consultant: str = ""
    podcast_voice_id_rutger: str = ""

    # Research plan confirmation settings
    auto_proceed_quick: bool = True       # Skip confirmation for QUICK depth
    auto_proceed_standard: bool = False   # Require confirmation for STANDARD
    auto_proceed_max_duration: int = 120  # Auto-proceed only if est. < N seconds
    require_confirmation_deep: bool = True  # Always confirm DEEP

    # KB document limit per agent (oldest research docs are evicted when exceeded)
    max_agent_kb_docs: int = 3

    # Scope guardrails
    research_time_budget_quick: int = 180      # Max seconds for QUICK research
    research_time_budget_standard: int = 600   # Max seconds for STANDARD research
    research_time_budget_deep: int = 3600      # Max seconds for DEEP research

    def __post_init__(self):
        self.environment = os.getenv("ENVIRONMENT", "local")
        self.google_cloud_project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
        self.deep_max_studies = int(os.getenv("DEEP_MAX_STUDIES", "6"))
        self.deep_max_rounds = int(os.getenv("DEEP_MAX_ROUNDS", "3"))
        self.deep_max_concurrent_studies = int(os.getenv("DEEP_MAX_CONCURRENT_STUDIES", "3"))
        self.auto_proceed_quick = os.getenv("AUTO_PROCEED_QUICK", "true").lower() == "true"
        self.auto_proceed_standard = os.getenv("AUTO_PROCEED_STANDARD", "false").lower() == "true"
        self.auto_proceed_max_duration = int(os.getenv("AUTO_PROCEED_MAX_DURATION", "120"))
        self.require_confirmation_deep = os.getenv("REQUIRE_CONFIRMATION_DEEP", "true").lower() == "true"
        self.max_agent_kb_docs = int(os.getenv("MAX_AGENT_KB_DOCS", "3"))
        self.research_time_budget_quick = int(os.getenv("RESEARCH_TIME_BUDGET_QUICK", "180"))
        self.research_time_budget_standard = int(os.getenv("RESEARCH_TIME_BUDGET_STANDARD", "600"))
        self.research_time_budget_deep = int(os.getenv("RESEARCH_TIME_BUDGET_DEEP", "3600"))
        self.google_api_key = os.getenv("GOOGLE_API_KEY", "")
        self.gcs_results_bucket = os.getenv("GCS_RESULTS_BUCKET", "")

        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.grok_api_key = os.getenv("GROK_API_KEY", "")
        self.newsapi_key = os.getenv("NEWSAPI_KEY", "")
        self.alpha_vantage_api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
        self.crunchbase_api_key = os.getenv("CRUNCHBASE_API_KEY", "")

        self.podcast_voice_id_maya = os.getenv("PODCAST_VOICE_ID_MAYA", "")
        self.podcast_voice_id_barnaby = os.getenv("PODCAST_VOICE_ID_BARNABY", "")
        self.podcast_voice_id_consultant = os.getenv("PODCAST_VOICE_ID_CONSULTANT", "")
        self.podcast_voice_id_rutger = os.getenv("PODCAST_VOICE_ID_RUTGER", "")

        if self.environment == "local":
            self.elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY", "")
            self.elevenlabs_webhook_secret = os.getenv("ELEVENLABS_WEBHOOK_SECRET", "")
            self.elevenlabs_agent_id_maya = os.getenv("ELEVENLABS_AGENT_ID_MAYA", "")
            self.elevenlabs_agent_id_barnaby = os.getenv("ELEVENLABS_AGENT_ID_BARNABY", "")
            self.elevenlabs_agent_id_consultant = os.getenv("ELEVENLABS_AGENT_ID_CONSULTANT", "")
            self.elevenlabs_agent_id_rutger = os.getenv("ELEVENLABS_AGENT_ID_RUTGER", "")
            # Backward compat: fall back to old single env var, then maya
            self.elevenlabs_agent_id = (
                os.getenv("ELEVENLABS_AGENT_ID", "")
                or self.elevenlabs_agent_id_maya
            )
        else:
            project = self.google_cloud_project
            if not project:
                raise ValueError("GOOGLE_CLOUD_PROJECT must be set in production")
            try:
                self.elevenlabs_api_key = _get_secret(project, "elevenlabs-api-key")
                self.elevenlabs_agent_id_maya = _get_secret(project, "elevenlabs-agent-id-maya")
                self.elevenlabs_agent_id_barnaby = _get_secret(project, "elevenlabs-agent-id-barnaby")
                self.elevenlabs_agent_id_consultant = _get_secret(project, "elevenlabs-agent-id-consultant")
                try:
                    self.elevenlabs_agent_id_rutger = _get_secret(project, "elevenlabs-agent-id-rutger")
                except Exception:
                    logger.warning("No agent ID secret for rutger (optional)")
                self.elevenlabs_agent_id = self.elevenlabs_agent_id_maya
            except Exception:
                logger.exception("Failed to load secrets from Secret Manager")
                raise
            try:
                secret = _get_secret(project, "elevenlabs-webhook-secret")
                if secret and secret != "placeholder":
                    self.elevenlabs_webhook_secret = secret
            except Exception:
                logger.warning("No webhook secret configured, signature verification disabled")
