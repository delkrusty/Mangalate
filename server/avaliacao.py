"""Scores translated rounds without a person looking first, and compares two rounds.

Runs on the PC (host Python, not inside the image) over folders written by
colab/batch.py with --diagnostics. It never calls an AI and never reads secrets.

    py avaliacao.py rodar --rodada base-1 [--gpu]       # runs the local corpus (teste/corpus.json)
    py avaliacao.py medir teste-curto/base-1             # writes avaliacao.json and avaliacao.md
    py avaliacao.py comparar teste-curto/base-1 teste-curto/base-2

The numbers point to the pages worth opening; they do not replace looking at them
(CLAUDE.md, quality priorities). Each metric maps to one priority:
  1 arte_longe     changed pixels far from any text region (art erased or smeared)
  2 restos         dark leftovers where the original letters were, inside a cleaned bubble
  3 fala_ingles    translated regions that stayed in English or came back empty
    fala_preservada  speech in a bubble or window left in the original
  5 letra_pequena  translations whose capitals are under 70% of the original capitals
"""
import argparse
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent

# Pixel difference (0-255, max over channels) that counts as a change; below it is
# PNG/colour noise from the engine's round trip.
CHANGE_LEVEL = 40
# Area kept around each text box, as a share of its own width/height on each side,
# plus a floor in pixels: the translation may be laid out over the whole bubble.
BOX_MARGIN_SHARE = 0.6
BOX_MARGIN_MIN_PX = 16
# A blob of change outside the protected area counts when it is at least this share of
# the page (0.05% of a 1000x1500 page is 750 px, about a 27x27 square).
FAR_BLOB_SHARE = 0.0005
# Grey-level standard deviation under which the original spot was flat background.
FLAT_ORIGINAL_STD = 12
# Luminance distance from the bubble background that counts as a leftover letter pixel.
LEFTOVER_LEVEL = 70
# Share of the original line area still dark after cleaning that flags a region.
LEFTOVER_SHARE = 0.02
# Translation capitals (about 0.7 of the font size) against the original capitals.
CAPS_PER_FONT_SIZE = 0.7
SMALL_LETTER_RATIO = 0.7
# Region backgrounds that are speech in a frame: leaving them in the original loses speech.
SPEECH_KINDS = {"interior", "janela", "tracos"}
CLEAN_KINDS = {"interior", "janela"}
# Words that only English uses; two of them in a translation mean it stayed in English.
ENGLISH_ONLY = set("""the you your you're i'm i'll i've don't can't won't it's that's what's
he's she's they're we're isn't aren't wasn't didn't doesn't is are was were been being have has
had will would should could this that these those what where when why who which with for from
and but not just all about there their them they she he his her him our we us my me it of to in
on at be do does did get got going gonna wanna yeah okay oh hey""".split())
ENGLISH_MIN_WORDS = 2
ENGLISH_MIN_SHARE = 0.3

STATUS_FAILED = {"translation_unusable_original_preserved", "blocked_original_preserved"}


def read_image(path):
    """cv2.imread fails on non-ASCII Windows paths; decode the bytes instead."""
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    if image is None:
        raise ValueError(f"Imagem ilegível: {path}")
    return image


def letters(text):
    text = unicodedata.normalize("NFKD", str(text or "")).lower()
    return re.sub(r"[^a-z]", "", text)


def english_words(text):
    words = re.findall(r"[a-z']+", str(text or "").lower().replace("’", "'"))
    hits = sum(word in ENGLISH_ONLY for word in words)
    return hits, len(words)


def stayed_english(original, translation):
    """Empty, identical to the original (ignoring case and punctuation) or mostly English words."""
    source, target = letters(original), letters(translation)
    if not source:
        return False  # punctuation only ("...", "!?") has nothing to translate
    if not target:
        return True
    hits, total = english_words(translation)
    if source == target:
        return hits > 0  # "BLA", "HA HA" and names are the same in Portuguese

    return hits >= ENGLISH_MIN_WORDS and hits >= ENGLISH_MIN_SHARE * total


