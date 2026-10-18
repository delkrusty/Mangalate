"""Interactive chapter processing for Colab or your own Docker worker. No tunnel."""
import argparse
import asyncio
import csv
import json
import re
import sys
import time
import traceback
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if not (ROOT / "profiles").exists():
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))
from gateway import open_page, inspect_result, profile_config

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def natural_key(path):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(path))]


def unpack_pages(archive, folder):
    """Limit zip bombs, duplicates and path traversal; never extract executable files."""
    with zipfile.ZipFile(archive) as bundle:
        entries = [x for x in bundle.infolist() if not x.is_dir() and Path(x.filename).suffix.lower() in IMAGE_SUFFIXES]
        if not entries or len(entries) > 300 or sum(x.file_size for x in entries) > 500 * 1024 * 1024:
            raise ValueError("Use até 300 páginas e 500 MB descompactados por capítulo.")
        seen = set()
        for item in entries:
            target = (folder / item.filename).resolve()
            if not target.is_relative_to(folder.resolve()) or target in seen:
                raise ValueError("Arquivo ZIP inseguro ou com nomes duplicados.")
            if item.file_size > 40 * 1024 * 1024:
                raise ValueError("Uma página passa de 40 MB.")
            seen.add(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.read(item))
    return sorted(seen, key=natural_key)


def select_pages(pages, spec):
    if not spec:
        return pages
    wanted = set()
    for part in spec.split(","):
        first, _, last = part.strip().partition("-")
        wanted.update(range(int(first), int(last or first) + 1))
    return [(index, path) for index, path in pages if index in wanted]


