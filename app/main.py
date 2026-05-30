import json
import logging
import os
import signal
import sys
import threading
import time

from flask import Flask

from app.config import Settings

_log = logging.getLogger(__name__)


def _patch_adk_telemetry() -> None:
    """Monkey-patch ADK telemetry to prevent bytes serialization crashes.

    ADK's trace_call_llm calls json.dumps on the LLM request, which crashes
    when tool results contain bytes (e.g., from fetched binary URLs). This
    wraps the function in a try/except so telemetry failures are silenced.
    Patches both the module attribute and the local binding in base_llm_flow.
    """
    try:
        from google.adk import telemetry  # type: ignore
    except ImportError:
        # ADK not installed — nothing to patch.
        return
    except Exception:  # pragma: no cover - defensive against broken installs
        _log.debug("Skipping ADK telemetry patch: unexpected import failure", exc_info=True)
        return

    _original = getattr(telemetry, "trace_call_llm", None)
    if _original is None:
        _log.debug("ADK telemetry has no trace_call_llm symbol; nothing to patch")
        return

    def _safe_trace_call_llm(*args, **kwargs):
        try:
            return _original(*args, **kwargs)
        except (TypeError, ValueError, json.JSONDecodeError):
            # The real-world failure mode is json.dumps choking on bytes;
            # still catch json.JSONDecodeError defensively.
            return None

    telemetry.trace_call_llm = _safe_trace_call_llm

    # Also patch the local binding in base_llm_flow (uses from-import).
    try:
        from google.adk.flows.llm_flows import base_llm_flow  # type: ignore

        base_llm_flow.trace_call_llm = _safe_trace_call_llm
    except ImportError:
        pass
    except AttributeError:
        _log.debug("base_llm_flow does not expose trace_call_llm; skipping inner patch")


_patch_adk_telemetry()


def create_app() -> Flask:
    """Flask application factory."""
    app = Flask(__name__)

    # Configure logging
    _setup_logging(app)

    # Load settings
    settings = Settings()
    app.config["SETTINGS"] = settings

    # Register blueprints
    from app.routes.health import health_bp
    from app.routes.webhook import webhook_bp
    from app.routes.ui_api import ui_api_bp
    from app.routes.explore import explore_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(webhook_bp)
    app.register_blueprint(ui_api_bp)
    app.register_blueprint(explore_bp)

    # Register SIGTERM handler for graceful shutdown
    _setup_sigterm_handler(app)

    app.logger.info("Luminary started (environment=%s)", settings.environment)
    return app


def _setup_sigterm_handler(app: Flask) -> None:
    """Register SIGTERM handler to checkpoint running DEEP jobs before shutdown.

    Cloud Run sends SIGTERM when recycling instances. We get ~10s to save state.
    This marks running DEEP jobs as interrupted in GCS metadata so the UI can
    offer a resume button instead of silently losing the job.

    Hardening notes:
      * Re-entry guard (``_sigterm_invoked``) prevents double-shutdown if a
        second SIGTERM arrives while we're still checkpointing.
      * A hard wall-clock deadline caps the handler at ~8s so we exit well
        before Cloud Run's 10s grace window elapses.
    """
    _sigterm_invoked = threading.Event()
    # Cloud Run gives ~10s after SIGTERM before SIGKILL; leave a little headroom.
    CHECKPOINT_DEADLINE_SECONDS = 8.0

    def _on_sigterm(signum, frame):
        if _sigterm_invoked.is_set():
            # Second signal — just get out of the way.
            return
        _sigterm_invoked.set()

        logger = logging.getLogger(__name__)
        logger.info("SIGTERM received — checkpointing running DEEP jobs")
        deadline = time.monotonic() + CHECKPOINT_DEADLINE_SECONDS

        try:
            from app.services.job_tracker import (
                get_running_deep_jobs,
                JobStatus,
                update_job,
            )
            from app.services import gcs_client

            settings = app.config.get("SETTINGS")
            bucket = settings.gcs_results_bucket if settings else ""
            deep_jobs = get_running_deep_jobs()

            for job in deep_jobs:
                if time.monotonic() >= deadline:
                    logger.warning(
                        "SIGTERM checkpoint deadline reached; skipping remaining jobs"
                    )
                    break
                try:
                    # Mark in-memory so any final poll returns "failed" instead of "running"
                    update_job(
                        job.job_id,
                        status=JobStatus.FAILED,
                        error="Server shutdown during research. Resume available.",
                    )
                    # Update GCS metadata so archive shows it as interrupted
                    if bucket:
                        gcs_client.update_metadata(
                            job.job_id,
                            bucket,
                            {
                                "status": "interrupted",
                                "error": "Server shutdown during research (SIGTERM). Resume available.",
                            },
                        )
                    logger.info("Marked job %s as interrupted", job.job_id)
                except Exception:
                    logger.exception("Failed to mark job %s as interrupted", job.job_id)
        except Exception:
            logging.getLogger(__name__).exception("SIGTERM handler error")
        finally:
            # Always exit, even if the checkpoint path errored. Using os._exit
            # in a finally here would skip gunicorn cleanup, so keep sys.exit.
            sys.exit(0)

    signal.signal(signal.SIGTERM, _on_sigterm)


def _setup_logging(app: Flask) -> None:
    """Configure structured logging for Cloud Run or standard logging locally."""
    environment = os.getenv("ENVIRONMENT", "local")

    if environment != "local":
        try:
            import google.cloud.logging

            client = google.cloud.logging.Client()
            client.setup_logging()
            app.logger.info("Cloud Logging configured")
        except Exception:
            logging.basicConfig(level=logging.INFO)
            app.logger.warning("Failed to set up Cloud Logging, using basic logging")
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
