# -*- coding: utf-8 -*-
"""mapimg.py — 분석 반경 지도 이미지 자동 생성 (OSM 타일 배경 + 반경/매물 오버레이).

리포트에 "이 분석이 어디를, 얼마나 넓게 봤는지"를 한 장으로 보여준다.
  · 배경 : OpenStreetMap 정적 타일(https://tile.openstreetmap.org/{z}/{x}/{y}.png)
           - 식별 가능한 User-Agent 사용(OSM 타일 사용정책 준수)
           - 타일 간 짧은 대기 + .cache/tiles/ 로컬 캐시로 재요청 최소화
           - 실패(네트워크/차단/429)면 **배경 없이** 원·마커만 그린다(폴백)
  · 오버레이 : 중심 마커 + 반경 원(빨간 실선 + 반투명 채움, 실제 축척)
               + 매물 점 마커, 선점률 상위 1~3위는 강조 마커 + 번호 라벨
  · 범례·축척 바·저작권 표기(© OpenStreetMap contributors)

의존성은 Pillow 뿐. Pillow가 없으면 render_*()는 조용히 None을 돌려주고
리포트는 지도 없이 정상 생성된다(graceful degradation).

축척 검증:
  원의 픽셀 반지름 = radius_m / mpp,  축척 바의 픽셀 길이 = bar_m / mpp
  (mpp = 중심 위도·줌의 meters-per-pixel) → 둘은 같은 척도를 공유한다.
  render_map(..., debug=True) 로 실제 값들을 dict 로 받아 검증할 수 있다.
"""
from __future__ import annotations

import io
import math
import os
import sys
import time

try:                                        # Pillow 없으면 지도 기능만 비활성
    from PIL import Image, ImageDraw, ImageFont
except ImportError:                         # pragma: no cover
    Image = ImageDraw = ImageFont = None

try:
    import requests
except ImportError:                         # pragma: no cover
    requests = None

import config

# --------------------------------------------------------------------------- #
# 상수
# --------------------------------------------------------------------------- #
# 배경 타일 — VWORLD_KEY 가 있으면 VWorld(국토부, 한글 지번·건물), 없으면 OSM 폴백.
# 키는 리포지토리에 넣지 않는다: 환경변수 또는 gitignore 된 .vworld_key 파일.
_KEYF = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".vworld_key")
VWORLD_KEY = (os.environ.get("VWORLD_KEY")
              or (open(_KEYF, encoding="utf-8").read().strip()
                  if os.path.exists(_KEYF) else ""))
# 레이어: Base(지도) / Hybrid(위성+라벨, .png) / Satellite(위성, .jpeg)
VWORLD_LAYER = os.environ.get("VWORLD_LAYER", "Base")
TILE_URL = (f"https://api.vworld.kr/req/wmts/1.0.0/{VWORLD_KEY}/{VWORLD_LAYER}"
            "/{z}/{y}/{x}.png" if VWORLD_KEY
            else "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
ATTRIB = "© VWorld (국토교통부)" if VWORLD_KEY else "© OpenStreetMap contributors"
USER_AGENT = "market-analyzer/1.0 (local research tool)"
TILE_SIZE = 256
MAP_W, MAP_H = 768, 576          # 출력 PNG 크기(타일 3x3~4x4 범위)
TILE_SLEEP = 0.2                 # 타일 요청 간 대기(초) — 캐시 히트는 대기 없음
TILE_TIMEOUT = 8
MAX_TILES = 20                   # 한 장에 쓰는 타일 상한(초과하면 배경 생략)
MAX_TILE_FAILS = 3               # 연속 실패 시 즉시 폴백(서버 두드리지 않음)
CACHE_SUBDIR = "tiles"

C_RED = (214, 45, 45)
C_RED_FILL = (214, 45, 45, 26)
C_ROOM = (16, 82, 60)            # 매물 마커(딥그린)
C_TOP = (198, 138, 22)           # 상위 선점률 강조(골드)
C_INK = (26, 32, 30)
C_BG_FALLBACK = (240, 238, 233)  # 타일 실패 시 배경

_NICE_M = (25, 50, 100, 150, 200, 250, 300, 500, 750,
           1000, 1500, 2000, 3000, 5000)

_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\malgun.ttf",                          # 맑은 고딕
    r"C:\Windows\Fonts\NanumGothic.ttf",
    r"C:\Windows\Fonts\gulim.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
)
_FONT_BOLD_CANDIDATES = (
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\NanumGothicBold.ttf",
) + _FONT_CANDIDATES

