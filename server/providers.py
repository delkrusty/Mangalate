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
from pathlib import Path
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
    "ollama": {
        "label": "Ollama no seu computador (grátis, sem internet, exige PC forte; erra mais, fica de reserva)",
        "base": "http://host.docker.internal:11434/v1",
        "model": "",
        "keys_url": "",
    },
    "openrouter": {
        "label": "OpenRouter (modelos :free, 50 páginas por dia sem créditos)",
        "base": "https://openrouter.ai/api/v1",
        "model": "",
        "keys_url": "https://openrouter.ai/keys",
    },
    "groq-2": {
        "label": "Groq, segundo modelo (GPT-OSS 20B, mesma chave do Groq, cota separada)",
        "base": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-20b",
        "keys_url": "https://console.groq.com/keys",
    },
}
# Models a provider retired, with the replacement used for keys saved before (Groq dropped
# llama-3.3-70b-versatile in 2026: "modelo recusado" every page).
RETIRED = {"llama-3.3-70b-versatile": "openai/gpt-oss-20b"}
RENAMED = {"groq-llama": "groq-2"}
# Presets that never translated a page (16/10/2026 test, one call each): the free Mistral plan
# answers 429 with a limit of 0 requests for mistral-small and mistral-medium, and GitHub Models
# answered a plain "OK" instead of a chat reply.  Keys saved for them are skipped.
REMOVED = {"mistral", "github"}
# Weaker: used only while the others are at their limit, never in the turns.  Ollama's
# gpt-oss:20b reversed 2 of 35 lines and got 3 genders wrong on pages Groq got right.
RESERVES = {"groq-2", "ollama"}
LOCAL_HOSTS = {"host.docker.internal", "localhost", "127.0.0.1"}
SHORT_REST = 60
LONG_REST = 3600
# A main provider back within this many seconds is waited for instead of handing the page to a
# reserve (ouro-8: gpt-oss-20b got 7 of 11 pages during per-minute limits and translated
# "PERSONALLY I THINK" as "Pessoal, acho").  Longer pauses (daily quotas) still use the reserve.
RESERVE_WAIT = 90
AI_TIMEOUT = 45     # seconds before a silent provider is left for the next one
# A model on this computer loads into memory on its first page and may run partly on the CPU:
# gpt-oss:20b took 51 s cold on a 16 GB PC with an 8 GB card, so every page hit AI_TIMEOUT.
# A page asks up to three times (answer and second tries), so a stuck model holds it 6 min at most.
LOCAL_TIMEOUT = 120


def timeout_for(provider):
    local = urlparse(str(provider.get("base", ""))).hostname in LOCAL_HOSTS
    return LOCAL_TIMEOUT if local else AI_TIMEOUT


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
        if name in REMOVED:
            continue
        key = str(item.get("key", "")).strip()
        if not name or not model or not validate_base(base):
            raise ValueError("Provedor incompleto: confira nome, endereço e modelo.")
        if not key and urlparse(base).hostname not in LOCAL_HOSTS:
            raise ValueError(f"Provedor {name} sem chave.")
        name, model = RENAMED.get(name, name), RETIRED.get(model, model)
        cleaned.append({"name": name, "base": base, "model": model, "key": key or "ollama"})
    if not cleaned:
        raise ValueError("Nenhuma IA em uso na lista; rode py setup.py e escolha outra.")
    return cleaned


def short_reasoning(base, model):
    """Groq's GPT-OSS thinks before answering and the thinking counts against the free
    8,000 tokens per minute; a short think keeps several pages per minute.  On Ollama the
    full think took 21 s a page with gpt-oss:20b, the short one 9.5 s."""
    return "gpt-oss" in model and urlparse(str(base)).hostname in {"api.groq.com"} | LOCAL_HOSTS


def dump_secret(providers):
    return json.dumps({"providers": providers}, ensure_ascii=False)


class AllProvidersResting(RuntimeError):
    """Every configured provider is at its limit or misconfigured."""

    def __init__(self, seconds):
        super().__init__(f"Todos os provedores estão no limite; tente em {max(1, round(seconds / 60))} min.")
        self.seconds = seconds


class UnusableAnswer(ValueError):
    """No provider produced a usable translation for this page (content, not health)."""


class NotAnAnswer(RuntimeError):
    """The address answered, but not like a chat API (a plain "OK" instead of JSON)."""
    status_code = 404


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
    def __init__(self, providers, clock=time.monotonic, log=print, take_turns=None, sleep=None):
        self.providers = list(providers)
        self.sleep = sleep
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
            # Where it broke (file:line), never the message: it may carry the provider's body.
            import traceback
            frames = traceback.extract_tb(exc.__traceback__)
            where = f" em {Path(frames[-1].filename).name}:{frames[-1].lineno}" if frames else ""
            self.rest(name, SHORT_REST, type(exc).__name__ + where)

    def main_back_in(self):
        """Seconds until a resting main provider is back; None when none is resting."""
        now = self.clock()
        waits = [self.resting.get(p["name"], 0) - now for p in self.providers if p["name"] not in RESERVES]
        if not waits or any(w <= 0 for w in waits):
            return None
        return min(waits)

    async def run(self, attempt, waited=False):
        """Call attempt(provider) on each available provider until one succeeds."""
        self.events = []
        self.__dict__["raw"] = []
        ready = self.available()
        main = [p for p in ready if p["name"] not in RESERVES] or ready
        spare = [p for p in ready if p not in main]
        if self.take_turns and main:
            # Each page starts with the next provider; the others stay as fallbacks.
            start = self.turn % len(main)
            self.turn += 1
            main = main[start:] + main[:start]
        ready = main + spare
        for provider in ready:
            if provider["name"] in RESERVES and not waited:
                back = self.main_back_in()
                if back is not None and back <= RESERVE_WAIT \
                        and not any(kind.startswith("content") for _, kind in self.events):
                    self.log(f"BYOK: esperando {round(back)} s pela IA principal em vez da reserva.")
                    import asyncio
                    await (self.sleep or asyncio.sleep)(back)
                    return await self.run(attempt, waited=True)
            try:
                result = await attempt(provider)
            except Exception as exc:  # provider bodies are never logged
                self.failed(provider, exc)
                continue
            self.strikes[provider["name"]] = 0
            self.log(f"BYOK: página traduzida por {provider['name']}")
            return result
        # If any provider that is still available answered (badly), the problem is this
        # page, not the providers' limits: never make the caller wait for a pause.
        if any(kind.startswith("content") for _, kind in self.events):
            raise UnusableAnswer("Nenhuma IA devolveu uma tradução válida para esta página.")
        now = self.clock()
        wait = min((t - now for t in self.resting.values() if t > now), default=SHORT_REST)
        raise AllProvidersResting(wait)
