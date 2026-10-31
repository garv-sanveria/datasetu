"""
ai_assist.py — Optional local open-model AI helper (stretch feature, off by default).

What it does:
    When datasetu serve is invoked with --ai, this module connects to a LOCAL
    Ollama instance (e.g. Gemma 3 4B) to:
      (a) Suggest LGD matches for unmatched district strings — recorded as
          method="ai_suggested", flagged for human review. NEVER silently applied
          to canonical LGD codes; the suggestion is advisory only.
      (b) Handle POST /v1/ask: natural-language question → validated filter params,
          verified against the column schema before use. No raw SQL ever passed.

    If Ollama is unavailable (not installed, not running, wrong model), this module
    degrades silently and returns None / empty suggestions. The core pipeline
    remains 100% deterministic with --ai off.

Why local model (not cloud):
    R8 (fully offline) and R5 (no secrets). A local Ollama model requires no
    API key, runs on the demo laptop, and satisfies the MLH Best Open-Source AI
    Project requirement without breaking the offline constraint.

How it connects to the rest:
    - cli.py checks --ai and imports this module only then.
    - router.py adds the POST /v1/ask route only when ai_enabled=True.
    - The suggestions from suggest_lgd_matches() are logged in the Rich console
      and available in the report as ai_suggestions (never as canonical codes).

Credits:
    Ollama: https://ollama.ai (MIT licence)
    Model: Gemma 3 (google/gemma-3-4b) — see THIRD_PARTY.md for licence details.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

OLLAMA_DEFAULT_URL = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "gemma3:4b"


class AIAssist:
    """
    Thin wrapper around the Ollama /api/generate endpoint.

    Instantiated by cli.py when --ai is passed. If Ollama is unreachable,
    all methods return empty/None results silently.
    """

    def __init__(
        self,
        base_url: str = OLLAMA_DEFAULT_URL,
        model: str = OLLAMA_DEFAULT_MODEL,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._available = self._check_available()

    def _check_available(self) -> bool:
        """Ping Ollama; returns False if not reachable (silent degradation)."""
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    @property
    def available(self) -> bool:
        return self._available

    def suggest_lgd_matches(
        self,
        unmatched: list[str],
        gazetteer_sample: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Ask the local model to suggest the most likely LGD district for each
        unmatched string.

        Returns a list of suggestions, each with:
          {raw: str, suggested_canonical: str, suggested_state: str,
           reasoning: str, flagged_for_review: True}

        These are ADVISORY ONLY and must NOT be written to canonical LGD codes
        without human verification.
        """
        if not self._available or not unmatched:
            return []

        suggestions = []
        # Build a compact gazetteer reference (first 20 entries to fit context)
        sample_text = "\n".join(
            f"  {e['district_name']} ({e['state_name']})" for e in gazetteer_sample[:20]
        )

        for raw_name in unmatched:
            prompt = (
                f"You are an Indian administrative geography expert.\n"
                f"The following district name appears in a government dataset: \"{raw_name}\"\n"
                f"Here is a sample of known LGD district names:\n{sample_text}\n\n"
                f"Which LGD district is most likely intended? Respond ONLY with valid JSON:\n"
                f'{{ "suggested_canonical": "<name>", "suggested_state": "<state>", "reasoning": "<1 sentence>" }}\n'
                f"If you are not confident, set suggested_canonical to null."
            )
            try:
                result = self._generate(prompt)
                parsed = json.loads(result)
                suggestions.append(
                    {
                        "raw": raw_name,
                        "suggested_canonical": parsed.get("suggested_canonical"),
                        "suggested_state": parsed.get("suggested_state"),
                        "reasoning": parsed.get("reasoning", ""),
                        "flagged_for_review": True,
                        "method": "ai_suggested",
                    }
                )
            except Exception:
                suggestions.append(
                    {
                        "raw": raw_name,
                        "suggested_canonical": None,
                        "suggested_state": None,
                        "reasoning": "AI suggestion failed",
                        "flagged_for_review": True,
                        "method": "ai_suggested",
                    }
                )

        return suggestions

    def natural_language_to_filters(
        self,
        question: str,
        schema: dict[str, str],
    ) -> dict[str, Any] | None:
        """
        Convert a natural-language question to validated filter params.

        Returns a dict of filter params validated against *schema*, or None
        if the model cannot produce a valid response. NEVER returns raw SQL.
        """
        if not self._available:
            return None

        cols_desc = "\n".join(f"  {col} ({typ})" for col, typ in schema.items())
        prompt = (
            f"You are a query assistant for a dataset with these columns:\n{cols_desc}\n\n"
            f"User question: \"{question}\"\n\n"
            f"Respond ONLY with valid JSON filters for the DataSetu API. Example:\n"
            f'{{ "State": "Karnataka", "Scheme__gte": 1000 }}\n'
            f"Only use column names from the list above. Set value to null to skip."
        )
        try:
            result = self._generate(prompt)
            parsed = json.loads(result)
            # Validate: only known columns, no raw SQL
            valid = {k: v for k, v in parsed.items() if k.split("__")[0] in schema and v is not None}
            return valid
        except Exception:
            return None

    def _generate(self, prompt: str, max_tokens: int = 256) -> str:
        """Call Ollama /api/generate and return the response text."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.1},
        }
        resp = httpx.post(f"{self.base_url}/api/generate", json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json().get("response", "")
