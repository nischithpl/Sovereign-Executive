"""
Thin wrapper around the local Ollama API.
Ollama must be running on the machine (`ollama serve` — usually starts
automatically after install) with a model already pulled
(`ollama pull llama3.2:1b`).

Nothing in this file ever leaves the machine — this is what makes the
whole project "sovereign" / offline.

Configuration (shared with ai_service.py — set once, used everywhere):
    OLLAMA_MODEL      model name, default "llama3.2:1b"
    OLLAMA_BASE_URL   Ollama server, default "http://localhost:11434"

Example:
    export OLLAMA_MODEL=llama3.2:1b
"""

import os

import requests

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_URL = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_TAGS_URL = f"{OLLAMA_BASE_URL}/api/tags"

# Single source of truth for the demo model. ai_service.py should read the
# same env var: MODEL_NAME = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")


class OllamaClient:
    def __init__(self, model: str = DEFAULT_MODEL, url: str = OLLAMA_URL):
        self.model = model
        self.url = url

    def is_available(self) -> bool:
        """
        Quick check (no generation) so callers can decide whether to use
        the real model or fall back to rule-based logic, without waiting
        for a slow timeout mid-demo.
        """
        try:
            requests.get(OLLAMA_TAGS_URL, timeout=3)
            return True
        except requests.exceptions.RequestException:
            return False

    def generate(self, prompt: str, temperature: float = 0.1) -> str:
        """
        Sends a prompt to the local model and returns the raw text response.
        temperature is kept low (0.1) because we want consistent, structured
        answers, not creative ones — this is the single biggest lever for
        reducing risk-level flip-flopping between runs.
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        try:
            response = requests.post(self.url, json=payload, timeout=60)
            response.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                f"Could not reach Ollama at {OLLAMA_BASE_URL}.\n"
                f"Fix: run `ollama serve` in a terminal, and make sure you've "
                f"pulled the model with `ollama pull {self.model}`."
            ) from e
        except requests.exceptions.Timeout as e:
            raise RuntimeError(
                "Ollama took too long to respond (>60s). "
                "Try a smaller model, e.g. `ollama pull llama3.2:1b`."
            ) from e

        return response.json()["response"]