_font_cache = {}


def _font_path(bold=False):
    for p in (_FONT_BOLD_CANDIDATES if bold else _FONT_CANDIDATES):
        if os.path.exists(p):
            return p
    return None


def _font(size, bold=False):
    key = (size, bold)
    if key not in _font_cache:
        p = _font_path(bold)
        try:
            _font_cache[key] = (ImageFont.truetype(p, size) if p
                                else ImageFont.load_default())
        except OSError:
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


def _has_korean_font():
    return _font_path() is not None


# --------------------------------------------------------------------------- #
# 가동률 표기 정규화
# --------------------------------------------------------------------------- #
_HANGUL = ((0xAC00, 0xD7A3), (0x1100, 0x11FF), (0x3130, 0x318F), (0xA960, 0xA97F))


def _has_hangul(s):
    return any(any(a <= ord(ch) <= b for a, b in _HANGUL) for ch in (s or ""))


def normalize_pct(value):
    """가동률 값을 퍼센트 스칼라(0~100)로 정규화.

    호출부마다 단위가 달라 이중 변환(×100을 두 번)이 생기던 것을 막는다.
    비율(0~1)로 들어오면 ×100, 이미 퍼센트(>1)면 그대로 둔다.

        0.573 → 57.3   57.3 → 57.3   1.0 → 100.0   100 → 100.0   None → None

    0~1 구간은 항상 '비율'로 해석한다(1.0 포함). 실데이터에서 "1%"보다
    "100%"가 압도적으로 흔하고, 지도 라벨에서 0.5%p 차이는 의미가 없다.
    숫자가 아니거나 음수/NaN/inf면 None(=라벨 생략).
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v) or v < 0:
        return None
    return v * 100.0 if v <= 1.0 else v


def pct_label(value):
    """정규화된 한 자리 소수 퍼센트 문자열('57.3%') — 값이 없으면 None."""
    p = normalize_pct(value)
    return None if p is None else f"{p:.1f}%"


# --------------------------------------------------------------------------- #
# 웹 메르카토르 좌표 변환
# --------------------------------------------------------------------------- #
def _deg2px(lat, lon, z):
    """WGS84 → 줌 z의 전역 픽셀 좌표(타일 256px 기준)."""
    n = 2.0 ** z
    x = (lon + 180.0) / 360.0 * n * TILE_SIZE
    s = min(max(math.sin(math.radians(lat)), -0.9999), 0.9999)
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n * TILE_SIZE
    return x, y


def meters_per_pixel(lat, z):
    return 156543.03392804097 * math.cos(math.radians(lat)) / (2.0 ** z)


def pick_zoom(lat, radius_m, width_px=MAP_W, cover=2.6):
    """반경 원이 여백을 두고 들어가는 최대 줌(=가장 자세한 배경)."""
    span = max(float(radius_m) * cover, 50.0)
    val = 156543.03392804097 * math.cos(math.radians(lat)) / (span / width_px)
    if val <= 0:
        return 15
    return max(3, min(18, int(math.floor(math.log(val, 2)))))


# --------------------------------------------------------------------------- #
# 타일 (캐시 + 예의 바른 요청)
# --------------------------------------------------------------------------- #
def _tile_cache_path(z, x, y):
    d = os.path.join(config.CACHE_DIR, CACHE_SUBDIR)
    os.makedirs(d, exist_ok=True)
    # 소스를 키에 넣지 않으면 OSM 캐시가 VWorld 요청에 그대로 재사용된다.
    src = f"vworld-{VWORLD_LAYER}" if VWORLD_KEY else "osm"
    return os.path.join(d, f"{src}_{z}_{x}_{y}.png")


def _fetch_tile(z, x, y):
    """타일 1장 → PIL Image | None. 캐시 우선, 네트워크는 UA 명시 + 대기."""
    p = _tile_cache_path(z, x, y)
    if os.path.exists(p) and os.path.getsize(p) > 0:
        try:
            return Image.open(p).convert("RGB")
        except OSError:
            pass
    if requests is None:
        return None
    try:
        r = requests.get(TILE_URL.format(z=z, x=x, y=y),
                         headers={"User-Agent": USER_AGENT,
                                  "Accept": "image/png,image/*;q=0.8"},
                         timeout=TILE_TIMEOUT)
        if r.status_code != 200 or not r.content:
            return None
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:
        return None
    try:
        img.save(p, "PNG")
    except OSError:
        pass
    time.sleep(TILE_SLEEP)              # 타일 서버 배려(캐시 히트는 대기 없음)
    return img


def _background(lat, lon, z, w, h):
    """중심 좌표 기준 w×h 배경 이미지 + (좌상단 전역픽셀, 성공타일수)."""
    cx, cy = _deg2px(lat, lon, z)
    left, top = cx - w / 2.0, cy - h / 2.0
    x0 = int(math.floor(left / TILE_SIZE))
    y0 = int(math.floor(top / TILE_SIZE))
    x1 = int(math.floor((left + w - 1) / TILE_SIZE))
    y1 = int(math.floor((top + h - 1) / TILE_SIZE))
    canvas = Image.new("RGB", (w, h), C_BG_FALLBACK)
    n_need = (x1 - x0 + 1) * (y1 - y0 + 1)
    if n_need > MAX_TILES:
        return canvas, 0, (left, top)

    n_max = 2 ** z
    ok = fails = 0
    stop = False
    for ty in range(y0, y1 + 1):
        if stop:
            break
        if ty < 0 or ty >= n_max:
            continue
        for tx in range(x0, x1 + 1):
            img = _fetch_tile(z, tx % n_max, ty)
            if img is None:
                fails += 1
                if fails >= MAX_TILE_FAILS and ok == 0:
                    stop = True         # 타일 서버 차단/오프라인 → 즉시 폴백
                    break
                continue
            ok += 1
            canvas.paste(img, (int(round(tx * TILE_SIZE - left)),
                               int(round(ty * TILE_SIZE - top))))
    if ok == 0:
        return Image.new("RGB", (w, h), C_BG_FALLBACK), 0, (left, top)
    # 오버레이가 잘 보이도록 배경을 살짝 밝게(흰색 22% 블렌드)
    canvas = Image.blend(canvas, Image.new("RGB", (w, h), (255, 255, 255)), 0.22)
    return canvas, ok, (left, top)


# --------------------------------------------------------------------------- #
# 그리기 헬퍼
# --------------------------------------------------------------------------- #
def _text_size(draw, text, font):
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    return r - l, b - t


def _dot(draw, x, y, r, fill, outline=(255, 255, 255), width=2):
    draw.ellipse((x - r, y - r, x + r, y + r), fill=fill,
                 outline=outline, width=width)


def _boxes_overlap(a, b, pad=3):
    return not (a[2] + pad < b[0] or b[2] + pad < a[0]
                or a[3] + pad < b[1] or b[3] + pad < a[1])


def _label(draw, x, y, text, font, placed, fg=(255, 255, 255),
           bg=(26, 32, 30, 210), w=MAP_W, h=MAP_H):
    """겹치지 않을 때만 라벨을 그린다. 그렸으면 True."""
    tw, th = _text_size(draw, text, font)
    bx0, by0 = x, y - th / 2 - 3
    box = (bx0 - 5, by0 - 2, bx0 + tw + 5, by0 + th + 6)
    if box[2] > w - 6:                       # 오른쪽으로 넘치면 왼쪽에 배치
        box = (x - tw - 16, box[1], x - 6, box[3])
        bx0 = box[0] + 5
    if box[0] < 4 or box[1] < 4 or box[3] > h - 4:
        return False
    for p in placed:
        if _boxes_overlap(box, p):
            return False
    draw.rounded_rectangle(box, radius=4, fill=bg)
    draw.text((bx0, by0), text, font=font, fill=fg)
    placed.append(box)
    return True


def _scale_bar(draw, w, h, mpp, ko):
    """축척 바 — 원과 같은 mpp를 쓰므로 원 지름과 직접 비교 가능."""
    target = w * 0.22
    cands = [d for d in _NICE_M if d / mpp <= target] or [_NICE_M[0]]
    bar_m = cands[-1]
    bar_px = bar_m / mpp
    x1, y = w - 14, h - 44
    x0 = x1 - bar_px
    f = _font(12, bold=True)
    label = (f"{bar_m}m" if bar_m < 1000 else f"{bar_m/1000:g}km")
    tw, th = _text_size(draw, label, f)
    draw.rounded_rectangle((x0 - 10, y - th - 12, x1 + 10, y + 10),
                           radius=5, fill=(255, 255, 255, 225))
    draw.line((x0, y, x1, y), fill=C_INK, width=3)
    draw.line((x0, y - 6, x0, y + 4), fill=C_INK, width=3)
    draw.line((x1, y - 6, x1, y + 4), fill=C_INK, width=3)
    draw.text(((x0 + x1) / 2 - tw / 2, y - th - 8), label, font=f, fill=C_INK)
    return bar_m, bar_px


def _legend(draw, w, h, radius_m, n_rooms, date, ko, n_top):
    f = _font(14, bold=True)
    f2 = _font(12)
    if ko:
        l1 = f"반경 {radius_m:.0f}m · 매물 {n_rooms}건 · 측정일 {date}"
        l2 = "● 중심  ● 오피스텔 원룸"
        if n_top:
            l2 += "  ● 선점률 상위 " + "".join("①②③"[:n_top])
    else:
        l1 = f"radius {radius_m:.0f}m / {n_rooms} listings / measured {date}"
        l2 = "centre  listings" + ("  top occupancy" if n_top else "")
    w1, h1 = _text_size(draw, l1, f)
    w2, h2 = _text_size(draw, l2, f2)
    bw = max(w1, w2) + 24
    bh = h1 + h2 + 22
    x0, y0 = 12, h - bh - 12
    draw.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=7,
                           fill=(255, 255, 255, 228), outline=(0, 0, 0, 38))
    draw.text((x0 + 12, y0 + 8), l1, font=f, fill=C_INK)
    ty = y0 + 10 + h1
    # 범례 키의 색 점을 텍스트 위에 덧그린다(글머리 ● 를 색으로 표시)
    draw.text((x0 + 12, ty), l2, font=f2, fill=(90, 98, 95))
    return (x0, y0, x0 + bw, y0 + bh)


def _room_label(rank, room, top, ko):
    """상위 매물 마커 라벨 — '1. 이름 57.3%' / '#1 Name 57.3%'."""
    name = (room.get("name") or top.get("name") or "").strip()
    limit = 12 if ko else 36        # 라틴 문자는 폭이 좁아 더 길게 담긴다
    if len(name) > limit:
        name = name[:limit] + "…"
    if _has_hangul(name) and not _has_korean_font():
        name = ""                            # 한글 글꼴 없음 → 두부 글자 방지
    occ = pct_label(top.get("combined"))
    head = f"{rank}." if ko else f"#{rank}"
    return " ".join(p for p in (head, name, occ) if p)


def _attribution(draw, w, h, has_tiles, ko):
    f = _font(11)
    txt = (ATTRIB if has_tiles
           else (f"배경 지도 없음 (타일 서버 응답 없음) · {ATTRIB}"
                 if ko else "no basemap (tile server unavailable)"))
    tw, th = _text_size(draw, txt, f)
    x1, y1 = w - 8, h - 8
    draw.rounded_rectangle((x1 - tw - 10, y1 - th - 8, x1, y1), radius=4,
                           fill=(255, 255, 255, 215))
    draw.text((x1 - tw - 5, y1 - th - 5), txt, font=f, fill=(70, 78, 76))


# --------------------------------------------------------------------------- #
# 메인
# --------------------------------------------------------------------------- #
def render_map(lat, lon, radius_m, rooms, out_path, top_rooms=None,
               date=None, aux_circles=False, debug=False, lang=None):
    """분석 반경 지도 PNG 생성 → 저장 경로(또는 실패 시 None).

    lat/lon    : 분석 중심
    radius_m   : 분석 반경(빨간 실선 원)
    rooms      : [{"lat","lon","rid","name","weekly",...}] 수집 매물
    top_rooms  : 선점률 상위 리스트([{"rid","name","combined"}]) — 1~3위 강조
                 combined 은 비율(0~1)·퍼센트(0~100) 아무거나 받는다
                 (normalize_pct 가 정규화 — 라벨은 항상 '57.3%' 형태)
    aux_circles: True면 300m/1km 보조 원(점선 느낌의 옅은 원) 추가
    debug      : True면 (경로, 진단dict) 튜플 반환(축척 검증용)
    lang       : 라벨/범례 언어 — "ko" | "en" | None(자동: 한글 글꼴 있으면 ko)
    """
    if Image is None:                       # Pillow 없음 → 지도 없이 진행
        return (None, {"reason": "Pillow 없음"}) if debug else None
    try:
        return _render(lat, lon, radius_m, rooms, out_path, top_rooms,
                       date, aux_circles, debug, lang)
    except Exception as e:                  # 지도는 부가정보 — 절대 리포트를 죽이지 않는다
        sys.stderr.write(f"[지도] 생성 실패(무시하고 계속): {e}\n")
        return (None, {"reason": str(e)}) if debug else None


def _render(lat, lon, radius_m, rooms, out_path, top_rooms, date,
            aux_circles, debug, lang=None):
    import datetime
    date = date or datetime.date.today().isoformat()
    radius_m = float(radius_m)
    if lang is None:
        ko = _has_korean_font()             # 자동: 한글 글꼴 있으면 한글 라벨
    else:
        ko = str(lang).lower().startswith("ko")
    if ko and not _has_korean_font():
        ko = False                          # 글꼴 없이 한글을 그리면 두부만 남는다
    w, h = MAP_W, MAP_H
    z = pick_zoom(lat, radius_m, w)
    mpp = meters_per_pixel(lat, z)
    bg, n_tiles, (left, top) = _background(lat, lon, z, w, h)

    def to_px(plat, plon):
        gx, gy = _deg2px(plat, plon, z)
        return gx - left, gy - top

    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    cx, cy = to_px(lat, lon)
    rpx = radius_m / mpp

    # 1) 반경 원 — 실제 축척(빨간 실선 + 반투명 채움)
    if aux_circles:
        for aux in (300.0, 1000.0):
            if abs(aux - radius_m) < 1:
                continue
            ar = aux / mpp
            if ar < rpx * 3:
                d.ellipse((cx - ar, cy - ar, cx + ar, cy + ar),
                          outline=(214, 45, 45, 90), width=1)
    d.ellipse((cx - rpx, cy - rpx, cx + rpx, cy + rpx), fill=C_RED_FILL)
    d.ellipse((cx - rpx, cy - rpx, cx + rpx, cy + rpx),
              outline=C_RED + (235,), width=3)

    # 2) 매물 마커 (반경 안/밖 구분 없이 수집분 전체 — 스캔은 반경 필터를 이미 통과)
    rank_by_rid = {}
    for i, t in enumerate(sorted(top_rooms or [],
                                 key=lambda x: x.get("combined") or 0,
                                 reverse=True)[:3], 1):
        if t.get("rid") is not None:
            rank_by_rid[t["rid"]] = (i, t)

    n_drawn = 0
    highlights = []
    for r in (rooms or []):
        rlat, rlon = r.get("lat"), r.get("lon")
        if rlat is None or rlon is None:
            continue
        x, y = to_px(float(rlat), float(rlon))
        if not (-20 <= x <= w + 20 and -20 <= y <= h + 20):
            continue
        n_drawn += 1
        hit = rank_by_rid.get(r.get("rid"))
        if hit:
            highlights.append((hit[0], x, y, r, hit[1]))
            continue
        _dot(d, x, y, 5, C_ROOM + (225,), (255, 255, 255, 235), 2)

    # 3) 상위 강조 마커 + 번호
    fnum = _font(13, bold=True)
    for rank, x, y, room, t in sorted(highlights):
        _dot(d, x, y, 11, C_TOP + (245,), (255, 255, 255, 255), 3)
        txt = str(rank)
        tw, th = _text_size(d, txt, fnum)
        d.text((x - tw / 2, y - th / 2 - 1), txt, font=fnum,
               fill=(255, 255, 255, 255))

    # 4) 중심 마커
    d.line((cx - 12, cy, cx + 12, cy), fill=(255, 255, 255, 200), width=3)
    d.line((cx, cy - 12, cx, cy + 12), fill=(255, 255, 255, 200), width=3)
    _dot(d, cx, cy, 7, C_RED + (255,), (255, 255, 255, 255), 3)

    # 5) 라벨(겹치지 않게 상위 몇 개만)
    placed = []
    flab = _font(12, bold=True)
    for rank, x, y, room, t in sorted(highlights):
        _label(d, x + 15, y, _room_label(rank, room, t, ko), flab, placed,
               bg=(198, 138, 22, 225), w=w, h=h)

    # 6) 범례·축척·저작권
    _legend(d, w, h, radius_m, n_drawn, date, ko, len(highlights))
    bar_m, bar_px = _scale_bar(d, w, h, mpp, ko)
    _attribution(d, w, h, n_tiles > 0, ko)

    img = Image.alpha_composite(bg.convert("RGBA"), ov).convert("RGB")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    info = {"zoom": z, "mpp": mpp, "radius_px": rpx, "tiles_ok": n_tiles,
            "rooms_drawn": n_drawn, "scale_bar_m": bar_m,
            "scale_bar_px": bar_px, "size": (w, h),
            "expected_bar_px": bar_m / mpp, "path": out_path}
    return (out_path, info) if debug else out_path


def render_for_report(region, date, lat, lon, radius_m, supply,
                      occupancy=None, out_dir=None, lang=None):
    """리포트용 래퍼 — output/{지역}_{날짜}_map.png 생성 후 경로 반환(실패 None)."""
    if Image is None:
        sys.stderr.write("[지도] Pillow 미설치 — 지도 없이 리포트 생성\n")
        return None
    rooms = (supply or {}).get("rooms") or []
    top = []
    if occupancy and occupancy.get("ok"):
        top = sorted(occupancy.get("rooms", []),
                     key=lambda r: r.get("combined") or 0, reverse=True)[:3]
    out_dir = out_dir or config.OUTPUT_DIR
    safe = "".join(c for c in str(region) if c not in '\\/:*?"<>|').strip()
    path = os.path.join(out_dir, f"{safe}_{date}_map.png")
    return render_map(lat, lon, radius_m, rooms, path, top_rooms=top,
                      date=date, lang=lang)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="분석 반경 지도 이미지 생성(단독 테스트)")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--radius", type=float, default=500)
    ap.add_argument("--out", default="map_test.png")
    ap.add_argument("--lang", choices=("ko", "en"), default=None)
    a = ap.parse_args()
    p, info = render_map(a.lat, a.lon, a.radius, [], a.out, debug=True,
                         lang=a.lang)
    print(p, info)
