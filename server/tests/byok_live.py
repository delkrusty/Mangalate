"""Live BYOK check against free provider tiers, run only by byok-live.yml.

Uses the real engine translator, the scan prompt and the Mangalate response
validation. Keys come from the environment (GitHub secrets) and are never
printed; provider error bodies are reduced to their exception type. The dialogue
is synthetic. Results are emitted as workflow notices so they can be read
without the full log.
"""
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LINES = [
    "UNDERSTOOD, KAISER.",
    "Haru, about what you told the Kaiser this morning...",
    "This morning? What are you talking about?",
    "We lost last time because of their wizards, right?",
    "He's been acting weird ever since the cat ran away.",
    "I need you as my partner...",
    "...at the ball tomorrow night.",
    "NO WAY! ABSOLUTELY NOT!",
    "IN YOVEMBER?! IF I COULD JUST AC7 LIKE NORMAL...",
]
PROVIDERS = [
    ("Groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1",
     ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "llama-3.3-70b-versatile"]),
    ("Gemini", "GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/",
     ["gemini-flash-lite-latest", "gemini-flash-latest"]),
]
# European Portuguese forms that should not appear in PT-BR dialogue.
EUROPEAN = re.compile(r"\b(estás|tens|és|vós|preciso de ti|contigo|a fazer|a falar|deves)\b", re.I)


def notice(title, lines):
    body = "%0A".join(str(x).replace("%", "%25").replace("\n", " ") for x in lines)
    safe_title = str(title).replace("%", "%25").replace(":", "%3A").replace(",", "%2C")
    print(f"::notice title={safe_title}::{body}", flush=True)


def checks(output):
    found = []
    if len(output) != len(LINES):
        found.append("quantidade de falas diferente")
    for index in (0, 1):
        if index < len(output) and "Kaiser" not in output[index]:
            found.append(f"nome Kaiser alterado na fala {index + 1}")
    if len(output) > 1 and "Haru" not in output[1]:
        found.append("nome Haru alterado")
    european = sorted({m.group(0).lower() for text in output for m in EUROPEAN.finditer(text)})
    if european:
        found.append("formas de Portugal: " + ", ".join(european))
    if any(re.search(r"yovember|ac7", text, re.I) for text in output):
        found.append("erro de OCR copiado")
    if any(len(re.findall(r"[^\W\d_]", text)) > 6 and text == text.upper() for text in output):
        found.append("tradução toda em maiúsculas")
    if any(re.search(r"[,;:!?](?=[^\W\d_])", text) for text in output):
        found.append("falta espaço após pontuação")
    return found or ["nenhum problema automático encontrado"]


async def available_models(base, key):
    import openai
    client = openai.AsyncOpenAI(api_key=key, base_url=base, max_retries=0, timeout=30)
    try:
        page = await client.models.list()
        return sorted({model.id.removeprefix("models/") for model in page.data})
    finally:
        await client.close()


async def run_provider(name, env, base, preferred):
    from manga_translator.config import TranslatorConfig
    from manga_translator.translators.custom_openai import CustomOpenAiTranslator
    key = os.environ.get(env, "").strip()
    if not key:
        notice(f"{name}: não testado", [f"Secret {env} não configurado no repositório."])
        return None
    print(f"::add-mask::{key}", flush=True)
    try:
        models = await available_models(base, key)
    except Exception as exc:
        notice(f"{name}: falha ao listar modelos", [type(exc).__name__])
        return None
    chosen = [m for m in preferred if m in models][:2] or preferred[:1]
    related = [m for m in models if re.search(r"flash|lite|gpt-oss|qwen|llama|gemma", m)][:25]
    notice(f"{name}: modelos disponíveis (amostra)", [", ".join(related) or "nenhum"])
    results = []
    for model in chosen:
        translator = CustomOpenAiTranslator(model=model, api_base=base, api_key=key)
        translator.parse_args(TranslatorConfig(translator="custom_openai", target_lang="PTB",
                                               gpt_config=str(ROOT / "profiles/scan-prompt.yaml")))
        started = time.monotonic()
        try:
            output = await translator.translate("ENG", "PTB", list(LINES))
            seconds = round(time.monotonic() - started, 1)
            lines = [f"{model} · {seconds}s · 1 pedido"]
            lines += [f"{i + 1}. {src} → {dst}" for i, (src, dst) in enumerate(zip(LINES, output))]
            lines += ["Verificação: " + "; ".join(checks(output))]
            notice(f"{name}: {model}", lines)
            results.append({"provider": name, "model": model, "seconds": seconds, "output": output,
                            "checks": checks(output)})
        except Exception as exc:
            notice(f"{name}: {model} falhou", [type(exc).__name__])
            results.append({"provider": name, "model": model, "error": type(exc).__name__})
        finally:
            await translator.client.close()
    return results