def strip_offset(strip, page):
    """Row where the page starts inside the diagnostic strip (seams borrow rows above)."""
    extra = strip.shape[0] - page.shape[0]
    if extra <= 0 or strip.shape[1] != page.shape[1]:
        return 0
    probes = [0, page.shape[0] // 2, page.shape[0] - 1]
    best, best_error = 0, None
    for offset in range(extra + 1):
        error = sum(float(np.abs(strip[offset + row].astype(int) - page[row].astype(int)).mean()) for row in probes)
        if best_error is None or error < best_error:
            best, best_error = offset, error
            if error == 0:
                break
    return best


def protected_area(shape, rows, offset):
    """Text boxes grown by their margin, in page coordinates."""
    height, width = shape[:2]
    area = np.zeros((height, width), np.uint8)
    for row in rows:
        x0, y0, x1, y1 = row["caixa"]
        y0, y1 = y0 - offset, y1 - offset
        grow_x = max(BOX_MARGIN_MIN_PX, int((x1 - x0) * BOX_MARGIN_SHARE))
        grow_y = max(BOX_MARGIN_MIN_PX, int((y1 - y0) * BOX_MARGIN_SHARE))
        x0, x1 = max(0, x0 - grow_x), min(width, x1 + grow_x)
        y0, y1 = max(0, y0 - grow_y), min(height, y1 + grow_y)
        if x1 > x0 and y1 > y0:
            area[y0:y1, x0:x1] = 1
    return area


def far_changes(original, translated, rows, offset):
    """Blobs of change outside every protected box: (blob count, largest blob share of the page, boxes)."""
    if original.shape != translated.shape:
        return {"manchas": 1, "maior": 1.0, "caixas": []}
    delta = np.abs(original.astype(np.int16) - translated.astype(np.int16)).max(axis=2)
    changed = (delta > CHANGE_LEVEL).astype(np.uint8)
    changed[protected_area(original.shape, rows, offset) > 0] = 0
    changed = cv2.morphologyEx(changed, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(changed, connectivity=8)
    page_area = changed.shape[0] * changed.shape[1]
    gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)

    def had_art(stat):
        # Text drawn over flat background (a translation moved into empty black or white) is
        # not lost art; erased art is a change where the original had lines or tone.
        x, y, w, h = stat[:4]
        return float(gray[y:y + h, x:x + w].std()) > FLAT_ORIGINAL_STD

    blobs = [stats[i] for i in range(1, count)
             if stats[i][cv2.CC_STAT_AREA] >= FAR_BLOB_SHARE * page_area and had_art(stats[i])]
    largest = max((b[cv2.CC_STAT_AREA] for b in blobs), default=0)
    boxes = [[int(b[0]), int(b[1]), int(b[0] + b[2]), int(b[1] + b[3])] for b in blobs]
    return {"manchas": len(blobs), "maior": round(largest / page_area, 5), "caixas": boxes[:10]}


def leftover_share(clean, row):
    """Share of the original line area that is still far from the bubble background after cleaning."""
    gray = cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY)
    mask = np.zeros(gray.shape, np.uint8)
    for quad in row.get("linhas") or []:
        cv2.fillPoly(mask, [np.array(quad, np.int32)], 1)
    x0, y0, x1, y1 = (max(0, v) for v in row["caixa"])
    inside = mask[y0:y1, x0:x1] > 0
    if inside.sum() < 20:
        return 0.0
    patch = gray[y0:y1, x0:x1].astype(np.int16)
    # Row by row: system windows and coloured panels fade from top to bottom, and a single
    # median turns the gradient itself into "leftovers".
    background = np.median(patch, axis=1, keepdims=True)
    inside_rows = np.broadcast_to(background, patch.shape)[inside]
    return float(np.mean(np.abs(patch[inside] - inside_rows) > LEFTOVER_LEVEL))