def save_diagnostics(folder, ctx, original):
    """Intermediate images and per-region data; no keys, URLs or provider bodies."""
    import numpy as np
    from PIL import Image, ImageDraw
    folder.mkdir(parents=True, exist_ok=True)
    original.save(folder / "1-original.png")
    def save_array(array, name):
        if array is not None:
            Image.fromarray(np.asarray(array).astype("uint8")).save(folder / name)
    save_array(getattr(ctx, "mask_raw", None), "2-mascara-detector.png")
    save_array(getattr(ctx, "mask", None), "4-mascara-final.png")
    # The renderer draws into img_inpainted; the copy taken before rendering is the clean page.
    clean = getattr(ctx, "mangalate_clean", None)
    save_array(clean if clean is not None else getattr(ctx, "img_inpainted", None), "5-limpa.png")
    kept = list(getattr(ctx, "text_regions", None) or [])
    preserved = list(getattr(ctx, "mangalate_preserved", None) or [])
    overlay = original.copy()
    draw = ImageDraw.Draw(overlay)
    rows = []
    for state, regions, colour in (("traduzida", kept, (0, 170, 0)), ("original_preservada", preserved, (220, 0, 0))):
        for region in regions:
            index = len(rows) + 1
            x0, y0, x1, y1 = (int(v) for v in region.xyxy)
            draw.rectangle((x0, y0, x1, y1), outline=colour, width=3)
            draw.text((x0 + 3, y0 + 3), str(index), fill=colour)
            for quad in region.lines:
                draw.polygon([tuple(int(c) for c in point) for point in quad], outline=(0, 90, 255))
            rows.append({"regiao": index, "estado": state, "caixa": [x0, y0, x1, y1],
                         "linhas": [[[int(c) for c in point] for point in quad] for quad in region.lines],
                         "fundo": getattr(region, "mangalate_background", None),
                         "ocr": str(getattr(region, "text_raw", region.text)),
                         "traducao": str(getattr(region, "translation", "") or "")})
    for repair in getattr(ctx, "mangalate_line_repairs", None) or []:
        for x0, y0, x1, y1 in repair["depois"]:
            draw.rectangle((x0 - 2, y0 - 2, x1 + 2, y1 + 2), outline=(255, 140, 0), width=2)
    for line in getattr(ctx, "mangalate_ocr_rescued", None) or []:
        x0, y0, x1, y1 = line["caixa"]
        draw.rectangle((x0 - 2, y0 - 2, x1 + 2, y1 + 2), outline=(160, 0, 200), width=2)
    if getattr(ctx, "mangalate_ocr_rescued", None):
        (folder / "ocr-resgatado.json").write_text(json.dumps(ctx.mangalate_ocr_rescued), encoding="utf-8")
    if getattr(ctx, "mangalate_line_repairs", None):
        (folder / "linhas-reparadas.json").write_text(json.dumps(ctx.mangalate_line_repairs), encoding="utf-8")
    for name, attr in (("linhas-detector.json", "mangalate_detector_lines"), ("ocr-linhas.json", "mangalate_ocr_lines"),
                       ("ocr-descartadas.json", "mangalate_ocr_lost")):
        if getattr(ctx, attr, None):
            (folder / name).write_text(json.dumps(getattr(ctx, attr), ensure_ascii=False), encoding="utf-8")
    overlay.save(folder / "3-regioes.png")
    (folder / "regioes.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


async def translate_with_patience(translator, image, config, waits=3):
    """When every AI is resting, wait for the first one to come back instead of failing pages."""
    from providers import AllProvidersResting
    for attempt in range(waits + 1):
        try:
            return await translator.translate(image, config)
        except AllProvidersResting as exc:
            if attempt == waits:
                raise
            seconds = min(max(exc.seconds, 5), 900)
            print(f"Todas as IAs em pausa; aguardando {round(seconds)} s para continuar.", flush=True)
            await asyncio.sleep(seconds)


def save_raw_answers(folder):
    """What each AI answered on a page that failed validation (local file, no keys)."""
    from engine_compat import provider_pool
    pool = provider_pool()
    raw = getattr(pool, "raw", None) if pool else None
    if not raw:
        return
    folder.mkdir(parents=True, exist_ok=True)
    parts = []
    for name, count, prompt, content in raw:
        parts += [f"===== {name}: esperava {count} falas", "--- pedido ---", prompt, "--- resposta ---", str(content), ""]
    (folder / "respostas-invalidas.txt").write_text("\n".join(parts), encoding="utf-8")


def provider_events():
    """Which AI failed on the last page and why (no text, keys or provider bodies)."""
    from engine_compat import provider_pool
    pool = provider_pool()
    return [f"{name}:{reason}" for name, reason in pool.events] if pool else []


async def run(args):
    import os
    if args.legacy:
        os.environ["MANGALATE_LEGACY_QUALITY"] = "true"
    if args.box_layout:
        os.environ["MANGALATE_BUBBLE_LAYOUT"] = "false"
    from engine_compat import apply_compatibility, set_page_context, set_page_rows, take_learned_terms
    apply_compatibility()
    from manga_translator import MangaTranslator, Config
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    pages = unpack_pages(args.input, output / "input")
    config = profile_config(args.profile, {"translator": {"target_lang": args.target}}, args.speed)
    # Whole-word wrapping avoids inappropriate English syllabification in PT-BR.
    config["render"]["no_hyphenation"] = True
    glossary = []
    if args.glossary:
        with args.glossary.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if not row.get("source") or not row.get("target"):
                    raise ValueError("Glossário CSV precisa das colunas source,target.")
                term = {"source": row["source"], "target": row["target"]}
                gender = (row.get("gender") or "").strip().lower()[:1]
                if gender in ("m", "f"):
                    term["gender"] = gender  # m/f: a character's gender, also when narrating
                glossary.append(term)
        if len(glossary) > 100:
            raise ValueError("Use no máximo 100 termos no glossário.")
    from memory import WorkMemory, remember
    # The work's memory lives in the worker's volume, shared with the app: a chapter
    # processed here teaches the glossary used when reading the next one, and back.
    memory = WorkMemory(None if args.no_memory else os.environ.get("MANGALATE_MEMORY_DIR", "/data/memoria"),
                        pinned=glossary)
    work_name = args.work or args.input.stem
    chapter_name = args.input.name
    translator = MangaTranslator({"use_gpu": args.gpu, "use_gpu_limited": args.gpu_limited,
                                  "verbose": False, "kernel_size": int(config.get("kernel_size", 3))})
    report, consecutive_failures = [], 0
    from seams import SeamCache, Strip, finish
    seam_cache, salt = SeamCache(), json.dumps(config, sort_keys=True)

    def neighbour(position):
        if args.no_seams or not 1 <= position <= len(pages):
            return None
        return open_page(pages[position - 1].read_bytes())

    for index, path in select_pages(list(enumerate(pages, 1)), args.pages):
        name = f"{index:04d}.png"
        print(f"Página {index}/{len(pages)}: {path.name}", flush=True)
        original = open_page(path.read_bytes())
        originals = output / "originals"
        originals.mkdir(exist_ok=True)
        original.save(originals / name)
        entry = {"page": name, "source_file": path.relative_to(output / "input").as_posix(), "review_required": True}
        try:
            if consecutive_failures >= 3:
                raise RuntimeError("Processamento suspenso após três falhas consecutivas; originais preservados.")
            set_page_context(memory.context(work_name, chapter_name, index) if args.profile == "byok" else None)
            started = time.monotonic()
            strip = Strip(original, neighbour(index - 1), neighbour(index + 1))
            set_page_rows(strip.top, strip.bottom)
            ctx = await translate_with_patience(translator, strip.image, Config(**config))
            result = finish(strip, ctx.result, getattr(ctx, "text_regions", None) if strip.stitched else None,
                            seam_cache, salt)
            entry["seams"] = {"above": strip.above is not None, "below": strip.below is not None}
            entry["seconds"] = round(time.monotonic() - started, 1)
            from speed import summary
            if getattr(ctx, "mangalate_timings", None):
                entry["timings"] = ctx.mangalate_timings
                print(f"  Tempos: {summary(ctx.mangalate_timings)}", flush=True)
            entry.update(inspect_result(original, result))
            pairs = [
                {"original": str(getattr(r, "text_raw", r.text)), "translation": str(r.translation)}
                # The engine leaves text_regions as None on pages without text.
                for r in (getattr(ctx, "text_regions", None) or [])
            ]
            entry["regions"] = pairs
            repairs = getattr(ctx, "mangalate_line_repairs", None)
            if repairs:
                entry["line_repairs"] = len(repairs)
            rescued = getattr(ctx, "mangalate_ocr_rescued", None)
            if rescued:
                entry["ocr_rescued"] = len(rescued)
            if args.diagnostics:
                # Diagnostic images use the strip, whose coordinates match the regions.
                rows = save_diagnostics(output / "diagnostico" / f"{index:04d}", ctx, strip.image)
                entry["preserved_regions"] = sum(row["estado"] == "original_preservada" for row in rows)
                # Also when a second try or another AI saved the page: why the first answer failed.
                save_raw_answers(output / "diagnostico" / f"{index:04d}")
            entry["status"] = "review" if pairs else "no_text_review"
            if provider_events():
                entry["provider_events"] = provider_events()
            terms = take_learned_terms()
            if args.profile == "byok":
                added = remember(memory, {"obra": work_name, "capitulo": chapter_name, "pagina": index},
                                 getattr(ctx, "text_regions", None), terms)
                if added:
                    entry["new_terms"] = [f"{source}={target}" for source, target in added]
            consecutive_failures = 0
        except Exception as exc:
            # Keep the original, clearly flagging failures; never export a blank page.
            result = original
            unusable = type(exc).__name__ == "UnusableAnswer"
            # A page the AIs could not translate is content, not a broken server: keep going.
            if not unusable:
                consecutive_failures += 1
            if unusable and args.diagnostics:
                save_raw_answers(output / "diagnostico" / f"{index:04d}")
            entry.update(status="translation_unusable_original_preserved" if unusable else "blocked_original_preserved",
                         provider_events=provider_events(), error=type(exc).__name__,
                         # File/line/function only: no page text, keys or provider bodies.
                         trace=[f"{Path(f.filename).name}:{f.lineno}:{f.name}"
                                for f in traceback.extract_tb(exc.__traceback__)[-8:]])
        translated = output / "translated"
        translated.mkdir(exist_ok=True)
        result.save(translated / name)
        report.append(entry)
    if args.profile == "byok":
        # Pinned + learned terms, ready to correct and pass back with --glossary.
        with (output / "glossario.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["source", "target", "gender"], restval="",
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(memory.glossary(work_name))
    (output / "review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    def safe(value):
        return str(value).replace("|", "\\|").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")
    notes = ["# Revisão do capítulo", "", "Compare cada página antes de ler/distribuir como edição final.", ""]
    for entry in report:
        name = entry["page"]
        notes += [f"## Página {name}", f"Estado: {entry['status']}. Revisão humana necessária.",
                  f"[Original](originals/{name}) | [Resultado](translated/{name})", "",
                  "| Texto reconhecido | Tradução |", "|---|---|"]
        notes += [f"| {safe(pair['original'])} | {safe(pair['translation'])} |" for pair in entry.get("regions", [])]
        notes += [""]
    (output / "revisao.md").write_text("\n".join(notes), encoding="utf-8")
    with zipfile.ZipFile(output / "capitulo-para-revisar.cbz", "w", zipfile.ZIP_DEFLATED) as book:
        for page in sorted((output / "translated").glob("*.png")):
            book.write(page, page.name)
    with zipfile.ZipFile(output / "revisao-completa.zip", "w", zipfile.ZIP_DEFLATED) as book:
        for folder in ("originals", "translated"):
            for page in sorted((output / folder).glob("*.png")):
                book.write(page, f"{folder}/{page.name}")
        book.write(output / "review.json", "review.json")
        book.write(output / "revisao.md", "revisao.md")
    print("Exportados capitulo-para-revisar.cbz e revisao-completa.zip. Confira a revisão antes de chamar de scan final.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("basic", "byok"), default="basic")
    parser.add_argument("--target", default="PTB")
    parser.add_argument("--gpu", action="store_true")
    parser.add_argument("--gpu-limited", action="store_true")
    parser.add_argument("--glossary", type=Path, help="CSV source,target com nomes e termos fixos (vence o aprendido)")
    parser.add_argument("--work", help="Nome da obra para a memória (padrão: nome do arquivo)")
    parser.add_argument("--no-memory", action="store_true",
                        help="Não usa nem grava a memória da obra (glossário aprendido e páginas anteriores)")
    parser.add_argument("--pages", help="Só estas páginas, ex.: 2,22-26,114")
    parser.add_argument("--diagnostics", action="store_true",
                        help="Salva máscaras, regiões, OCR e tradução de cada página em diagnostico/")
    parser.add_argument("--speed", choices=("quality", "fast"),
                        help="quality: limpeza mais fina; fast: mais rápido em CPU (padrão: o do servidor)")
    parser.add_argument("--no-seams", action="store_true",
                        help="Traduz cada página sozinha, sem emendar balões cortados entre páginas")
    parser.add_argument("--box-layout", action="store_true",
                        help="Encaixa o texto na caixa do original, como na 0.5.3, para comparar com o ajuste ao balão")
    parser.add_argument("--legacy", action="store_true",
                        help="Usa a limpeza e o espaçamento da 0.5.2, para comparar antes/depois")
    asyncio.run(run(parser.parse_args()))
