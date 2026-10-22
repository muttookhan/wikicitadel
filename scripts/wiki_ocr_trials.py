#!/usr/bin/env python3
"""wiki_ocr_trials.py — OCR engine trials for the open OCR queue
(W4 implementation wave, 2026-10-22; build-list item "OCR engine
trials for the open OCR queue").

The wiki's trust posture for machine-read text already exists:
scripts/wiki_ocr_queue.py (the ABBYY FineReader Verification
pattern — confidence recorded exactly as reported, "unknown"
queues like a low number, nothing rests a cited claim on
unverified extraction) and scripts/wiki_preocr.py (the pre-ingest
seam that refuses cleanly when no engine is configured). What
did not exist is a MEASUREMENT of candidate OCR engines against
that posture. This module is that measurement:

  * a REGISTRY of candidate engines, each probed live (import /
    PATH / node require) — availability is established, never
    assumed, and an unavailable engine is an honest DOOR whose
    blocker is recorded verbatim, exactly as the document-engine
    trials (scripts/wiki_convert_engines.py) door theirs;
  * a FIXTURE SET of synthetic scanned pages whose ground truth
    is known by construction (rendered from stated text with
    stated fonts, then degraded by stated operations). They are
    labelled synthetic everywhere they appear. Accuracy is only
    ever measured against known ground truth — never against a
    real document whose true text is merely believed;
  * per-engine RUNS over the same fixtures producing image+text
    paired output (the multi-engine comparison shape from the
    build-list spec): recognised text, per-word confidences
    exactly as the engine emits them (never recalibrated),
    character/word error rates, wall time, and a confidence-
    honesty block (mean reported confidence vs measured word
    accuracy; the share of words that would queue under the
    OCR queue's CONFIDENCE_THRESHOLD; mean confidence of the
    words the engine got WRONG);
  * a reference recognizer ("template-matcher") — this project's
    own code, a same-font glyph template matcher over PIL+numpy.
    It exists so the measurement pipeline is exercised end to
    end with genuine recognition behaviour (real errors, real
    confidences) on the synthetic fixtures. It is NOT a
    candidate engine for the corpus: it recognises only the one
    font/size it holds templates for, and the record says so.
  * a preocr STAGE adapter: make_preocr_stage(name) returns a
    callable with scripts/wiki_preocr.py's stage contract
    (path -> (text, confidence)); an unavailable engine raises
    wiki_preocr.OcrUnavailable with the verbatim blocker — the
    seam's clean refusal, never a silent pass-through.

Licence routes, judged at source 2026-10-22:
  tesseract    Apache-2.0 (tesseract-ocr/tesseract) —
               adapt-with-credit; a wrapper shells to the
               binary, no code carried.
  easyocr      Apache-2.0 (JaidedAI/EasyOCR) —
               adapt-with-credit; adapter is our own code.
               First run downloads detection + recognition
               weights (torch hub / module download, >100 MB)
               — a network download, never attempted here.
  paddleocr    Apache-2.0 (PaddlePaddle/PaddleOCR) —
               adapt-with-credit; needs the paddlepaddle
               backend; models download on first use.
  rapidocr     Apache-2.0 (RapidAI/RapidOCR) —
               adapt-with-credit; onnxruntime backend, models
               bundled with the package.
  keras-ocr    MIT (faustomorales/keras-ocr) —
               adapt-with-credit; needs tensorflow; weights
               download on first use.
  tesseract.js Apache-2.0 (naptha/tesseract.js) —
               adapt-with-credit; the WASM core and traineddata
               are fetched at install/runtime by default. (The
               Lens-surface build item owns its UI side; it is
               registered here only as an engine candidate.)
  ocrmypdf     MPL-2.0 — IDEAS ONLY / interface: per the
               standing wiki_preocr.py precedent, no code is
               adapted; it would be driven as an external CLI.
  docling      MIT — adapt-with-credit; its OCR capability is
               registered in scripts/wiki_convert_engines.py;
               cross-referenced here, probed by the same import.
  template-matcher — this project's own code (the reference
               recognizer above); no external licence.

Local-only: no hosted OCR API is ever called, no package is
installed, no model is downloaded. An engine that needs any of
those to exist here is doored with that stated.

Usage:
  python3 scripts/wiki_ocr_trials.py probe [--json]
  python3 scripts/wiki_ocr_trials.py fixtures --out DIR
  python3 scripts/wiki_ocr_trials.py run [--fixtures DIR]
      [--engine NAME ...] [--out record.json]
  python3 scripts/wiki_ocr_trials.py measure-pdf PATH [--json]
Exit: 0 ok; 2 usage error. Requires PIL + numpy for the
fixture/matcher machinery (probed, and their absence doors the
fixture half, never fakes it).
"""
import argparse
import hashlib
import importlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

