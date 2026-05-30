# Luminary

**A voice-first deep-research agent.** Talk to one of four ElevenLabs voice
agents about anything — markets, companies, science, history — and Luminary
runs a multi-phase research pipeline behind the scenes: query analysis,
study planning, iterative source-grounded research, claim validation, QA
anticipation, and synthesis. The agent reads the result back to you, or
turns it into a two-host podcast.

Built on Google ADK + Gemini, multi-provider routing (OpenAI gpt-5.5, Grok),
ElevenLabs Conversational + TTS, and an Observable Framework dashboard.
Runs on Cloud Run.

## What it does

Trigger it by saying something to one of the voice agents — Maya, Barnaby,
Consultant, or Rutger. Luminary picks a depth automatically:

| Depth | Trigger | Pipeline | Time budget |
|---|---|---|---|
| **Quick** | "quick look at X", "brief on X" | Single researcher, no follow-ups | 3 min |
| **Standard** | (default) | Sub-question fan-out → parallel research → follow-ups → synthesis | 10 min |
| **Deep** | "deep dive on X", "comprehensive analysis of X" | Multi-study iterative pipeline: query analysis → study planning → iterative research → claim validation → QA anticipation → strategic analysis → master synthesis | up to 60 min |

Each run is a real, source-grounded investigation — not a single LLM call.
Cross-study claim validation catches contradictions across sources before
they reach you. QA anticipation pre-answers the follow-up questions you're
likely to ask.

## Architecture

```
ElevenLabs voice agent  ──▶  webhook /webhook/elevenlabs (HMAC-verified)
                                        │
                                        ▼
                          ┌──────────────────────────┐
                          │  research_orchestrator   │
                          │  ─ depth detection       │
                          │  ─ plan/confirm gate     │
                          │  ─ memory + KG injection │
                          └──────────┬───────────────┘
                                     ▼
              ┌───────────────────────────────────────────────┐
              │                deep_pipeline                  │
              │                                               │
              │   query_analyzer ─▶ study_planner ─▶ iterative│
              │           ▼                                   │
              │   parallel(researcher × N studies)            │
              │           ▼                                   │
              │   synthesis_evaluator ─▶ gap_analyzer (loop)  │
              │           ▼                                   │
              │   claim_validator ─▶ qa_anticipator           │
              │           ▼                                   │
              │   strategic_analyst ─▶ master synthesis       │
              └───────────────────────┬───────────────────────┘
                                      ▼
                       GCS results · memory · knowledge graph
                                      ▼
                       agent KB attach  →  next voice turn
                       podcast_generator (optional, 2-host)
                       Observable dashboard (`/explore`)
```

### Model routing

Every pipeline phase is routed to the right provider. Defaults:

| Phase | Default model |
|---|---|
| Query analysis | Gemini 3.5 Flash |
| Study planning | Gemini 3.5 Flash |
| Study research | Gemini 3.5 Flash (with `google_search` grounding) |
| Complex study research | Gemini Deep Research (autonomous agent) |
| Study synthesis | OpenAI gpt-5.5 → Gemini Pro → Flash (fallback chain) |
| Master synthesis | OpenAI gpt-5.5 → Gemini Pro → Flash |
| Claim validation | OpenAI gpt-5.5 (contradiction detection) |
| Strategic analysis | Gemini 3.1 Pro |
| Verification | Gemini 3.5 Flash (with `web_search` tool) |

All overridable via env vars (`GEMINI_MODEL`, `GEMINI_PRO_MODEL`,
`OPENAI_REASONING_MODEL`).

The new outline-first + citation-audit pipeline is gated behind `LUMINARY_V2_PIPELINE=1`
(default off). When the flag is set, master synthesis walks a generated outline,
citations use deduped `[N]` markers from a shared SourceRegistry, and a
post-synthesis citation verifier flags + patches unsupported claims.

## Repo layout