def score_page(run, entry):
    """Metrics of one page of a round."""
    name = entry["page"]
    page = {"pagina": name, "estado": entry.get("status"), "segundos": entry.get("seconds"),
            "regioes": len(entry.get("regions") or [])}
    if entry.get("status") in STATUS_FAILED:
        page["falhou"] = True
        return page
    page["fala_ingles"] = [pair.get("original", "") for pair in entry.get("regions") or []
                           if stayed_english(pair.get("original"), pair.get("translation"))]
    folder = run / "diagnostico" / Path(name).stem
    rows_path = folder / "regioes.json"
    if not rows_path.exists():
        page["sem_diagnostico"] = True
        return page
    rows = json.loads(rows_path.read_text(encoding="utf-8"))
    kind = lambda row: (row.get("fundo") or {}).get("kind") if isinstance(row.get("fundo"), dict) else None
    page["fala_preservada"] = [row["ocr"] for row in rows
                               if row["estado"] == "original_preservada" and kind(row) in SPEECH_KINDS]
    page["arte_preservada"] = sum(row["estado"] == "original_preservada" and kind(row) == "art" for row in rows)
    original = read_image(run / "originals" / name)
    translated = read_image(run / "translated" / name)
    strip_path = folder / "1-original.png"
    offset = strip_offset(read_image(strip_path), original) if strip_path.exists() else 0
    page["arte_longe"] = far_changes(original, translated, rows, offset)
    clean_path = folder / "5-limpa.png"
    restos = []
    if clean_path.exists():
        clean = read_image(clean_path)
        for row in rows:
            if row["estado"] == "traduzida" and kind(row) in CLEAN_KINDS:
                share = leftover_share(clean, row)
                if share > LEFTOVER_SHARE:
                    restos.append({"regiao": row["regiao"], "parte": round(share, 3)})
    page["restos"] = restos
    small = []
    for row in rows:
        size = row.get("letra") or {}
        if row["estado"] == "traduzida" and size.get("tamanho") and size.get("original"):
            ratio = CAPS_PER_FONT_SIZE * size["tamanho"] / size["original"]
            if ratio < SMALL_LETTER_RATIO:
                small.append({"regiao": row["regiao"], "razao": round(ratio, 2)})
    page["letra_pequena"] = small
    return page


def problems(page):
    """Counts per metric, in priority order; the page's weight in the summary."""
    if page.get("falhou"):
        return {"falhou": 1}
    far = page.get("arte_longe") or {}
    return {"arte_longe": far.get("manchas", 0), "restos": len(page.get("restos") or []),
            "fala_ingles": len(page.get("fala_ingles") or []),
            "fala_preservada": len(page.get("fala_preservada") or []),
            "letra_pequena": len(page.get("letra_pequena") or [])}


METRICS = ("falhou", "arte_longe", "restos", "fala_ingles", "fala_preservada", "letra_pequena")


def find_runs(root):
    """Every folder under root that has a review.json (one per batch.py output)."""
    root = Path(root)
    return sorted({path.parent for path in root.rglob("review.json")}, key=lambda p: str(p))


def measure(root):
    root = Path(root)
    result = {"rodada": root.name, "trechos": {}}
    for run in find_runs(root):
        entries = json.loads((run / "review.json").read_text(encoding="utf-8"))
        key = run.relative_to(root).as_posix() if run != root else "."
        result["trechos"][key] = [score_page(run, entry) for entry in entries]
    totals = dict.fromkeys(METRICS, 0)
    pages = 0
    for scored in result["trechos"].values():
        for page in scored:
            pages += 1
            for metric, value in problems(page).items():
                totals[metric] += value
    result["total"] = {"paginas": pages, **totals}
    return result


def summary_md(result):
    lines = [f"# Avaliação automática: {result['rodada']}", "",
             "Números para achar as páginas a abrir; o veredito continua sendo olhar a página.", "",
             "| Trecho | Páginas | " + " | ".join(METRICS) + " |", "|---|---" + "|---" * len(METRICS) + "|"]
    for key, scored in result["trechos"].items():
        sums = dict.fromkeys(METRICS, 0)
        for page in scored:
            for metric, value in problems(page).items():
                sums[metric] += value
        lines.append(f"| {key} | {len(scored)} | " + " | ".join(str(sums[m]) for m in METRICS) + " |")
    total = result["total"]
    lines.append(f"| **total** | {total['paginas']} | " + " | ".join(str(total[m]) for m in METRICS) + " |")
    lines += ["", "## Páginas com problema", ""]
    for key, scored in result["trechos"].items():
        for page in scored:
            found = {m: v for m, v in problems(page).items() if v}
            if found:
                lines.append(f"- {key}/{page['pagina']}: " + ", ".join(f"{m} {v}" for m, v in found.items()))
    return "\n".join(lines) + "\n"


