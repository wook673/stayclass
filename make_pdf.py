from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import Color, HexColor

# ── 폰트 등록 ──────────────────────────────────────────────
pdfmetrics.registerFont(TTFont("KR",   r"C:\Windows\Fonts\malgun.ttf"))
pdfmetrics.registerFont(TTFont("KR-B", r"C:\Windows\Fonts\malgunbd.ttf"))

# ── 슬라이드 사이즈 (16:9 widescreen) ─────────────────────
W = 960
H = 540

# ── 색상 ──────────────────────────────────────────────────
BG     = HexColor("#0A0A0A")
SURF   = HexColor("#141414")
BORDER = HexColor("#2A2A2A")
TEXT   = HexColor("#F0ECE4")
MUTED  = HexColor("#777777")
LIME   = HexColor("#C8FF57")
BLUE   = HexColor("#38BDF8")
DIM    = HexColor("#222222")

OUT = r"C:\Users\User\test\stayclass_lecture.pdf"
c = canvas.Canvas(OUT, pagesize=(W, H))


# ── 헬퍼 ──────────────────────────────────────────────────
def bg_fill(color=BG):
    c.setFillColor(color)
    c.rect(0, 0, W, H, fill=1, stroke=0)

def accent_bar(color=LIME, w=4):
    c.setFillColor(color)
    c.rect(0, 0, w, H, fill=1, stroke=0)

def txt(text, x, y, size=18, font="KR", color=TEXT, align="left"):
    c.setFont(font, size)
    c.setFillColor(color)
    if align == "center":
        c.drawCentredString(x, y, text)
    elif align == "right":
        c.drawRightString(x, y, text)
    else:
        c.drawString(x, y, text)

def label(text, x, y, color=LIME):
    txt(text.upper(), x, y, size=11, font="KR-B", color=color)

def heading(lines, x, y, size=46, color=TEXT):
    for i, line in enumerate(lines):
        txt(line, x, y - i * (size * 1.2), size=size, font="KR-B", color=color)

def fill_rect(x, y, w, h, color, rx=0):
    c.setFillColor(color)
    c.setStrokeColor(color)
    if rx:
        c.roundRect(x, y, w, h, rx, fill=1, stroke=0)
    else:
        c.rect(x, y, w, h, fill=1, stroke=0)

def stroke_rect(x, y, w, h, color, lw=1):
    c.setStrokeColor(color)
    c.setLineWidth(lw)
    c.rect(x, y, w, h, fill=0, stroke=1)

def hline(x, y, w, color=BORDER, lw=0.5):
    c.setStrokeColor(color)
    c.setLineWidth(lw)
    c.line(x, y, x + w, y)

def bar_row(lbl, val, note, pct, y, col=TEXT, note_col=LIME):
    bar_x = 220
    bar_full = 520
    txt(lbl, 20, y, size=13, color=MUTED)
    txt(val,  bar_x, y, size=17, font="KR-B", color=col)
    txt(note, bar_x + 260, y, size=11, color=note_col)
    fill_rect(bar_x, y - 14, bar_full, 4, BORDER)
    fill_rect(bar_x, y - 14, int(bar_full * pct), 4, col)

def bullet(items, x, y, size=17, gap=34):
    for i, item in enumerate(items):
        txt("—", x, y - i * gap, size=size, font="KR", color=BORDER)
        txt(item, x + 20, y - i * gap, size=size, font="KR", color=MUTED)

def page_end():
    c.showPage()


# ══════════════════════════════════════════════════════════
# SLIDE 1 — 표지
# ══════════════════════════════════════════════════════════
bg_fill()
accent_bar(LIME)

# 배경 대형 숫자
c.setFont("KR-B", 320)
c.setFillColor(DIM)
c.drawString(400, 60, "150")

txt("STAYCLASS", 30, H - 40, size=12, font="KR-B", color=MUTED)

heading(["직장 다니면서", "월 150만원", "더 버는 법"],
        30, H - 90, size=54)

# 150만원 강조선
fill_rect(30, H - 230, 290, 4, LIME)

txt("단기임대 수익 시스템 · 4주 현장강의", 30, 70, size=17, color=MUTED)
txt("© 2026 STAYCLASS", 30, 30, size=11, color=BORDER)

page_end()


# ══════════════════════════════════════════════════════════
# SLIDE 2 — 목차
# ══════════════════════════════════════════════════════════
bg_fill()
accent_bar(LIME)

label("오늘 배울 것", 30, H - 45)
heading(["4주 완성", "커리큘럼"], 30, H - 80, size=44)