```
app/
  agents/         24 ADK-built agents — query_analyzer, study_planner,
                  iterative_researcher, claim_validator, qa_anticipator,
                  strategic_analyst, synthesis_evaluator, podcast_generator,
                  watch_checker, memory_extractor, …
  routes/         Flask blueprints — health, webhook (ElevenLabs HMAC),
                  ui_api, explore (serves the dashboard).
  services/       model_router, research_orchestrator, GCS client,
                  ElevenLabs client, OpenAI / Grok clients, memory_store,
                  knowledge_graph, watch_store, notification_client,
                  podcast_service, research_index, active_prep, briefing.
  static/         Front-end assets — js/app.js (the SPA logic), css/app.css,
                  icon.svg + manifest.json (installable PWA).
  templates/      index.html — markup + Tailwind config only (the JS/CSS
                  were split out into static/).
  models/         Typed dataclasses — depth, webhook payload,
                  research result, study result, QA clusters.
explore/          Observable Framework dashboard built into the Docker
                  image at /explore. Visualizes research jobs, costs,
                  pipeline traces, knowledge graph.
tests/            Pytest suites for orchestrator, model router, agents,
                  webhook signature verification.
Dockerfile        Multi-stage build: Node 20 (explore build) →
                  Python 3.11 (Flask + Gunicorn).
```

## Running locally

```bash
# Python side
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in real values
gunicorn 'app.main:create_app()' --bind 0.0.0.0:8080 --threads 8

# Dashboard side (separate terminal)
cd explore
npm ci
npm run dev  # observable preview on :3000
```

Local mode reads all secrets from `.env`. Any other `ENVIRONMENT` value
pulls secrets from Google Secret Manager (see `app/config.py`).

## Required environment

Minimum to boot:

- `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`
- `GOOGLE_CLOUD_PROJECT`, `GOOGLE_API_KEY`
- `GCS_RESULTS_BUCKET`

See [`.env.example`](.env.example) for the full surface (including
`ELEVENLABS_WEBHOOK_SECRET` — **required** in non-local environments,
HMAC-verified on every inbound webhook).

Optional providers expand capability:

- `OPENAI_API_KEY` → enables gpt-5.5 synthesis path
- `GROK_API_KEY` → enables Grok for specific phases
- `NEWSAPI_KEY`, `ALPHA_VANTAGE_API_KEY`, `CRUNCHBASE_API_KEY` → enables
  the corresponding domain-specific data clients
- `SENDGRID_API_KEY` → enables watch-store email notifications

## Notable design choices

- **Plan/confirm gate before deep runs.** Deep mode (60-min budget) builds
  a study plan first, surfaces it via the voice agent for explicit
  confirmation, and only then executes. `AUTO_PROCEED_*` env vars tune
  this per depth.
- **Cancellation is async-safe.** A user-initiated cancel raises a
  module-level `ResearchCancelled` that's re-raised in every task handler;
  no orphaned threads, no zombie LLM calls.
- **Checkpoints to GCS.** Long deep runs persist intermediate state, so
  crashes resume instead of restarting.
- **Memory + knowledge graph.** Past research findings get re-injected
  into related queries; the knowledge graph tracks entities across studies.
- **Relevance-scoped agent context.** Each completed job is uploaded as a
  single consolidated briefing (not 6–10 fragments) and bounded by
  `MAX_AGENT_KB_DOCS` (evicted *after* attach). A persistent "Research
  Library Index" gives the agents breadth-awareness, and at call start the
  selected research's executive summary is injected as the
  `current_research` / `research_title` dynamic variables — so a call is
  scoped to one topic instead of every topic ever researched. *(Requires
  the agent prompts to reference those variables.)*
- **In-car, meeting-prep UX.** The home has a **Talk / Research** split:
  Talk (default) shows the active prep + four big one-tap agent buttons
  (tap → pick research → scoped call); Research holds the query/depth
  creation UI. Built for a phone in a car mount — big targets, high
  contrast, non-blocking toasts/confirms, call reconnect on cellular
  drops, mic pre-flight, dark mode, and an installable full-screen PWA.
- **Podcast generation.** A 2-host podcast (Maya + Barnaby) can be
  produced from any synthesis via ElevenLabs TTS.

## Deploy

The Dockerfile is multi-stage and Cloud Run-ready:

```bash
gcloud builds submit --tag gcr.io/$PROJECT/luminary
gcloud run deploy luminary --image gcr.io/$PROJECT/luminary \
  --region europe-west4 --platform managed --port 8080 \
  --memory 2Gi --cpu 2 --timeout 3600 --concurrency 8
```

Webhook endpoint: `https://<service>/webhook/elevenlabs`. Point your
ElevenLabs agent's post-call webhook at it.