def page_changed(before_run, after_run, name):
    """Share of the page whose translated pixels differ between two rounds."""
    try:
        a, b = read_image(before_run / "translated" / name), read_image(after_run / "translated" / name)
    except (ValueError, OSError):
        return None
    if a.shape != b.shape:
        return 1.0
    delta = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2)
    return round(float(np.mean(delta > CHANGE_LEVEL)), 4)


def compare(before_root, after_root):
    before_root, after_root = Path(before_root), Path(after_root)
    before, after = measure(before_root), measure(after_root)
    rows, worse, better = [], [], []
    # Totals only over the pages both rounds have, so a missing stretch is not a gain.
    totals_before, totals_after = dict.fromkeys(("paginas",) + METRICS, 0), dict.fromkeys(("paginas",) + METRICS, 0)
    for key, pages in after["trechos"].items():
        old = {page["pagina"]: page for page in before["trechos"].get(key, [])}
        for page in pages:
            if page["pagina"] not in old:
                continue
            a, b = problems(old[page["pagina"]]), problems(page)
            for totals, counts in ((totals_before, a), (totals_after, b)):
                totals["paginas"] += 1
                for metric, value in counts.items():
                    totals[metric] += value
            delta = {m: b.get(m, 0) - a.get(m, 0) for m in METRICS if b.get(m, 0) != a.get(m, 0)}
            moved = page_changed(before_root / key, after_root / key, page["pagina"])
            label = f"{key}/{page['pagina']}"
            rows.append({"pagina": label, "mudou": moved, "delta": delta})
            if any(v > 0 for v in delta.values()):
                worse.append(label)
            elif delta:
                better.append(label)
    return {"antes": totals_before, "depois": totals_after, "paginas": rows,
            "piorou": worse, "melhorou": better,
            "faltando": sorted(set(before["trechos"]) - set(after["trechos"]))}


def compare_md(diff, before_name, after_name):
    lines = [f"# {before_name} → {after_name}", "", "| Métrica | Antes | Depois |", "|---|---|---|"]
    for metric in ("paginas",) + METRICS:
        lines.append(f"| {metric} | {diff['antes'].get(metric, 0)} | {diff['depois'].get(metric, 0)} |")
    changed = [row for row in diff["paginas"] if row["mudou"]]
    lines += ["", f"Páginas com pixels diferentes: {len(changed)} de {len(diff['paginas'])} (abra todas).", ""]
    for row in changed:
        delta = ", ".join(f"{m} {v:+d}" for m, v in row["delta"].items()) or "métricas iguais"
        lines.append(f"- {row['pagina']}: {row['mudou']:.1%} da página; {delta}")
    if diff["piorou"]:
        lines += ["", "**Pioraram em alguma métrica:** " + ", ".join(diff["piorou"])]
    if diff["faltando"]:
        lines += ["", "**Trechos que não rodaram depois:** " + ", ".join(diff["faltando"])]
    return "\n".join(lines) + "\n"


def image_override(service, image):
    """Compose file that runs the round on another image (a commit built with --imagem), so the
    server the app uses keeps running its own version."""
    if not re.fullmatch(r"[\w.\-/]+:[\w.\-]+", image):
        raise ValueError(f"Nome de imagem inválido: {image}")
    return f"services:\n  {service}:\n    image: {image}\n"