weeks = [
    ("1주차", "수익 나는\n물건 찾기"),
    ("2주차", "계약 &\n방 세팅"),
    ("3주차", "운영\n자동화 구축"),
    ("4주차", "수익 극대화\n& 확장"),
]
cx_start = 30
for i, (wk, ttl) in enumerate(weeks):
    cx = cx_start + i * 235
    fill_rect(cx, 215, 220, 3, LIME)
    txt(wk, cx, 198, size=12, font="KR-B", color=LIME)
    for j, line in enumerate(ttl.split("\n")):
        txt(line, cx, 162 - j * 28, size=18, font="KR-B", color=TEXT)

txt("목표: 4주 후 방 1개 운영 시작 · 방 3개 달성 시 월 150만원",
    30, 40, size=14, color=MUTED)

page_end()


# ══════════════════════════════════════════════════════════
# SLIDE 3 — 왜 단기임대인가
# ══════════════════════════════════════════════════════════
bg_fill()
accent_bar(LIME)

label("왜 단기임대인가", 30, H - 45)
heading(["이게 되는", "이유 셋"], 30, H - 80, size=44)

reasons = [
    ("01", "내 집 없어도 됩니다",   "임차인 구조로 운영 · 초기비용 100~150만원"),
    ("02", "자동화가 됩니다",       "하루 30분 이내 운영 · 직장 병행 가능"),
    ("03", "월세보다 2배 납니다",    "월세 30~40만원  vs  단기임대 50~70만원"),
]

for i, (num, ttl, desc) in enumerate(reasons):
    y = 235 - i * 88
    txt(num, 30, y, size=13, font="KR-B", color=BORDER)
    txt(ttl, 80, y, size=20, font="KR-B", color=TEXT)
    txt(desc, 80, y - 28, size=14, color=MUTED)
    if i < 2:
        hline(30, y - 48, W - 60, BORDER)

page_end()


# ══════════════════════════════════════════════════════════
# SLIDE 4 — 수익 구조
# ══════════════════════════════════════════════════════════
bg_fill()
accent_bar(LIME)

label("수익 구조", 30, H - 45)
heading(["방 3개 =", "월 150만원"], 30, H - 80, size=44)

bars = [
    ("방 1개",  "월 50~70만원",    "실측 기준", 0.38, TEXT,  LIME),
    ("방 3개",  "월 150~210만원",  "목표",      0.68, LIME,  LIME),
    ("방 7개",  "월 381만원",      "강사 실측", 1.00, BLUE,  BLUE),
]

for i, (lbl, val, note, pct, col, nc) in enumerate(bars):
    bar_row(lbl, val, note, pct, 240 - i * 70, col, nc)

txt("강사 실측: 7개 방 / Hostier 2026년 6월 기준",
    30, 45, size=12, color=BORDER)

page_end()


# ══════════════════════════════════════════════════════════
# SLIDE 5 — 실증 데이터
# ══════════════════════════════════════════════════════════
bg_fill()
accent_bar(BLUE)

label("강사 직접 운영 실증", 30, H - 45, color=BLUE)
heading(["숫자가", "증명합니다"], 30, H - 80, size=44)

# 데이터 카드
fill_rect(20, 55, W - 40, 200, SURF)
fill_rect(20, 251, W - 40, 4, BLUE)

txt("● LIVE  · Hostier 2026년 6월 기준", 36, 238, size=11, font="KR-B", color=BLUE)

stats = [
    ("90",   "%",   "가동률"),
    ("381",  "만원", "월 순수익"),
    ("54",   "만원", "방당 평균"),
    ("7",    "개",   "직영 방"),
]

for i, (num, unit, desc) in enumerate(stats):
    cx = 36 + i * 228
    txt(num,  cx,      210, size=54, font="KR-B", color=LIME)
    txt(unit, cx + 72, 220, size=16, font="KR-B", color=BLUE)
    txt(desc, cx,       78, size=13, color=MUTED)
    if i < 3:
        hline(cx + 200, 90, 1, BORDER, lw=30)

txt("가동률 90% · 210박 중 188박 예약 확정",
    36, 58, size=12, color=MUTED)

page_end()


# ══════════════════════════════════════════════════════════
# SLIDE 6 — 1주차
# ══════════════════════════════════════════════════════════
bg_fill()
accent_bar(LIME)

label("1주차", 30, H - 45)
heading(["수익 나는", "물건 찾기"], 30, H - 80, size=44)

items1 = [
    "역세권 · 병원 · 법원 인근 지역 선정 공식",
    "삼삼엠투 vs 에어비앤비 수익 구조 비교",
    "수익 계산기로 사전 검증하는 법",
    "집주인 협상 스크립트 제공",
    "계약 전 체크리스트 완성",
]
bullet(items1, 30, 235)

