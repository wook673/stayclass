#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""report_shots.py - Render a report HTML into JPGs (full body + 2-way split + cover).

Uses Playwright (Edge channel) for rendering and Pillow for cropping.

CLI
---
    python routine/report_shots.py <report.html> --out-dir <dir> --prefix <name>
        [--cover cover.html] [--width 1280] [--quality 88]
        [--boundary-label 04] [--no-split] [--dry-run]

Outputs (into --out-dir):
    <prefix>.jpg           full body, single image (kept - used for the PDF)
    <prefix>_1.jpg         body page 1/2  (0 .. crop line)
    <prefix>_2.jpg         body page 2/2  (crop line .. bottom)
    <prefix>_0_표지.jpg    cover, when --cover is given
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

from PIL import Image

# --------------------------------------------------------------------------
# Browser launch
# --------------------------------------------------------------------------

EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

# JS evaluated in the page to collect section-boundary geometry.
# Coordinates are ABSOLUTE document pixels (rect + window.scrollY / scrollX).
_JS_BOUNDARIES = r"""
() => {
  const abs = (el) => {
    const r = el.getBoundingClientRect();
    return {
      top: Math.round(r.top + window.scrollY),
      bottom: Math.round(r.bottom + window.scrollY),
    };
  };

  // Walk up from a `.sec-num` to the nearest sensible block ancestor so that the
  // section heading starts a page cleanly (picks up the section's top padding /
  // border). Never climb into an ancestor that already contains another
  // `.sec-num`, because a single <section> may hold several numbered blocks.
  const blockAncestor = (numEl) => {
    let cand = numEl.closest('.sec-head') || numEl;
    let p = cand.parentElement;
    while (p && p !== document.body && p !== document.documentElement) {
      if (p.querySelectorAll('.sec-num').length !== 1) break;
      if (abs(p).top >= abs(cand).top) { cand = p; p = p.parentElement; continue; }
      cand = p;
      p = p.parentElement;
    }
    return cand;
  };

  const out = [];

  document.querySelectorAll('.sec-num').forEach((numEl) => {
    const host = blockAncestor(numEl);
    const g = abs(host);
    out.push({
      kind: 'sec-num',
      label: (numEl.textContent || '').trim(),
      top: g.top,
      bottom: g.bottom,
      tag: host.tagName.toLowerCase(),
      cls: host.className || '',
    });
  });

  document.querySelectorAll('section').forEach((sec, i) => {
    const g = abs(sec);
    const numEl = sec.querySelector('.sec-num');
    out.push({
      kind: 'section',
      label: numEl ? (numEl.textContent || '').trim() : String(i),
      top: g.top,
      bottom: g.bottom,
      tag: 'section',
      cls: sec.className || '',
    });
  });

  out.sort((a, b) => (a.top - b.top) || (a.kind === 'sec-num' ? -1 : 1));

  // Scroll box (includes decorative overflow) vs. layout box (the <html>/<body>
  // border box). Pages like cover.html set an exact body size and then bleed a
  // glow past it; the layout box is what we actually want to keep.
  const scrollH = Math.max(
    document.body.scrollHeight, document.documentElement.scrollHeight,
    document.body.offsetHeight, document.documentElement.offsetHeight);
  const scrollW = Math.max(
    document.body.scrollWidth, document.documentElement.scrollWidth);
  const hr = document.documentElement.getBoundingClientRect();
  const br = document.body.getBoundingClientRect();
  const layoutH = Math.round(Math.max(hr.height, br.height));
  const layoutW = Math.round(Math.max(hr.width, br.width));

  return {
    scrollHeight: scrollH,
    scrollWidth: scrollW,
    height: (layoutH > 0 && layoutH < scrollH) ? layoutH : scrollH,
    width: (layoutW > 0 && layoutW < scrollW) ? layoutW : scrollW,
    boundaries: out,
  };
}
"""


def _launch(pw):
    """Launch Chromium/Edge. Returns (browser, how) where `how` describes the config."""
    try:
        return pw.chromium.launch(channel="msedge"), 'channel="msedge"'
    except Exception as exc:  # pragma: no cover - environment dependent
        last = exc
    if Path(EDGE_EXE).exists():
        try:
            return pw.chromium.launch(executable_path=EDGE_EXE), f'executable_path={EDGE_EXE}'
        except Exception as exc:  # pragma: no cover
            last = exc
    raise RuntimeError(f"could not launch a browser for rendering: {last}")


def _file_url(path: Path) -> str:
    return Path(path).resolve().as_uri()


def _render(html_path, width: int, want_png: bool):
    """Open the HTML in a headless browser at `width`.

    Returns (info_dict, png_bytes_or_None). `info_dict` has keys
    height / width / boundaries (see _JS_BOUNDARIES).
    """
    from playwright.sync_api import sync_playwright

    html_path = Path(html_path).resolve()
    with sync_playwright() as pw:
        browser, how = _launch(pw)
        try:
            page = browser.new_page(viewport={"width": width, "height": 1200},
                                    device_scale_factor=1)
            page.goto(_file_url(html_path), wait_until="load")
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(400)
            info = page.evaluate(_JS_BOUNDARIES)
            info["launch"] = how
            png = page.screenshot(full_page=True, type="png") if want_png else None
        finally:
            browser.close()
    return info, png


# --------------------------------------------------------------------------
# Pure logic (browser-free, unit tested)
# --------------------------------------------------------------------------