def corpus_commands(corpus, round_name, gpu=False, workdir=HERE, override=None):
    """One docker command per corpus entry, the same as CLAUDE.md's test round."""
    service, profile = ("translator-gpu", "gpu") if gpu else ("translator-cpu", "cpu")
    compose = ["docker", "compose"]
    if override:
        compose += ["-f", str(Path(workdir) / "docker-compose.yml"), "-f", str(override)]
    commands = []
    for item in corpus:
        output = f"/work/teste-curto/{round_name}/{item['id']}"
        command = compose + ["--profile", profile, "run", "--rm", "-v", f"{workdir}:/work", service,
                   "/mangalate/batch.py", "--input", f"/work/teste/{item['capitulo']}", "--pages", str(item["paginas"]),
                   "--work", item.get("obra") or item["id"], "--output", output, "--profile", "byok",
                   "--speed", item.get("speed", "fast"), "--diagnostics"]
        if not item.get("memoria"):
            # The work's memory changes between rounds (it learns from each one), so two rounds
            # of the same corpus are only comparable without it.
            command.append("--no-memory")
        if item.get("art_text"):
            command += ["--art-text", item["art_text"]]
        if gpu:
            command.append("--gpu")
        commands.append((item, command))
    return commands


def load_corpus(path):
    corpus = json.loads(Path(path).read_text(encoding="utf-8"))
    ids = [item["id"] for item in corpus]
    if len(ids) != len(set(ids)):
        raise ValueError("Cada trecho do corpus precisa de um id único.")
    for item in corpus:
        if not re.fullmatch(r"[\w.-]+", item["id"]) or "/" in item["capitulo"] or "\\" in item["capitulo"]:
            raise ValueError(f"id ou capítulo inválido: {item['id']}")
    return corpus


def run_corpus(args):
    corpus = load_corpus(args.corpus or Path(args.servidor) / "teste" / "corpus.json")
    if args.only:
        wanted = set(args.only.split(","))
        corpus = [item for item in corpus if item["id"] in wanted]
    server = Path(args.servidor).resolve()
    target = server / "teste-curto" / args.rodada
    target.mkdir(parents=True, exist_ok=True)
    override = None
    if args.imagem:
        override = target / "compose-imagem.yml"
        override.write_text(image_override("translator-gpu" if args.gpu else "translator-cpu", args.imagem),
                            encoding="utf-8")
    for item, command in corpus_commands(corpus, args.rodada, args.gpu, server, override):
        if (target / item["id"] / "review.json").exists():
            print(f"{item['id']}: já rodado, pulando.")
            continue
        print(f"{item['id']} ({item.get('estilo', '')}): páginas {item['paginas']}", flush=True)
        with (target / f"{item['id']}.log").open("w", encoding="utf-8") as log:
            code = subprocess.call(command, cwd=server, stdout=log, stderr=subprocess.STDOUT)
        if code:
            print(f"  terminou com código {code}; veja {item['id']}.log", flush=True)
    write_measure(target)


def write_measure(root):
    root = Path(root)
    result = measure(root)
    (root / "avaliacao.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    (root / "avaliacao.md").write_text(summary_md(result), encoding="utf-8")
    print(summary_md(result).split("## Páginas")[0])
    print(f"Detalhes em {root / 'avaliacao.md'}")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console defaults to cp1252
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("rodar", help="Roda o corpus local e mede")
    run.add_argument("--rodada", required=True)
    run.add_argument("--servidor", default=str(HERE),
                     help="Pasta server/ com teste/, teste-curto/, .env e secrets/ (padrão: esta)")
    run.add_argument("--corpus", help="Padrão: <servidor>/teste/corpus.json")
    run.add_argument("--imagem", help="Roda com esta imagem (ex.: mangalate-translator-cpu:base), sem trocar o servidor do app")
    run.add_argument("--only", help="Só estes ids, separados por vírgula")
    run.add_argument("--gpu", action="store_true")
    meas = sub.add_parser("medir", help="Mede uma rodada que já existe")
    meas.add_argument("pasta")
    comp = sub.add_parser("comparar", help="Compara duas rodadas do mesmo corpus")
    comp.add_argument("antes")
    comp.add_argument("depois")
    args = parser.parse_args(argv)
    if args.command == "rodar":
        run_corpus(args)
    elif args.command == "medir":
        write_measure(args.pasta)
    else:
        diff = compare(args.antes, args.depois)
        text = compare_md(diff, Path(args.antes).name, Path(args.depois).name)
        (Path(args.depois) / "comparacao.md").write_text(text, encoding="utf-8")
        print(text)
        return 1 if diff["piorou"] else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