# The queue's stated policy threshold — imported so this record
# can never drift from the queue's own number.
try:
    from wiki_ocr_queue import CONFIDENCE_THRESHOLD
except Exception:  # pragma: no cover — queue module is in-tree
    CONFIDENCE_THRESHOLD = 0.90

TRIAL_DATE = "2026-10-22"
FIXTURE_SEED = 20261022

FONT_DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_SERIF = ("/usr/share/fonts/truetype/liberation/"
              "LiberationSerif-Regular.ttf")

# ------------------------------------------------------------ registry

def _module_probe(module_names):
    """Import probe in THIS interpreter; blocker verbatim."""
    last = None
    for name in module_names:
        try:
            mod = importlib.import_module(name)
            return {"available": True,
                    "version": getattr(mod, "__version__", None),
                    "blocker": None}
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
    return {"available": False, "version": None,
            "blocker": last or "no importable module"}


def _binary_probe(binary):
    path = shutil.which(binary)
    if path:
        return {"available": True, "version": path,
                "blocker": None}
    return {"available": False, "version": None,
            "blocker": f"shutil.which({binary!r}) returned None "
                       f"— not on PATH"}


def _node_probe(module):
    node = shutil.which("node")
    if not node:
        return {"available": False, "version": None,
                "blocker": "node not on PATH"}
    try:
        proc = subprocess.run(
            [node, "-e", f"require({module!r})"],
            capture_output=True, text=True, timeout=30)
    except Exception as exc:
        return {"available": False, "version": None,
                "blocker": f"{type(exc).__name__}: {exc}"}
    if proc.returncode == 0:
        return {"available": True, "version": node,
                "blocker": None}
    first = (proc.stderr or "").strip().splitlines()
    err = next((ln.strip() for ln in first
                if ln.strip().startswith("Error")), "require failed")
    return {"available": False, "version": None,
            "blocker": f"node require({module!r}): {err}"}


def _matcher_probe():
    missing = []
    for name in ("PIL", "numpy"):
        try:
            importlib.import_module(name)
        except Exception as exc:
            missing.append(f"{type(exc).__name__}: {exc}")
    if missing:
        return {"available": False, "version": None,
                "blocker": "; ".join(missing)}
    if not Path(FONT_DEJAVU).is_file():
        return {"available": False, "version": None,
                "blocker": f"template font not on disk: "
                           f"{FONT_DEJAVU}"}
    import PIL
    import numpy
    return {"available": True,
            "version": f"PIL {PIL.__version__}, "
                       f"numpy {numpy.__version__}",
            "blocker": None}