def choose_crop_line(boundaries, page_height, boundary_label="04"):
    """Pick the y pixel where the body should be cut into two pages.

    `boundaries` is a list of dicts with at least "top" (int) and "label" (str);
    an optional "kind" of "sec-num" is preferred over "section" when both share
    a label.

    Rules, in order:
      1. top of the block whose label == boundary_label (prefer kind "sec-num");
      2. otherwise the boundary nearest to the vertical midpoint of the page,
         searching strictly below the midpoint first;
      3. otherwise (no usable boundary at all) the midpoint itself.

    The result is always clamped to 1 .. page_height-1 so both crops are non-empty.
    """
    page_height = int(page_height)
    mid = page_height // 2

    def clamp(v):
        return max(1, min(int(v), max(1, page_height - 1)))

    items = [b for b in (boundaries or []) if b.get("top") is not None]

    if boundary_label:
        matches = [b for b in items if str(b.get("label", "")).strip() == str(boundary_label)]
        if matches:
            matches.sort(key=lambda b: (b.get("kind") != "sec-num", b["top"]))
            return clamp(matches[0]["top"])

    # Fallback: nearest boundary below the midpoint (exclude 0 / full-height edges).
    inner = [b for b in items if 0 < int(b["top"]) < page_height]
    below = [b for b in inner if int(b["top"]) >= mid]
    if below:
        return clamp(min(below, key=lambda b: int(b["top"])) ["top"])
    if inner:
        return clamp(max(inner, key=lambda b: int(b["top"]))["top"])
    return clamp(mid)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def _save_jpg(img: Image.Image, out_path, quality: int) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.save(out_path, "JPEG", quality=quality, subsampling=0, optimize=True)
    return out_path


def _to_image(png: bytes, info: dict) -> Image.Image:
    """Decode the full-page PNG and trim decorative overflow outside the layout box."""
    img = Image.open(io.BytesIO(png)).convert("RGB")
    w = min(img.width, int(info.get("width") or img.width) or img.width)
    h = min(img.height, int(info.get("height") or img.height) or img.height)
    if (w, h) != img.size and w > 0 and h > 0:
        img = img.crop((0, 0, w, h))
    return img


def capture_full(html_path, out_jpg, width=1280, quality=88) -> Path:
    """Full-page screenshot of one HTML file into a single JPG. Returns the path."""
    info, png = _render(html_path, width, want_png=True)
    return _save_jpg(_to_image(png, info), out_jpg, quality)


def split_points(html_path, width=1280) -> list:
    """Section boundary info from the rendered DOM.

    Returns [{"index":0,"label":"03","top":123,"bottom":4567,"kind":...,
              "tag":...,"cls":...}, ...] in document order. Coordinates are
    absolute document pixels at the given render width.
    """
    info, _ = _render(html_path, width, want_png=False)
    out = []
    for i, b in enumerate(info["boundaries"]):
        out.append({
            "index": i,
            "label": b["label"],
            "top": b["top"],
            "bottom": b["bottom"],
            "kind": b["kind"],
            "tag": b["tag"],
            "cls": b["cls"],
        })
    return out


def capture_split(html_path, out_prefix, width=1280, quality=88,
                  boundary_label="04") -> list:
    """Render `html_path` and crop it into exactly two JPGs at a block boundary.

    Writes <out_prefix>_1.jpg (0..line) and <out_prefix>_2.jpg (line..height).
    The cut line is a block top edge, so no content is bisected.
    Returns [path1, path2].
    """
    info, png = _render(html_path, width, want_png=True)
    out_prefix = Path(out_prefix)
    img = _to_image(png, info)  # the full capture stays in memory
    w, h = img.size
    scale = h / info["height"] if info["height"] else 1.0
    line = choose_crop_line(info["boundaries"], info["height"], boundary_label)
    line_px = max(1, min(int(round(line * scale)), h - 1))
    p1 = _save_jpg(img.crop((0, 0, w, line_px)),
                   out_prefix.with_name(out_prefix.name + "_1.jpg"), quality)
    p2 = _save_jpg(img.crop((0, line_px, w, h)),
                   out_prefix.with_name(out_prefix.name + "_2.jpg"), quality)
    return [p1, p2]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _report(path: Path) -> None:
    with Image.open(path) as im:
        w, h = im.size
    kb = path.stat().st_size / 1024
    print(f"[wrote] {path}  {w}x{h}  {kb:.0f} KB")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render a report HTML into JPGs.")
    ap.add_argument("report", help="path to the report HTML")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--cover", default=None, help="optional cover HTML")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--quality", type=int, default=88)
    ap.add_argument("--boundary-label", default="04")
    ap.add_argument("--no-split", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="print split_points() as JSON, write nothing")
    args = ap.parse_args(argv)

    report = Path(args.report).resolve()
    if not report.exists():
        print(f"ERROR: no such report: {report}", file=sys.stderr)
        return 2

    if args.dry_run:
        pts = split_points(report, width=args.width)
        sys.stdout.write(json.dumps(pts, ensure_ascii=False, indent=2) + "\n")
        return 0

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    if args.cover:
        cover = Path(args.cover).resolve()
        if not cover.exists():
            print(f"ERROR: no such cover: {cover}", file=sys.stderr)
            return 2
        written.append(capture_full(cover, out_dir / f"{args.prefix}_0_표지.jpg",
                                    width=args.width, quality=args.quality))

    written.append(capture_full(report, out_dir / f"{args.prefix}.jpg",
                                width=args.width, quality=args.quality))

    if not args.no_split:
        written.extend(capture_split(report, out_dir / args.prefix,
                                     width=args.width, quality=args.quality,
                                     boundary_label=args.boundary_label))

    for p in written:
        _report(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
