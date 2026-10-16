"""BYOK providers: ready-made presets and automatic rotation between them.

The provider secret (secrets/provider_key.txt, mounted at
/run/secrets/provider_key) holds either a plain API key, for a single provider
configured through CUSTOM_OPENAI_API_BASE/CUSTOM_OPENAI_MODEL, or a JSON list
written by setup.py:

    {"providers": [{"name": "groq", "base": "...", "model": "...", "key": "..."}, ...]}

With several providers, pages take turns among the ones not resting (page 1 to
the first, page 2 to the second...), so each free quota lasts longer; set
MANGALATE_ROTATION=ordem to always start with the first.  A
provider that answers "limit reached" rests for the time it asks (or a minute);
after three limits in a row it rests for an hour, which covers daily quotas.
Wrong key or model rests it for an hour too, so reading continues on the next
provider.  Keys never leave the server and are never logged.
"""
import json
import os
import time
from urllib.parse import urlparse

PRESETS = {
    "groq": {
        "label": "Groq (grátis, mais rápido)",
        "base": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
        "keys_url": "https://console.groq.com/keys",
    },
    "gemini": {
        "label": "Google Gemini (grátis, mais coloquial)",
        "base": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-flash-lite-latest",
        "keys_url": "https://aistudio.google.com/apikey",
    },
    "openrouter": {
        "label": "OpenRouter (modelos :free, 50 páginas por dia sem créditos)",
        "base": "https://openrouter.ai/api/v1",
        "model": "",
        "keys_url": "https://openrouter.ai/keys",
    },
    "ollama": {
        "label": "Ollama no seu computador (grátis, sem internet, exige PC forte)",
        "base": "http://host.docker.internal:11434/v1",
        "model": "",
        "keys_url": "",
    },
    "mistral": {
        "label": "Mistral (grátis no plano Experiment, cota mensal grande)",
        "base": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
        "keys_url": "https://console.mistral.ai/api-keys",
    },
    "groq-llama": {
        "label": "Groq, segundo modelo (mesma chave do Groq, cota separada)",
        "base": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "keys_url": "https://console.groq.com/keys",
    },
    "github": {
        "label": "GitHub Models (grátis com conta do GitHub, reserva)",
        "base": "https://models.github.ai/inference",
        "model": "openai/gpt-4.1-mini",
        "keys_url": "https://github.com/settings/personal-access-tokens/new (permissão Models: leitura)",
    },
}
LOCAL_HOSTS = {"host.docker.internal", "localhost", "127.0.0.1"}
SHORT_REST = 60
LONG_REST = 3600
AI_TIMEOUT = 45     # seconds before a silent provider is left for the next one


def validate_base(url):
    """HTTPS for remote providers; plain HTTP only for a model on this computer."""
    parsed = urlparse(url)
    if not parsed.netloc:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname in LOCAL_HOSTS


def parse_secret(text):
    """Return the provider list from the secret, or None for a plain single key."""
    text = (text or "").strip()
    if not text.startswith("{"):
        return None
    data = json.loads(text)
    providers = data.get("providers") if isinstance(data, dict) else None
    if not isinstance(providers, list) or not providers:
        raise ValueError("Lista de provedores vazia.")
    cleaned = []
    for item in providers:
        name, base, model = (str(item.get(k, "")).strip() for k in ("name", "base", "model"))
        key = str(item.get("key", "")).strip()
        if not name or not model or not validate_base(base):
            raise ValueError("Provedor incompleto: confira nome, endereço e modelo.")
        if not key and urlparse(base).hostname not in LOCAL_HOSTS:
            raise ValueError(f"Provedor {name} sem chave.")
        cleaned.append({"name": name, "base": base, "model": model, "key": key or "ollama"})
    return cleaned


def dump_secret(providers):
    return json.dumps({"providers": providers}, ensure_ascii=False)


class AllProvidersResting(RuntimeError):
    """Every configured provider is at its limit or misconfigured."""

    def __init__(self, seconds):
        super().__init__(f"Todos os provedores estão no limite; tente em {max(1, round(seconds / 60))} min.")
        self.seconds = seconds


class UnusableAnswer(ValueError):
    """No provider produced a usable translation for this page (content, not health)."""


def classify(exc):
    """'limit', 'config', 'content' (bad answer for this page) or 'retry'."""
    status = getattr(exc, "status_code", None)
    if status == 429:
        return "limit"
    # Google answers an invalid API key with 400, not 401.
    if status in (400, 401, 402, 403, 404):
        return "config"
    if isinstance(exc, ValueError):
        return "content"
    return "retry"


def retry_after(exc):
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    try:
        return max(1.0, float(headers.get("retry-after")))
    except (TypeError, ValueError):
        return None


class ProviderPool:
    def __init__(self, providers, clock=time.monotonic, log=print, take_turns=None):
        self.providers = list(providers)
        self.clock = clock
        self.log = log
        self.resting = {}
        self.strikes = {}
        self.turn = 0
        if take_turns is None:
            take_turns = os.environ.get("MANGALATE_ROTATION", "alternar").lower() != "ordem"
        self.take_turns = take_turns
        self.events = []  # (provider, reason) of the last page, for review reports

    def available(self):
        now = self.clock()
        return [p for p in self.providers if self.resting.get(p["name"], 0) <= now]

    def rest(self, name, seconds, reason):
        self.resting[name] = self.clock() + seconds
        self.log(f"BYOK: {name} em pausa por {round(seconds)} s ({reason}); usando o próximo provedor.")

    def failed(self, provider, exc):
        name, kind = provider["name"], classify(exc)
        self.events.append((name, kind if kind != "retry" else type(exc).__name__))
        if kind == "content":
            # A malformed answer says nothing about the provider's health: no pause.
            # Our own validation messages only (never the provider's body).
            reason = str(exc)[:120] if type(exc).__module__ in {"engine_compat", "providers", "builtins"} else ""
            self.events[-1] = (name, f"content: {reason}" if reason else "content")
            self.log(f"BYOK: {name} devolveu uma resposta inválida para esta página ({reason}); tentando o próximo.")
        elif kind == "limit":
            self.strikes[name] = self.strikes.get(name, 0) + 1
            seconds = LONG_REST if self.strikes[name] >= 3 else (retry_after(exc) or SHORT_REST)
            self.rest(name, seconds, "limite atingido")
        elif kind == "config":
            self.rest(name, LONG_REST, "chave, saldo ou modelo recusado — confira a chave rodando py setup.py")
        else:
            self.rest(name, SHORT_REST, type(exc).__name__)

    async def run(self, attempt):
        """Call attempt(provider) on each available provider until one succeeds."""
        self.events = []
        self.__dict__["raw"] = []
        ready = self.available()
        if self.take_turns and ready:
            # Each page starts with the next provider; the others stay as fallbacks.
            start = self.turn % len(ready)
            self.turn += 1
            ready = ready[start:] + ready[:start]
        for provider in ready:
            try:
                result = await attempt(provider)
            except Exception as exc:  # provider bodies are never logged
                self.failed(provider, exc)
                continue
            self.strikes[provider["name"]] = 0
            return result
        # If any provider that is still available answered (badly), the problem is this
        # page, not the providers' limits: never make the caller wait for a pause.
        if any(kind.startswith("content") for _, kind in self.events):
            raise UnusableAnswer("Nenhuma IA devolveu uma tradução válida para esta página.")
        now = self.clock()
        wait = min((t - now for t in self.resting.values() if t > now), default=SHORT_REST)
        raise AllProvidersResting(wait)
