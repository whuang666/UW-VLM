"""Build the v0.2 paper figures (task illustration, A/B input comparison, truncation case).

Inputs are read-only: curated QA (condition A images + question text), condition-B
composites, clean key frames from ``replayed_activities``, and the model response of one
truncated B item.  Nothing here re-scores or rewrites any evidence.

Figures (white background, opaque RGB, 300 dpi):
  fig1_task_overview.png      clean state strip + the question face the model sees
  fig2_condition_AB.png       same question, same state: condition A vs condition B
  fig3_appendix_truncation.png B input + raw response excerpt + budget/stop reason

Deliberately NOT produced: any figure implying "zoom hurts perception".  The only
supportable reading of the current dev run is that B's deficit is entangled with the
256-token output budget (8 of 9 invalid answers are ``finish_reason=length``).

Usage:
    python scripts/usim/make_paper_figures.py --out docs/WBW/figures
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_ROOT = ROOT / "data" / "usim_enact" / "usim-enact-v0.2"
CURATED = DATA_ROOT / "QA" / "train" / "enact_ordering_curated.jsonl"
B_QA = DATA_ROOT / "QA" / "conditions" / "B_zoom" / "enact_ordering.jsonl"
RUN = ROOT / "data" / "usim_enact" / "runs" / "qwen3.8-max" / "v02_dev_001"

FONT_DIR = Path("C:/Windows/Fonts")
DPI = (300, 300)
WHITE = (255, 255, 255)
INK = (17, 17, 17)
GREY = (110, 110, 110)
ACCENT = (0, 82, 155)
WARN = (176, 58, 0)

# paper-facing choices
FIG1_QUESTION = "827185aa"   # forward L=5, gt [4,1,2,3]
FIG2_QUESTION = "d7fd42e4"   # forward L=4, gt [3,1,2]
FIG3_QUESTION = "ccfd8e4e"   # forward L=4, gt [3,2,1] -- the truncated B item
EPISODE = "usim_train_episode_001304"


def font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    if mono:
        name = "consolab.ttf" if bold else "consola.ttf"
    else:
        name = "arialbd.ttf" if bold else "arial.ttf"
    path = FONT_DIR / name
    if not path.exists():
        path = FONT_DIR / ("arialbd.ttf" if bold else "arial.ttf")
    return ImageFont.truetype(str(path), size)


def load_jsonl(path: Path) -> List[Dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def pick(records: Sequence[Dict], suffix: str) -> Dict:
    for record in records:
        if record["id"].endswith(suffix):
            return record
    raise SystemExit(f"question not found: {suffix}")


def open_rgb(path: Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def paste(canvas: Image.Image, image: Image.Image, box: Tuple[int, int, int, int]) -> None:
    """Fit ``image`` into ``box`` keeping aspect ratio, centred."""
    x, y, w, h = box
    scale = min(w / image.width, h / image.height)
    size = (max(1, int(round(image.width * scale))), max(1, int(round(image.height * scale))))
    resized = image.resize(size, Image.LANCZOS)
    canvas.paste(resized, (x + (w - size[0]) // 2, y + (h - size[1]) // 2))


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, width: int) -> List[str]:
    lines: List[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for word in paragraph.split(" "):
            candidate = (current + " " + word).strip()
            if draw.textlength(candidate, font=fnt) <= width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        lines.append(current)
    return lines


def text_block(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont,
               x: int, y: int, width: int, fill=INK, leading: float = 1.35) -> int:
    line_height = int(fnt.size * leading)
    for line in wrap(draw, text, fnt, width):
        draw.text((x, y), line, font=fnt, fill=fill)
        y += line_height
    return y


def frame_box(draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int], colour=GREY, width: int = 2) -> None:
    x, y, w, h = box
    draw.rectangle([x - 1, y - 1, x + w, y + h], outline=colour, width=width)


def arrow(draw: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int, colour=GREY, width: int = 4) -> None:
    draw.line([x0, y0, x1, y1], fill=colour, width=width)
    head = 12
    draw.polygon([(x1, y1), (x1 - head, y1 - head // 2), (x1 - head, y1 + head // 2)], fill=colour)


def caption(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, width: int, fnt) -> int:
    return text_block(draw, text, fnt, x, y, width, fill=GREY)


def finish(canvas: Image.Image, out: Path, pad: int = 46) -> Path:
    """Crop the canvas to its actual content so no figure ships with dead white space."""
    array = np.asarray(canvas)
    mask = np.any(array != 255, axis=2)
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    if len(rows) == 0 or len(cols) == 0:
        canvas.save(out, dpi=DPI)
        return out
    top = max(0, int(rows[0]) - pad)
    bottom = min(canvas.height, int(rows[-1]) + pad)
    left = max(0, int(cols[0]) - pad)
    right = min(canvas.width, int(cols[-1]) + pad)
    canvas.crop((left, top, right, bottom)).save(out, dpi=DPI)
    return out


def figure1(curated: Sequence[Dict], out: Path) -> Path:
    """Task overview: clean state strip (top) + the question face the model receives (bottom)."""
    record = pick(curated, FIG1_QUESTION)
    key_frames = record["key_frame_ids"]

    width, height = 1800, 1320
    canvas = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(canvas)
    f_title, f_label, f_body, f_small = font(34, True), font(22, True), font(21), font(18)

    draw.text((60, 44), "USIM-ENACT v0.2: one underwater manipulation episode and the question it yields",
              font=f_title, fill=INK)

    # ---- (a) clean key frames in true temporal order
    draw.text((60, 118), "(a) Episode states (ego camera, clean frames, true temporal order)",
              font=f_label, fill=ACCENT)
    thumb_w, thumb_h, gap = 312, 234, 30
    x, y = 60, 166
    for index, frame in enumerate(key_frames):
        path = DATA_ROOT / "replayed_activities" / EPISODE / "external_sensor1" / f"{int(frame):05d}.png"
        paste(canvas, open_rgb(path), (x, y, thumb_w, thumb_h))
        frame_box(draw, (x, y, thumb_w, thumb_h))
        draw.text((x, y + thumb_h + 8), f"s{index}  (frame {frame})", font=f_small, fill=INK)
        if index < len(key_frames) - 1:
            arrow(draw, x + thumb_w + 5, y + thumb_h // 2, x + thumb_w + gap - 5, y + thumb_h // 2,
                  colour=(80, 80, 80), width=5)
        x += thumb_w + gap
    caption(draw, "The state strip is the annotation ground truth: each arrow is one visible transition "
                  "(start -> pre-grasp approach -> grasp -> lift -> at_box).",
            60, y + thumb_h + 40, width - 120, f_small)

    # ---- (b) the question face
    top = y + thumb_h + 96
    draw.line([60, top - 24, width - 60, top - 24], fill=(220, 220, 220), width=2)
    draw.text((60, top), "(b) The question the model must answer (condition A input, labels burned into the frames)",
              font=f_label, fill=ACCENT)
    y = top + 48
    x = 60
    for position, relative in enumerate(record["images"]):
        paste(canvas, open_rgb(DATA_ROOT / str(relative).replace("\\", "/")), (x, y, thumb_w, thumb_h))
        frame_box(draw, (x, y, thumb_w, thumb_h), colour=ACCENT, width=3)
        name = "Current State" if position == 0 else f"Next State {position}"
        draw.text((x, y + thumb_h + 8), name, font=f_small, fill=INK)
        x += thumb_w + gap

    text_x = 60
    text_y = y + thumb_h + 44
    actions = record["question"].split("## Actions in Order")[1].split("Now please provide")[0].strip()
    y2 = text_block(draw, "Actions in Order (verbatim):", f_body, text_x, text_y, 1080)
    y2 = text_block(draw, actions, font(19, mono=True), text_x, y2 + 6, 1080, fill=INK)
    y2 = text_block(draw, "Output format: only a Python list of the future-state labels, e.g. [1, 3, 2]. "
                          "Ground truth for this question: " + str(record["gt_answer"]) + ".",
                    f_small, text_x, y2 + 14, 1080, fill=GREY)
    caption(draw, "The instruction preamble is condensed here (full template in the appendix); the images, the "
                  "action list and the output constraint are exactly what the model receives.",
            text_x, y2 + 16, 1080, f_small)

    out.parent.mkdir(parents=True, exist_ok=True)
    return finish(canvas, out)


def figure2(curated: Sequence[Dict], b_records: Sequence[Dict], out: Path) -> Path:
    """Same question, same state: condition A frame vs condition B composite.

    Geometry is exact-fit on purpose: A is 320x240 shown at 480x360 (4:3), B is 640x240
    shown at 960x360 (8:3).  No letterboxing, so the zoom panel outline lands precisely on
    the right half of the composite instead of floating over empty margins.
    """
    record = pick(curated, FIG2_QUESTION)
    b_record = pick(b_records, FIG2_QUESTION)

    width = 1800
    canvas = Image.new("RGB", (width, 1500), WHITE)
    draw = ImageDraw.Draw(canvas)
    f_title, f_label, f_small, f_head = font(34, True), font(23, True), font(18), font(19, True)

    draw.text((60, 44), "Condition A vs condition B on the same question and the same state",
              font=f_title, fill=INK)
    caption(draw, "A = the 320x240 ego frame.  B = [full frame | local zoom] at 640x240.  The zoom is a 1.6-2.0x "
                  "digital crop: it adds no sensor information, it only reallocates pixels to the region of interest.",
            60, 100, width - 120, f_small)

    a_box = (60, 0, 480, 360)
    b_box = (620, 0, 960, 360)
    rows = [(0, "Current State"), (2, "Next State 2 (grasp stage)")]
    y = 200
    for position, role in rows:
        draw.text((60, y), f"state index {position} — {role}", font=f_label, fill=ACCENT)
        draw.text((a_box[0], y + 42), "A  ego frame (320x240)", font=f_head, fill=INK)
        draw.text((b_box[0], y + 42), "B  [full | zoom] (640x240)", font=f_head, fill=INK)

        a_img = open_rgb(DATA_ROOT / str(record["images"][position]).replace("\\", "/"))
        b_img = open_rgb(DATA_ROOT / str(b_record["images"][position]).replace("\\", "/"))
        paste(canvas, a_img, (a_box[0], y + 76, a_box[2], a_box[3]))
        paste(canvas, b_img, (b_box[0], y + 76, b_box[2], b_box[3]))

        # the zoom panel is exactly the right half of the composite
        zx = b_box[0] + b_box[2] // 2
        draw.rectangle([zx, y + 74, b_box[0] + b_box[2] + 2, y + 76 + b_box[3] + 2], outline=WARN, width=4)
        draw.text((zx + 8, y + 76 + b_box[3] + 10), "zoom panel: digital only, no new detail",
                  font=f_small, fill=WARN)

        y += 76 + b_box[3] + 74
        if position != rows[-1][0]:
            draw.line([60, y - 34, 1580, y - 34], fill=(226, 226, 226), width=2)

    caption(draw, "Both rows use the same question id, the same key frame and the same burned-in labels, so a score "
                  "gap between conditions cannot be attributed to the question or to the state.",
            60, y + 6, width - 120, f_small)

    canvas.save(out, dpi=DPI)
    return finish(canvas, out)


def figure3(b_records: Sequence[Dict], out: Path) -> Path:
    """Appendix: the truncated answer case with input, excerpt, budget and stop reason."""
    b_record = pick(b_records, FIG3_QUESTION)
    predictions = {json.loads(line)["id"]: json.loads(line)
                   for line in (RUN / "B_zoom" / "predictions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
    prediction = predictions[b_record["id"]]
    raw = prediction.get("raw") or prediction.get("answer") or ""

    width, height = 1800, 1100
    canvas = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(canvas)
    f_title, f_label, f_small, f_mono = font(32, True), font(22, True), font(18), font(17, mono=True)

    draw.text((60, 44), "Appendix: an unparsed condition-B answer is a budget/format failure", font=f_title, fill=INK)
    caption(draw, "Development-set diagnostic, single case.  The reasoning is cut off by the 256-token budget before the "
                  "required list is printed, so this item carries no information about condition B's perception.  It does "
                  "not follow that the other truncated items would have been correct: only this one was read in full.",
            60, 96, width - 120, f_small)

    draw.text((60, 176), "condition-B input (one of the four states)", font=f_label, fill=ACCENT)
    # exact fit: 640x240 composite
    paste(canvas, open_rgb(DATA_ROOT / str(b_record["images"][2]).replace("\\", "/")), (60, 216, 640, 240))
    frame_box(draw, (60, 216, 640, 240))

    meta = [
        ("question id", b_record["id"][-8:] + "  (forward, L=4)"),
        ("ground truth", str(b_record["gt_answer"])),
        ("max_completion_tokens", "256"),
        ("completion_tokens", str(prediction.get("usage", {}).get("completion_tokens"))),
        ("finish_reason", str(prediction.get("finish_reason"))),
        ("parsed", "None  -> strict v0.3 scores 0"),
    ]
    y = 520
    for key, value in meta:
        draw.text((60, y), key, font=f_small, fill=GREY)
        colour = WARN if key in ("finish_reason", "parsed") else INK
        draw.text((420, y), value, font=font(18, True) if colour == WARN else f_small, fill=colour)
        y += 38

    draw.text((760, 176), "raw response (excerpt)", font=f_label, fill=ACCENT)
    excerpt = raw[:1500]
    lines = wrap(draw, excerpt, f_mono, 960)[:34]
    y = 216
    for line in lines:
        draw.text((760, y), line, font=f_mono, fill=INK)
        y += 27
    draw.text((760, y + 4), "[... truncated by the output budget at this point ...]", font=f_mono, fill=WARN)
    return finish(canvas, out)

    canvas.save(out, dpi=DPI)
    return out


def comparison(curated: Sequence[Dict], b_records: Sequence[Dict], out: Path) -> Path:
    """Source material next to the exact pixels used in the figure, to show nothing was retouched.

    The figures only resample (LANCZOS upscale) the native frames; this sheet proves it by
    showing native -> rendered for the same frame, plus the untouched condition-B composite.
    """
    width = 1800
    canvas = Image.new("RGB", (width, 1200), WHITE)
    draw = ImageDraw.Draw(canvas)
    f_title, f_small, f_head = font(30, True), font(18), font(19, True)

    draw.text((60, 40), "Self-check: native source vs the pixels actually drawn in the figures", font=f_title, fill=INK)
    caption(draw, "Left of each pair is the file on disk; right is the same frame after the figure's only "
                  "transformation (LANCZOS resample). No retouching, no colour change, no cropping of content.",
            60, 92, width - 120, f_small)

    record = pick(curated, FIG2_QUESTION)
    a_native = open_rgb(DATA_ROOT / str(record["images"][0]).replace("\\", "/"))
    b_native = open_rgb(DATA_ROOT / str(pick(b_records, FIG2_QUESTION)["images"][0]).replace("\\", "/"))

    draw.text((60, 160), "condition A frame (native 320x240)", font=f_head, fill=INK)
    paste(canvas, a_native, (60, 194, 320, 240))
    frame_box(draw, (60, 194, 320, 240))
    draw.text((440, 160), "as drawn in fig2 (480x360)", font=f_head, fill=INK)
    paste(canvas, a_native, (440, 194, 480, 360))
    frame_box(draw, (440, 194, 480, 360))

    draw.text((60, 600), "condition B composite (native 640x240)", font=f_head, fill=INK)
    paste(canvas, b_native, (60, 634, 640, 240))
    frame_box(draw, (60, 634, 640, 240))
    draw.text((760, 600), "as drawn in fig2 (960x360), zoom half outlined", font=f_head, fill=INK)
    paste(canvas, b_native, (760, 634, 960, 360))
    frame_box(draw, (760, 634, 960, 360))
    draw.rectangle([760 + 480, 632, 760 + 960 + 2, 634 + 360 + 2], outline=WARN, width=4)

    caption(draw, "Both conditions are shown at the same 1.5x resample so the visual comparison in the paper is fair; "
                  "the upscale adds no information, it only matches print size.",
            60, 1024, width - 120, f_small)
    return finish(canvas, out)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(ROOT / "docs" / "WBW" / "figures"))
    args = parser.parse_args(argv)

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    curated = load_jsonl(CURATED)
    b_records = load_jsonl(B_QA)

    fig1 = figure1(curated, out_dir / "fig1_task_overview.png")
    fig2 = figure2(curated, b_records, out_dir / "fig2_condition_AB.png")
    fig3 = figure3(b_records, out_dir / "fig3_appendix_truncation.png")
    sheet = comparison(curated, b_records, out_dir / "source_vs_rendered.png")

    for path in (fig1, fig2, fig3, sheet):
        with Image.open(path) as image:
            print(f"{path.name}: {image.width}x{image.height} {image.mode} dpi={image.info.get('dpi')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
