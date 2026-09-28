"""
Thin wrapper around the local Ollama API.
Ollama must be running on the machine (`ollama serve` — usually starts
automatically after install) with a model already pulled
(`ollama pull llama3.2`).

Nothing in this file ever leaves the machine — this is what makes the
whole project "sovereign" / offline.
"""

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
DEFAULT_MODEL = "llama3.2"


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
                "Could not reach Ollama at http://localhost:11434.\n"
                "Fix: run `ollama serve` in a terminal, and make sure you've "
                "pulled a model with `ollama pull llama3.2`."
            ) from e
        except requests.exceptions.Timeout as e:
            raise RuntimeError(
                "Ollama took too long to respond (>60s). "
                "Try a smaller model, e.g. `ollama pull phi3`."
            ) from e

        return response.json()["response"]