ENGINES = {
    "tesseract": {
        "label": "Tesseract OCR (binary, subprocess wrapper)",
        "licence": "Apache-2.0",
        "licence_route": "adapt-with-credit",
        "role": "candidate",
        "probe": lambda: _binary_probe("tesseract"),
        "first_run_downloads": None,
        "notes": "the classic local engine; reports per-word "
                 "confidence via TSV output; the wrapper would "
                 "be our own subprocess code",
    },
    "easyocr": {
        "label": "EasyOCR (JaidedAI/EasyOCR)",
        "licence": "Apache-2.0",
        "licence_route": "adapt-with-credit",
        "role": "candidate",
        "probe": lambda: _module_probe(["easyocr"]),
        "first_run_downloads": "detection + recognition model "
                               "weights (>100 MB) on first use",
        "notes": "the build-list spec's named candidate: a "
                 "confidence score on every span; needs torch",
    },
    "paddleocr": {
        "label": "PaddleOCR (PaddlePaddle/PaddleOCR)",
        "licence": "Apache-2.0",
        "licence_route": "adapt-with-credit",
        "role": "candidate",
        "probe": lambda: _module_probe(["paddleocr"]),
        "first_run_downloads": "model files on first use; "
                               "paddlepaddle backend package",
        "notes": "per-span confidences; heavy backend",
    },
    "rapidocr": {
        "label": "RapidOCR (RapidAI/RapidOCR)",
        "licence": "Apache-2.0",
        "licence_route": "adapt-with-credit",
        "role": "candidate",
        "probe": lambda: _module_probe(["rapidocr_onnxruntime"]),
        "first_run_downloads": None,
        "notes": "onnxruntime-based; models ship inside the "
                 "package, so an install alone would make it "
                 "runnable offline",
    },
    "keras-ocr": {
        "label": "keras-ocr (faustomorales/keras-ocr)",
        "licence": "MIT",
        "licence_route": "adapt-with-credit",
        "role": "candidate",
        "probe": lambda: _module_probe(["keras_ocr"]),
        "first_run_downloads": "detector + recognizer weights "
                               "on first use; tensorflow backend",
        "notes": "pipeline API; per-word predictions carry no "
                 "calibrated confidence (recorded as such if "
                 "ever run)",
    },
    "tesseract.js": {
        "label": "tesseract.js (naptha/tesseract.js, WASM)",
        "licence": "Apache-2.0",
        "licence_route": "adapt-with-credit",
        "role": "candidate",
        "probe": lambda: _node_probe("tesseract.js"),
        "first_run_downloads": "WASM core + eng.traineddata "
                               "fetched at install/runtime by "
                               "default",
        "notes": "browser/WASM route; the separate Lens-surface "
                 "build item owns its UI integration",
    },
    "ocrmypdf": {
        "label": "OCRmyPDF (CLI pipeline over tesseract)",
        "licence": "MPL-2.0",
        "licence_route": "ideas-only (interface; no code "
                         "adapted — the wiki_preocr.py "
                         "precedent)",
        "role": "candidate",
        "probe": lambda: _binary_probe("ocrmypdf"),
        "first_run_downloads": None,
        "notes": "would also need the tesseract binary it "
                 "drives; produces a text layer, confidences "
                 "come from tesseract's own output",
    },
    "docling": {
        "label": "Docling OCR path (docling-project/docling)",
        "licence": "MIT",
        "licence_route": "adapt-with-credit",
        "role": "candidate",
        "probe": lambda: _module_probe(["docling"]),
        "first_run_downloads": "torch + model weights "
                               "(hundreds of MB) on first use",
        "notes": "registered as a document engine in "
                 "wiki_convert_engines.py; its OCR is the "
                 "document-engine lane's designed answer for "
                 "scanned pages — cross-referenced, not "
                 "duplicated, here",
    },
    "template-matcher": {
        "label": "Template matcher (this project's reference "
                 "recognizer)",
        "licence": "this project's own code",
        "licence_route": "native",
        "role": "reference — calibration only, NOT a corpus "
                "engine",
        "probe": _matcher_probe,
        "first_run_downloads": None,
        "notes": "same-font glyph template matching (DejaVu "
                 "Sans 40px templates); exists to exercise the "
                 "measurement pipeline end to end with genuine "
                 "recognition errors and confidences",
    },
}


def probe_engine(name):
    spec = ENGINES[name]
    rec = {k: v for k, v in spec.items() if k != "probe"}
    rec["name"] = name
    rec["probe"] = spec["probe"]()
    return rec


def probe_all():
    return {name: probe_engine(name) for name in ENGINES}


class EngineUnavailable(Exception):
    """Carries the engine's probe record so the caller doors
    the request with the blocker named, never a silent skip."""

    def __init__(self, engine_record):
        self.engine = engine_record
        super().__init__(
            f"engine {engine_record['name']!r} unavailable: "
            f"{engine_record['probe']['blocker']}")


# -------------------------------------------------------------- metrics