async def run_nllb():
    from engine_compat import apply_compatibility
    apply_compatibility()
    from manga_translator.translators.nllb import NLLBTranslator
    translator = NLLBTranslator()
    await translator.load("ENG", "PTB", "cpu")
    started = time.monotonic()
    output = await translator.translate("ENG", "PTB", list(LINES))
    seconds = round(time.monotonic() - started, 1)
    lines = [f"NLLB 600M · {seconds}s (CPU)"]
    lines += [f"{i + 1}. {src} → {dst}" for i, (src, dst) in enumerate(zip(LINES, output))]
    lines += ["Verificação: " + "; ".join(checks(output))]
    notice("Básico: NLLB", lines)
    return [{"provider": "Basico", "model": "nllb", "seconds": seconds, "output": output, "checks": checks(output)}]


async def run_rotation():
    """Groq with a model that does not exist must hand the page to Gemini."""
    import engine_compat
    from manga_translator.config import TranslatorConfig
    from manga_translator.translators.custom_openai import CustomOpenAiTranslator
    from providers import dump_secret
    keys = {env: os.environ.get(env, "").strip() for _, env, _, _ in PROVIDERS}
    if not all(keys.values()):
        notice("Alternância: não testada", ["Precisa dos dois secrets."])
        return []
    secret = Path("/tmp/providers-live.json")
    secret.write_text(dump_secret([
        {"name": "groq", "base": PROVIDERS[0][2], "model": "modelo-que-nao-existe", "key": keys["GROQ_API_KEY"]},
        {"name": "gemini", "base": PROVIDERS[1][2], "model": "gemini-flash-lite-latest", "key": keys["GEMINI_API_KEY"]},
    ]))
    os.environ["MANGALATE_API_KEY_FILE"] = str(secret)
    engine_compat._POOL = None
    translator = CustomOpenAiTranslator(model="modelo-que-nao-existe", api_base=PROVIDERS[0][2],
                                        api_key=keys["GROQ_API_KEY"])
    translator.parse_args(TranslatorConfig(translator="custom_openai", target_lang="PTB",
                                           gpt_config=str(ROOT / "profiles/scan-prompt.yaml")))
    started = time.monotonic()
    try:
        output = await translator.translate("ENG", "PTB", list(LINES[:3]))
        pool = engine_compat.provider_pool()
        resting = sorted(name for name, until in pool.resting.items() if until > pool.clock())
        notice("Alternância: Groq com modelo inválido → Gemini",
               [f"{round(time.monotonic() - started, 1)}s · em pausa: {', '.join(resting) or 'nenhum'}"]
               + [f"{i + 1}. {src} → {dst}" for i, (src, dst) in enumerate(zip(LINES, output))])
        return [{"rotation": "ok", "resting": resting, "output": output}]
    except Exception as exc:
        notice("Alternância falhou", [type(exc).__name__])
        return [{"rotation": "error", "error": type(exc).__name__}]
    finally:
        await translator.client.close()
        secret.unlink(missing_ok=True)


async def main():
    from engine_compat import apply_compatibility
    apply_compatibility()
    report = []
    for provider in PROVIDERS:
        report += await run_provider(*provider) or []
    report += await run_rotation()
    try:
        report += await run_nllb()
    except Exception as exc:
        notice("Básico: NLLB falhou", [type(exc).__name__])
    Path("/tmp/byok-live.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
