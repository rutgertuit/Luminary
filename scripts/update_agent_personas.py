"""Reduce agent repetitiveness: topic-aware first messages + anti-repetition rule.

For each of the 4 ElevenLabs agents:
  1. Back up the current first_message + prompt to a local JSON file.
  2. Replace the static catchphrase greeting with a short, topic-aware opener
     using the {{research_title}} dynamic variable (varies per selected research).
  3. Append a "Variety & freshness" rule to the system prompt (idempotent).
  4. Set default placeholders for the injected dynamic variables.

PATCHes only the changed fields (deep-merge), mirroring elevenlabs_client's
attach flow, so other config (voice, llm, knowledge_base, tools) is preserved.

Usage:  PYTHONPATH=. python scripts/update_agent_personas.py
        DRY=1 PYTHONPATH=. python scripts/update_agent_personas.py   # preview only
"""
import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()

BASE = "https://api.elevenlabs.io/v1/convai/agents"
KEY = os.getenv("ELEVENLABS_API_KEY", "")
DRY = os.getenv("DRY", "") == "1"

AGENTS = {
    "maya": os.getenv("ELEVENLABS_AGENT_ID_MAYA", ""),
    "barnaby": os.getenv("ELEVENLABS_AGENT_ID_BARNABY", ""),
    "consultant": os.getenv("ELEVENLABS_AGENT_ID_CONSULTANT", ""),
    "rutger": os.getenv("ELEVENLABS_AGENT_ID_RUTGER", ""),
}

FIRST_MESSAGES = {
    "maya": "Maya here. {{research_title}} — I've been through the whole thing. Where do you want to start?",
    "barnaby": "Professor Barnaby, reporting in! {{research_title}} — and honestly, there's some fascinating stuff in here. What should we dig into first?",
    "consultant": "Consultant 4.0, Senior Partner track. I've completed my review of {{research_title}}. Where would you like to begin?",
    "rutger": "Hey, Rutger here. So — {{research_title}}. A few things really stood out to me. What's on your mind?",
}

VARIETY_MARKER = "# Variety & freshness"
VARIETY_RULE = (
    "\n\n" + VARIETY_MARKER + "\n"
    "- Do not reuse a fixed catchphrase or the same opening line every conversation. "
    "Vary your wording, sentence structure, and signature phrases each time.\n"
    "- Open by engaging directly with the specific topic ({{research_title}}) and the "
    "user's actual question — never a scripted intro you repeat verbatim.\n"
    "- Across the conversation, avoid recycling the same stock phrases; keep your "
    "responses fresh while staying fully in character."
)

VAR_DEFAULTS = {
    "research_title": "your latest research",
    "current_research": "",
    "research_index": "",
}


def headers():
    return {"xi-api-key": KEY, "Content-Type": "application/json"}


def main():
    backup = {}
    for slug, aid in AGENTS.items():
        if not aid:
            print(f"{slug}: no agent id, skipping")
            continue

        r = requests.get(f"{BASE}/{aid}", headers={"xi-api-key": KEY}, timeout=30)
        r.raise_for_status()
        agent = r.json().get("conversation_config", {}).get("agent", {})
        cur_first = agent.get("first_message", "")
        cur_prompt = agent.get("prompt", {}).get("prompt", "")
        backup[slug] = {"agent_id": aid, "first_message": cur_first, "prompt": cur_prompt}

        new_first = FIRST_MESSAGES[slug]
        new_prompt = cur_prompt if VARIETY_MARKER in cur_prompt else (cur_prompt + VARIETY_RULE)

        existing_ph = agent.get("dynamic_variables", {}).get("dynamic_variable_placeholders", {}) or {}
        merged_ph = {**VAR_DEFAULTS, **existing_ph}  # don't override anything already set

        patch = {
            "conversation_config": {
                "agent": {
                    "first_message": new_first,
                    "prompt": {"prompt": new_prompt},
                    "dynamic_variables": {"dynamic_variable_placeholders": merged_ph},
                }
            }
        }

        print(f"\n==== {slug} ====")
        print("  OLD first:", repr(cur_first)[:120])
        print("  NEW first:", repr(new_first)[:120])
        print("  prompt rule:", "already present" if VARIETY_MARKER in cur_prompt else "appending")

        if DRY:
            print("  [DRY] not patching")
            continue

        pr = requests.patch(f"{BASE}/{aid}", headers=headers(), json=patch, timeout=30)
        if not pr.ok:
            print(f"  PATCH FAILED {pr.status_code}: {pr.text[:300]}")
        else:
            print("  PATCH ok")

    # Save backup for easy revert
    with open("agent_persona_backup.json", "w", encoding="utf-8") as f:
        json.dump(backup, f, indent=2, ensure_ascii=False)
    print("\nBackup of original first_message + prompt saved to agent_persona_backup.json")


if __name__ == "__main__":
    main()