def edit_distance(a, b):
    """Levenshtein distance over sequences (chars or words)."""
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _collapse(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def char_error_rate(truth, hyp):
    t, h = _collapse(truth), _collapse(hyp)
    if not t:
        return 0.0 if not h else 1.0
    return round(edit_distance(t, h) / len(t), 4)


def align_words(truth_words, hyp_words):
    """Word-level alignment by edit DP. Returns a list of
    (truth_word|None, hyp_word|None, correct) triples."""
    n, m = len(truth_words), len(hyp_words)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i
    for j in range(1, m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = min(
                dp[i - 1][j] + 1, dp[i][j - 1] + 1,
                dp[i - 1][j - 1]
                + (truth_words[i - 1] != hyp_words[j - 1]))
    pairs = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] \
                + (truth_words[i - 1] != hyp_words[j - 1]):
            pairs.append((truth_words[i - 1], hyp_words[j - 1],
                          truth_words[i - 1] == hyp_words[j - 1]))
            i, j = i - 1, j - 1
        elif j > 0 and dp[i][j] == dp[i][j - 1] + 1:
            pairs.append((None, hyp_words[j - 1], False))
            j -= 1
        else:
            pairs.append((truth_words[i - 1], None, False))
            i -= 1
    return pairs[::-1]


def word_error_rate(truth, hyp):
    tw, hw = _collapse(truth).split(), _collapse(hyp).split()
    if not tw:
        return 0.0 if not hw else 1.0
    return round(edit_distance(tw, hw) / len(tw), 4)


def confidence_report(truth_text, words):
    """Confidence honesty for one run. `words` is the engine's
    own [{text, confidence}] list, confidences exactly as
    emitted. Word correctness comes from aligning the emitted
    words to the ground-truth words."""
    tw = _collapse(truth_text).split()
    hw = [w["text"] for w in words]
    pairs = align_words(tw, hw)
    hyp_pairs = [p for p in pairs if p[1] is not None]
    conf_of = {}
    for idx, w in enumerate(words):
        conf_of[idx] = w.get("confidence")
    correct_conf, wrong_conf = [], []
    hi = 0
    for k, (_t, h, ok) in enumerate(hyp_pairs):
        c = conf_of.get(hi)
        hi += 1
        if isinstance(c, (int, float)):
            (correct_conf if ok else wrong_conf).append(c)
    all_conf = [w["confidence"] for w in words
                if isinstance(w.get("confidence"), (int, float))]
    accuracy = (sum(1 for p in pairs if p[2]) / len(tw)) if tw \
        else 0.0
    mean_conf = (sum(all_conf) / len(all_conf)) if all_conf \
        else None
    return {
        "words_emitted": len(words),
        "words_with_confidence": len(all_conf),
        "mean_word_confidence":
            round(mean_conf, 4) if mean_conf is not None else None,
        "word_accuracy": round(accuracy, 4),
        "calibration_gap_mean_conf_minus_accuracy":
            round(mean_conf - accuracy, 4)
            if mean_conf is not None else None,
        "share_below_queue_threshold": (
            round(sum(1 for c in all_conf
                      if c < CONFIDENCE_THRESHOLD)
                  / len(all_conf), 4) if all_conf else None),
        "queue_threshold": CONFIDENCE_THRESHOLD,
        "mean_confidence_correct_words":
            round(sum(correct_conf) / len(correct_conf), 4)
            if correct_conf else None,
        "mean_confidence_wrong_words":
            round(sum(wrong_conf) / len(wrong_conf), 4)
            if wrong_conf else None,
    }


# ------------------------------------------------------------- fixtures
# Synthetic scanned pages: ground truth known by construction.
# Labelled synthetic in every record they feed.

FIXTURE_LINES = [
    "The quick brown fox jumps over the lazy dog.",
    "Muttoo Home School keeps every page in the register.",
    "Confidence 0.90 is the threshold; unknown queues too!",
]
FIXTURE_TEXT = "\n".join(FIXTURE_LINES)

CHARSET = "".join(sorted(set(
    FIXTURE_TEXT
    + "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    + "0123456789 .,;:!?'-()")))

# kind -> (font, px, ink, degradation) — degradation applied
# after rendering, from a seeded RNG: byte-reproducible.
FIXTURE_KINDS = {
    "clean":       {"font": FONT_DEJAVU, "px": 40, "ink": 0,
                    "degrade": None},
    "noisy":       {"font": FONT_DEJAVU, "px": 40, "ink": 0,
                    "degrade": "noise"},
    "blurred":     {"font": FONT_DEJAVU, "px": 40, "ink": 0,
                    "degrade": "blur"},
    "rotated":     {"font": FONT_DEJAVU, "px": 40, "ink": 0,
                    "degrade": "rotate"},
    "lowcontrast": {"font": FONT_DEJAVU, "px": 40, "ink": 150,
                    "degrade": None},
    "serif":       {"font": FONT_SERIF, "px": 40, "ink": 0,
                    "degrade": None},
    "small":       {"font": FONT_DEJAVU, "px": 22, "ink": 0,
                    "degrade": None},
}


def render_fixture(kind):
    """Returns (PIL.Image, ground_truth_text). Deterministic:
    the noise RNG is seeded per kind."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    spec = FIXTURE_KINDS[kind]
    font = ImageFont.truetype(spec["font"], spec["px"])
    line_h = int(spec["px"] * 1.6)
    img = Image.new("L", (1250, line_h * len(FIXTURE_LINES) + 40),
                    255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(FIXTURE_LINES):
        draw.text((30, 20 + i * line_h), line, font=font,
                  fill=spec["ink"])
    deg = spec["degrade"]
    if deg == "blur":
        img = img.filter(ImageFilter.GaussianBlur(1.3))
    elif deg == "rotate":
        img = img.rotate(2.5, resample=Image.BICUBIC,
                         fillcolor=255)
    elif deg == "noise":
        rng = np.random.RandomState(FIXTURE_SEED + len(kind))
        arr = np.asarray(img).astype(np.float64)
        arr += rng.normal(0, 16, arr.shape)
        sp = rng.random(arr.shape)
        arr[sp < 0.005] = 0
        arr[sp > 0.995] = 255
        img = Image.fromarray(
            np.clip(arr, 0, 255).astype(np.uint8))
    return img, FIXTURE_TEXT


def write_fixtures(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for kind in FIXTURE_KINDS:
        img, truth = render_fixture(kind)
        p = out / f"fixture-{kind}.png"
        img.save(p)
        spec = FIXTURE_KINDS[kind]
        records.append({
            "kind": kind, "file": p.name,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "font": Path(spec["font"]).name, "px": spec["px"],
            "ink": spec["ink"], "degradation": spec["degrade"],
            "ground_truth": truth,
            "synthetic": True,
        })
    (out / "fixtures.json").write_text(
        json.dumps({"fixtures": records,
                    "ground_truth_lines": FIXTURE_LINES,
                    "synthetic": True,
                    "seed": FIXTURE_SEED}, indent=2),
        encoding="utf-8")
    return records


# ------------------------------------------- template-matcher (reference)

_TEMPLATE_PX = 40
_GRID = (16, 24)  # width, height of the normalised glyph grid


def _ink_crop(gray_img, threshold=128):
    """Crop a PIL grayscale image to its ink bounding box;
    returns a float array with ink = 1.0, or None when empty."""
    import numpy as np
    arr = np.asarray(gray_img).astype(np.float64)
    ink = arr < threshold
    if not ink.any():
        return None
    rows = np.where(ink.any(axis=1))[0]
    cols = np.where(ink.any(axis=0))[0]
    return (255.0 - arr[rows[0]:rows[-1] + 1,
                        cols[0]:cols[-1] + 1]) / 255.0


def _grid_vector(crop):
    """Normalise an ink crop onto the fixed grid as a flat
    float vector (ink-positive)."""
    import numpy as np
    from PIL import Image
    img = Image.fromarray(
        (np.clip(crop, 0, 1) * 255).astype(np.uint8))
    img = img.resize(_GRID, Image.BILINEAR)
    return (np.asarray(img).astype(np.float64) / 255.0).ravel()


class TemplateMatcher:
    """Same-font glyph template matching. Templates are rendered
    from DejaVu Sans at _TEMPLATE_PX; recognition segments the
    page into connected components, groups them into lines and
    glyphs, and matches each glyph by normalised cross-
    correlation against the templates. The confidence emitted
    per word is the mean of its glyphs' (ncc+1)/2 scores —
    recorded as emitted, never recalibrated."""

    def __init__(self):
        from PIL import Image, ImageDraw, ImageFont
        self.font = ImageFont.truetype(FONT_DEJAVU, _TEMPLATE_PX)
        self.templates = {}
        for ch in CHARSET:
            if ch == " ":
                continue
            canvas = Image.new("L", (100, 100), 255)
            ImageDraw.Draw(canvas).text((10, 10), ch,
                                        font=self.font, fill=0)
            crop = _ink_crop(canvas)
            if crop is not None:
                self.templates[ch] = _grid_vector(crop)
        self._chars = sorted(self.templates)
        import numpy as np
        mat = np.stack([self.templates[c] for c in self._chars])
        self._mat = mat
        self._mat_c = mat - mat.mean(axis=1, keepdims=True)
        self._mat_n = np.linalg.norm(self._mat_c, axis=1)

    def _match(self, crop):
        import numpy as np
        vec = _grid_vector(crop)
        vc = vec - vec.mean()
        denom = self._mat_n * (np.linalg.norm(vc) or 1.0)
        ncc = np.where(denom > 0,
                       (self._mat_c @ vc) / np.where(
                           denom == 0, 1, denom), -1)
        best = int(np.argmax(ncc))
        return self._chars[best], float(
            min(1.0, max(0.0, (ncc[best] + 1) / 2)))

    def ocr(self, image):
        import numpy as np
        from scipy import ndimage
        gray = np.asarray(image.convert("L")).astype(np.float64)
        lo, hi = float(gray.min()), float(gray.max())
        threshold = (lo + hi) / 2 if hi - lo > 40 else 128.0
        ink = gray < threshold
        structure = np.ones((3, 3), dtype=int)
        labels, n = ndimage.label(ink, structure=structure)
        objects = ndimage.find_objects(labels)
        comps = []
        dropped = 0
        for idx, sl in enumerate(objects, 1):
            if sl is None:
                continue
            area = int((labels[sl] == idx).sum())
            if area < 4:
                dropped += 1
                continue
            comps.append({"r0": sl[0].start, "r1": sl[0].stop,
                          "c0": sl[1].start, "c1": sl[1].stop,
                          "area": area})
        # group components into lines by vertical overlap
        comps.sort(key=lambda c: (c["r0"] + c["r1"]) / 2)
        lines = []
        for comp in comps:
            placed = False
            for line in lines:
                overlap = min(comp["r1"], line["r1"]) \
                    - max(comp["r0"], line["r0"])
                h = min(comp["r1"] - comp["r0"],
                        line["r1"] - line["r0"])
                if h > 0 and overlap > 0.5 * h:
                    line["comps"].append(comp)
                    line["r0"] = min(line["r0"], comp["r0"])
                    line["r1"] = max(line["r1"], comp["r1"])
                    placed = True
                    break
            if not placed:
                lines.append({"r0": comp["r0"], "r1": comp["r1"],
                              "comps": [comp]})
        lines.sort(key=lambda ln: ln["r0"])
        out_lines, out_words = [], []
        for line in lines:
            line_h = line["r1"] - line["r0"]
            cs = sorted(line["comps"], key=lambda c: c["c0"])
            # merge vertically stacked parts of one glyph
            # (i/j dots, ':' ';' '!' bodies)
            glyphs = []
            for comp in cs:
                merged = False
                for g in glyphs:
                    xover = min(comp["c1"], g["c1"]) \
                        - max(comp["c0"], g["c0"])
                    narrow = min(comp["c1"] - comp["c0"],
                                 g["c1"] - g["c0"])
                    vgap = max(comp["r0"], g["r0"]) \
                        - min(comp["r1"], g["r1"])
                    if narrow > 0 and xover > 0.6 * narrow \
                            and vgap < 0.35 * line_h:
                        g["r0"] = min(g["r0"], comp["r0"])
                        g["r1"] = max(g["r1"], comp["r1"])
                        g["c0"] = min(g["c0"], comp["c0"])
                        g["c1"] = max(g["c1"], comp["c1"])
                        merged = True
                        break
                if not merged:
                    glyphs.append(dict(comp))
            glyphs.sort(key=lambda g: g["c0"])
            widths = sorted(g["c1"] - g["c0"] for g in glyphs)
            med_w = widths[len(widths) // 2] if widths else 0
            word_gap = max(8.0, 0.5 * med_w)
            words, cur = [], []
            prev = None
            for g in glyphs:
                crop = (255.0 - gray[g["r0"]:g["r1"],
                                     g["c0"]:g["c1"]]) / 255.0
                ch, conf = self._match(crop)
                if prev is not None \
                        and g["c0"] - prev > word_gap and cur:
                    words.append(cur)
                    cur = []
                cur.append((ch, conf))
                prev = g["c1"]
            if cur:
                words.append(cur)
            line_text = []
            for w in words:
                text = "".join(ch for ch, _c in w)
                conf = sum(c for _ch, c in w) / len(w)
                line_text.append(text)
                out_words.append(
                    {"text": text, "confidence": round(conf, 4)})
            out_lines.append(" ".join(line_text))
        return {"text": "\n".join(out_lines), "words": out_words,
                "components_dropped_as_specks": dropped,
                "lines": len(out_lines)}


_MATCHER = None


def _get_matcher():
    global _MATCHER
    if _MATCHER is None:
        _MATCHER = TemplateMatcher()
    return _MATCHER


# ------------------------------------------------------------------ runs

def run_engine(name, image):
    """Run engine NAME over a PIL image. Returns the result
    dict (text, words, engine detail). Raises EngineUnavailable
    with the probe record when the engine cannot run here —
    for the real candidates that is the only path tonight, and
    it is a result, not a failure of the harness."""
    rec = probe_engine(name)
    if not rec["probe"]["available"]:
        raise EngineUnavailable(rec)
    if name == "template-matcher":
        return _get_matcher().ocr(image)
    # Every other engine that ever passes its probe gains its
    # adapter here, against its public API, the day it is
    # installed. No adapter exists for an engine this module
    # has not measured; claiming one would be fabrication.
    raise EngineUnavailable(rec)


def trial_run(engine_name, image, truth, fixture_kind):
    """One measured run: image+text paired output + metrics."""
    started = time.perf_counter()
    try:
        result = run_engine(engine_name, image)
    except EngineUnavailable as exc:
        return {"engine": engine_name, "fixture": fixture_kind,
                "available": False,
                "blocker": exc.engine["probe"]["blocker"],
                "wall_seconds": round(
                    time.perf_counter() - started, 4)}
    wall = round(time.perf_counter() - started, 4)
    words = result.get("words") or [
        {"text": w, "confidence": None}
        for w in _collapse(result["text"]).split()]
    return {
        "engine": engine_name, "fixture": fixture_kind,
        "available": True, "wall_seconds": wall,
        "text": result["text"], "words": words,
        "cer": char_error_rate(truth, result["text"]),
        "wer": word_error_rate(truth, result["text"]),
        "confidence": confidence_report(truth, words),
        "detail": {k: v for k, v in result.items()
                   if k not in ("text", "words")},
    }


def run_trials(engine_names=None, fixture_kinds=None):
    """The full trial: probes, fixtures rendered in memory,
    every engine over every fixture. Returns the record."""
    names = engine_names or list(ENGINES)
    kinds = fixture_kinds or list(FIXTURE_KINDS)
    runs = []
    for kind in kinds:
        image, truth = render_fixture(kind)
        for name in names:
            runs.append(trial_run(name, image, truth, kind))
    return {
        "kind": "ocr-engine-trials",
        "date": TRIAL_DATE,
        "synthetic_fixtures": True,
        "ground_truth": FIXTURE_TEXT,
        "metric_notes": "CER/WER over whitespace-collapsed "
                        "text, case-sensitive; confidences "
                        "exactly as emitted, never "
                        "recalibrated; wall time is this "
                        "machine, this run",
        "engines": probe_all(),
        "runs": runs,
    }


# ------------------------------------------------------- preocr adapter

def make_preocr_stage(engine_name):
    """A scripts/wiki_preocr.py stage callable for ENGINE_NAME:
    path -> (text, mean word confidence). An unavailable engine
    raises wiki_preocr.OcrUnavailable carrying the verbatim
    blocker — the seam's clean refusal."""
    import wiki_preocr as wpo
    from PIL import Image

    def stage(path):
        rec = probe_engine(engine_name)
        if not rec["probe"]["available"]:
            raise wpo.OcrUnavailable(
                f"OCR engine {engine_name!r} unavailable: "
                f"{rec['probe']['blocker']}")
        try:
            result = run_engine(engine_name, Image.open(path))
        except EngineUnavailable as exc:
            raise wpo.OcrUnavailable(
                f"OCR engine {engine_name!r} unavailable: "
                f"{exc.engine['probe']['blocker']}")
        words = result.get("words") or []
        confs = [w["confidence"] for w in words
                 if isinstance(w.get("confidence"), (int, float))]
        confidence = (sum(confs) / len(confs)) if confs else 0.0
        return result["text"], confidence

    return stage


# ------------------------------------------------------------ measure-pdf

def measure_pdf(path):
    """Read-only measurement of a PDF for the OCR queue's
    sake: what its embedded text layer holds (the incumbent
    extraction for ocr-0001), and whether its pages carry
    images at all. Nothing is written anywhere; a PDF with no
    text layer would be the OCR candidate — this one is
    measured, not processed."""
    p = Path(path)
    out = {"file": str(p), "bytes": p.stat().st_size,
           "read_only": True}
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(p))
        per_page, images = [], 0
        for page in reader.pages:
            per_page.append(len(page.extract_text() or ""))
            try:
                res = page.get("/Resources") or {}
                xobj = res.get("/XObject") or {}
                for key in xobj:
                    obj = xobj[key].get_object()
                    if obj.get("/Subtype") == "/Image":
                        images += 1
            except Exception:
                pass
        out["extractor"] = "pypdf (this interpreter)"
        out["pages"] = len(reader.pages)
        out["per_page_chars"] = per_page
        out["total_chars"] = sum(per_page)
        out["image_xobjects"] = images
    except Exception as exc:
        out["extractor"] = None
        out["pypdf_blocker"] = f"{type(exc).__name__}: {exc}"
        if shutil.which("pdftotext"):
            proc = subprocess.run(
                ["pdftotext", str(p), "-"], capture_output=True,
                text=True, timeout=120)
            out["extractor"] = "poppler pdftotext (cross-check)"
            out["total_chars"] = len(proc.stdout)
            out["pages"] = proc.stdout.count("\f")
    return out


# ------------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("fixtures")
    p.add_argument("--out", required=True)
    p = sub.add_parser("run")
    p.add_argument("--fixtures", default=None,
                   help="accepted for symmetry; fixtures are "
                        "rendered in memory from the seeded "
                        "generator either way")
    p.add_argument("--engine", action="append", default=None)
    p.add_argument("--out", default=None)
    p = sub.add_parser("measure-pdf")
    p.add_argument("path")
    p.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "probe":
        probes = probe_all()
        if args.json:
            print(json.dumps(probes, indent=2))
        else:
            for name, rec in probes.items():
                state = "AVAILABLE" if rec["probe"]["available"] \
                    else f"DOORED — {rec['probe']['blocker']}"
                print(f"{name:16s} [{rec['licence_route']}] "
                      f"{state}")
        return 0
    if args.cmd == "fixtures":
        records = write_fixtures(args.out)
        print(f"wrote {len(records)} synthetic fixtures to "
              f"{args.out} (ground truth in fixtures.json)")
        return 0
    if args.cmd == "run":
        record = run_trials(args.engine)
        if args.out:
            Path(args.out).write_text(
                json.dumps(record, indent=2), encoding="utf-8")
            print(f"record written to {args.out}")
        else:
            print(json.dumps(record, indent=2))
        return 0
    if args.cmd == "measure-pdf":
        result = measure_pdf(args.path)
        print(json.dumps(result, indent=2) if args.json
              else result)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