# 핵심 공식 박스
fill_rect(680, 120, 260, 160, SURF)
stroke_rect(680, 120, 260, 160, BORDER)
txt("핵심 공식", 692, 260, size=11, font="KR-B", color=LIME)
txt("수요 = 유동인구", 692, 232, size=16, font="KR-B", color=TEXT)
txt("÷ 숙소 수",       692, 204, size=16, font="KR-B", color=TEXT)
txt("이 비율이 높은 곳부터", 692, 170, size=12, color=MUTED)
txt("선점합니다",           692, 148, size=12, color=MUTED)

page_end()


# ══════════════════════════════════════════════════════════
# SLIDE 7 — 2주차
# ══════════════════════════════════════════════════════════
bg_fill()
accent_bar(LIME)

label("2주차", 30, H - 45)
heading(["계약 &", "방 세팅"], 30, H - 80, size=44)

items2 = [
    "계약서 조항 체크리스트 (전대차 허용 조항 필수)",
    "초기 세팅 물품 리스트 & 비용 최소화",
    "사진 촬영으로 클릭률 높이는 법",
    "첫 예약 빠르게 받는 초기 가격 전략",
    "삼삼엠투 리스팅 첫 등록 실습",
]
bullet(items2, 30, 235)

# 비용 박스
fill_rect(680, 90, 260, 200, SURF)
stroke_rect(680, 90, 260, 200, BORDER)
txt("초기 비용 목표", 692, 270, size=11, font="KR-B", color=LIME)
costs = [("보증금", "50~100만원"), ("세팅 용품", "30~50만원"), ("중개비", "10~20만원")]
for i, (k, v) in enumerate(costs):
    y = 236 - i * 44
    txt(k, 692, y, size=13, color=MUTED)
    txt(v, 820, y, size=13, font="KR-B", color=TEXT)

page_end()


# ══════════════════════════════════════════════════════════
# SLIDE 8 — 3주차
# ══════════════════════════════════════════════════════════
bg_fill()
accent_bar(LIME)

label("3주차", 30, H - 45)
heading(["운영", "자동화 구축"], 30, H - 80, size=44)

items3 = [
    "비대면 체크인 시스템 (키박스 / 스마트락)",
    "청소 위탁 업체 선정 기준 & 단가 협상",
    "메시지 자동화 템플릿 전체 제공",
    "예약→안내→체크아웃 자동 흐름 설계",
    "하루 30분 운영 루틴 만들기",
]
bullet(items3, 30, 235)

fill_rect(680, 110, 260, 175, SURF)
stroke_rect(680, 110, 260, 175, BORDER)
txt("자동화 후", 692, 266, size=11, font="KR-B", color=LIME)
txt("하루 30분", 692, 228, size=30, font="KR-B", color=LIME)
txt("직장 퇴근 후", 692, 180, size=13, color=MUTED)
txt("루틴으로 관리 가능", 692, 157, size=13, color=MUTED)

page_end()


# ══════════════════════════════════════════════════════════
# SLIDE 9 — 4주차
# ══════════════════════════════════════════════════════════
bg_fill()
accent_bar(LIME)

label("4주차", 30, H - 45)
heading(["수익 극대화", "& 확장"], 30, H - 80, size=44)

items4 = [
    "시즌별 가격 조정 전략 (성수기 / 비수기)",
    "공실 최소화 — 다채널 & 할인 타이밍 전략",
    "플랫폼 노출 랭킹 올리는 법",
    "2호점 계약 타이밍 (1호점 안정 후 60일)",
    "위탁운영 전환으로 완전 자동화 완성",
]
bullet(items4, 30, 235)

fill_rect(680, 90, 260, 215, SURF)
stroke_rect(680, 90, 260, 215, BORDER)
txt("최종 목표", 692, 286, size=11, font="KR-B", color=LIME)
txt("방 3개",   692, 250, size=28, font="KR-B", color=LIME)
txt("월 150만원", 692, 216, size=22, font="KR-B", color=LIME)
hline(692, 204, 230, BORDER)
txt("방 7개 달성 시",  692, 183, size=13, color=MUTED)
txt("월 381만원 (실측)", 692, 160, size=13, color=BLUE)

page_end()


# ══════════════════════════════════════════════════════════
# SLIDE 10 — Q&A
# ══════════════════════════════════════════════════════════
bg_fill()
accent_bar(LIME)

# 배경 대형 텍스트
c.setFont("KR-B", 260)
c.setFillColor(DIM)
c.drawString(20, 100, "Q&A")

txt("궁금한 것 뭐든지 물어보세요",
    30, 115, size=26, font="KR-B", color=TEXT)

txt("카카오채널  ·  pf.kakao.com/_APzxbX/chat",
    30, 76, size=14, color=MUTED)

# 하단 라임 바
fill_rect(0, 0, W, 8, LIME)

txt("STAYCLASS", 30, 18, size=12, font="KR-B", color=BORDER)

page_end()


# ── 저장 ──────────────────────────────────────────────────
c.save()
print(f"PDF 저장 완료: {OUT}")
print(f"총 10슬라이드")
