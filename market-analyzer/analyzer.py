# -*- coding: utf-8 -*-
"""analyzer.py — 다니엘스테이 단기임대 시장분석 CLI.

사용:
  python analyzer.py --loc 동탄역 --radius 500 [--months 6] [--weeks 8]
                     [--session-file session.txt] [--samples 10]
                     [--mgmt 10] [--occ 0.70] [--no-cache]
  # 사전에 없는 지역:
  python analyzer.py --lat .. --lon .. --lawd 41597 --dong 영천동 --loc 이름

파이프라인: 위치해석 → 33m2 공급스캔 → (세션있으면)예약률 → MOLIT 밴드 →
            수익률(정본 산식·앵커검증) → 콘솔요약 + md + html.
예약률은 세션 없음/만료 시 죽지 않고 "로그인 필요" 표기 후 계속(graceful degradation).
"""
from __future__ import annotations

import argparse
import sys

import config
import locate                    # 지역명 자유 입력 자동 해석(사전에 없을 때)
import model                     # import 시점에 앵커 자기검증 실행(실패하면 여기서 중단)
import molit
import m33
import report
import rules                     # import 시점에 판단룰 자기검증 실행
import stations


def build_caveats(ctx) -> list:
    c = [
        "매출(주간가·예약률)=33m2 현시점 실측 스냅숏, 비용(월세)=MOLIT 법정동 실거래 — "
        "공간단위(500m 반경 ≠ 법정동)·시점 불일치.",
        "표기 월세는 MOLIT 신고 원값(보증금 환산 없음). 밴드 내 보증금 혼재(300~700/700~1300)로 "
        "각 밴드 중위는 '대략 500/1000 케이스' 근사.",
        "관리비는 가정값(기본 10만, --mgmt로 조정), 공과금 6만·청소실비 3.2만·수수료 3.3%·청소수입 "
        "3만/주는 산식 고정 가정. MOLIT 관리비 필드는 전부 null.",
        "예약률의 disable(호스트 수기 차단)은 타 플랫폼 예약(실수요)로 해석하나 상한 성격 — "
        "일부는 순수 운영중단일 수 있음.",
    ]
    b = ctx["molit"]["bands"]
    if not b["500"]["sufficient"] or not b["1000"]["sufficient"]:
        c.append("표본<3 밴드는 '표본 부족'으로 수치 미제시(추정 금지).")
    if ctx.get("occ_login_needed"):
        c.append("예약률 로그인 세션이 없어 가동률 미측정 — 수익 계산은 '세션 필요'로 "
                 "보류(공급·월세만 산출). 가정치 대체 없음.")
    if ctx.get("window", "past") == "past":
        c.append("가동률은 지난 %d주 확정 실적(booking+disable ÷ 기간) 기준 — "
                 "향후 수요를 보장하지 않음." % ctx.get("weeks", 8))
    return c


def compute_conservative(weekly_median_won, occ, bands, mgmt):
    """보수적 순수익 (기본 출력, 만원 단위) — 사용자 지정 단순 산식.

      월 기대매출 = 주간가 중위 × 4.345 × 실측 가동률
      보수 순수익 = 기대매출 − 밴드 월세중위 − 관리비   (다른 가감 없음)

    500밴드가 기준(primary), 1000밴드는 참고 행. occ(실측) 없으면 빈 리스트.
    """
    if occ is None or weekly_median_won is None:
        return []
    weekly_man = weekly_median_won / 10000.0
    revenue = weekly_man * config.WEEKS_PER_MONTH * occ
    rows = []
    for band, dep in (("500", config.DEPOSIT_500), ("1000", config.DEPOSIT_1000)):
        b = bands[band]
        if not b["sufficient"]:
            continue
        rent = b["rent_median"]
        rows.append({
            "band": band, "deposit": dep, "revenue": revenue,
            "rent": rent, "mgmt": mgmt, "net": revenue - rent - mgmt,
            "primary": band == "500",
        })
    return rows


def compute_scenarios(weekly_median_won, occ, bands, mgmt):
    """[상세 모델·보조] 밴드별(충분 표본) × share 60/50 수익률(정본 산식).
    occ 없으면 빈 리스트."""
    if occ is None or weekly_median_won is None:
        return []
    weekly_man = weekly_median_won / 10000.0
    scs = []
    for band, dep in (("500", config.DEPOSIT_500), ("1000", config.DEPOSIT_1000)):
        b = bands[band]
        if not b["sufficient"]:
            continue
        rent = b["rent_median"]
        p60 = model.monthly_profit(weekly_man, occ, rent, mgmt,
                                   config.UTILITIES, config.SHARE_PRIMARY)
        p50 = model.monthly_profit(weekly_man, occ, rent, mgmt,
                                   config.UTILITIES, config.SHARE_ALT)
        scs.append({
            "band": band, "deposit": dep, "rent": rent,
            "profit60": p60, "profit50": p50,
            "yield60": model.annual_yield_pct(p60, dep),
            "yield50": model.annual_yield_pct(p50, dep),
        })
    return scs


def run_scan_mode(args):
    """--scan: 지역 스캔 → 비교 랭킹 리포트."""
    import scan
    session_headers = None
    if args.session_file:
        try:
            session_headers = m33.parse_session_file(args.session_file)
            print(f"      세션 파일 로드: {list(session_headers.keys())}")
        except (OSError, m33.SessionError) as e:
            print(f"      세션 파일 문제({e}) — 예약률 없이 진행", file=sys.stderr)
    print(f"[스캔] '{args.scan}' 지역 스캔 시작...")
    try:
        result = scan.run_scan(
            args.scan, top=args.top, months=args.months, radius=args.radius,
            occ_assumed=args.occ, session_headers=session_headers,
            mgmt=args.mgmt, use_cache=not args.no_cache,
            min_size=args.min_cluster)
    except Exception as e:
        print(f"[스캔] 실패: {e}", file=sys.stderr)
        return 1
    md_path, html_path = report.write_scan_reports(result)
    print(f"\n스캔 랭킹 리포트 생성:\n  {md_path}\n  {html_path}")
    print(f"  발굴 클러스터 {result['n_clusters']}개 · 분석 {len(result['clusters'])}개")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="다니엘스테이 단기임대 시장분석")
    ap.add_argument("--loc", help="지역명(사전) 또는 수동 지정 시 표시 이름")
    ap.add_argument("--scan", help="스캔 모드: 지역명(예: '수원시 영통구') 바운딩박스 "
                    "타일수집→500m 클러스터링→상위 N 분석→비교 랭킹 리포트")
    ap.add_argument("--top", type=int, default=5, help="스캔 상위 클러스터 수(기본 5)")
    ap.add_argument("--min-cluster", type=int, default=3,
                    help="클러스터 최소 매물 수(기본 3)")
    ap.add_argument("--radius", type=float, default=config.DEFAULT_RADIUS_M)
    ap.add_argument("--months", type=int, default=config.DEFAULT_MONTHS)
    ap.add_argument("--weeks", type=int, default=config.DEFAULT_WEEKS)
    ap.add_argument("--samples", type=int, default=config.DEFAULT_SAMPLES)
    ap.add_argument("--mgmt", type=float, default=config.DEFAULT_MGMT,
                    help="관리비 가정(만원, 기본 10)")
    ap.add_argument("--occ", type=float, default=None,
                    help="[스캔 모드 전용] 가정 예약률(0~1). 단일 지역 분석은 "
                         "실측만 사용 — 세션 없으면 수익 계산 보류")
    ap.add_argument("--window", choices=("past", "future"), default="past",
                    help="가동률 측정 창: past=지난 N주 확정 실적(기본) / "
                         "future=향후 N주 예정")
    ap.add_argument("--session-file", help="33m2 로그인 세션 파일(쿠키/Bearer)")
    ap.add_argument("--no-cache", action="store_true", help="MOLIT 캐시 미사용")
    # 수동 위치(사전에 없을 때)
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--lawd")
    ap.add_argument("--dong", nargs="+")
    args = ap.parse_args(argv)

    config.ensure_dirs()

    # 스캔 모드: 지역 전체 타일 수집 → 클러스터링 → 상위 N 분석 → 랭킹
    if args.scan:
        return run_scan_mode(args)

    # 1) 위치 해석: 사전(빠른 경로) → 수동 지정 → 자동 해석(locate)
    locate_evidence = None
    st, name = stations.resolve(args.loc or "")
    if st:
        lat, lon = st["lat"], st["lon"]
        lawd, dongs, desc = st["lawd"], st["dongs"], st["desc"]
        region = name
    elif (args.lat is not None and args.lon is not None
          and args.lawd and args.dong):
        lat, lon = args.lat, args.lon
        lawd, dongs, desc = args.lawd, args.dong, "수동 지정 위치"
        region = args.loc or f"{lat},{lon}"
    elif args.loc:
        # 사전에도 없고 수동 지정도 없음 → 자동 해석 시도
        print(f"[1/4] '{args.loc}' 사전에 없음 → 자동 위치 해석(지오코딩→33m2→LAWD→역매칭)...")
        try:
            loc = locate.auto_locate(args.loc, args.radius, args.months,
                                     molit.load_service_key(),
                                     use_cache=not args.no_cache)
        except locate.LocateError as e:
            ap.error(f"자동 위치 해석 실패: {e}\n"
                     f"  사전 지역: {', '.join(stations.known_names())}\n"
                     f"  또는 --lat --lon --lawd --dong 수동 지정.")
        lat, lon = loc["lat"], loc["lon"]
        lawd, dongs, desc = loc["lawd"], loc["dongs"], loc["desc"]
        region = args.loc
        locate_evidence = loc["evidence"]
    else:
        ap.error("--loc(지역명) 또는 --lat --lon --lawd --dong 수동 지정 필요.\n"
                 f"  사전 지역: {', '.join(stations.known_names())}")

    print(f"[1/4] 위치 해석: {region} (lat {lat}, lon {lon}, LAWD {lawd}, 동 {'/'.join(dongs)})")
    if locate_evidence:
        for e in locate_evidence:
            print(f"      · {e}")

    # 세션
    session_headers = None
    if args.session_file:
        try:
            session_headers = m33.parse_session_file(args.session_file)
            print(f"      세션 파일 로드: {list(session_headers.keys())}")
        except (OSError, m33.SessionError) as e:
            print(f"      세션 파일 문제({e}) — 예약률은 건너뜀", file=sys.stderr)

    # 2) 공급 스캔
    print(f"[2/4] 33m2 공급 스캔(반경 {args.radius:.0f}m)...")
    try:
        supply = m33.scan_supply(lat, lon, args.radius)
    except Exception as e:
        print(f"      공급 스캔 실패: {e}", file=sys.stderr)
        supply = {"n_total": 0, "n_type_excluded": 0, "n_notroom_excluded": 0,
                  "n_kept": 0, "weekly": {"median": None, "min": None,
                  "max": None, "n": 0}, "rooms": []}
    print(f"      유지 {supply['n_kept']}건 · 주간가 중위 "
          f"{supply['weekly']['median']}")

    # 3) 예약률 — 실측 필수 (기본: 지난 N주 확정 실적)
    occupancy, occ_login_needed = None, False
    if session_headers:
        wlabel = "지난" if args.window == "past" else "향후"
        print(f"[3/4] 예약률 캘린더 조회({wlabel} {args.weeks}주 창)...")
        try:
            occupancy = m33.fetch_occupancy(supply["rooms"], session_headers,
                                            weeks=args.weeks, samples=args.samples,
                                            window=args.window)
        except m33.SessionError as e:
            print(f"      예약률: 로그인 필요 ({e})", file=sys.stderr)
            occ_login_needed = True
    else:
        print("[3/4] 예약률: 세션 파일 없음 → 수익 계산 보류(세션 필요)")
        occ_login_needed = True

    # 실측값만 사용 — 가정치 대체 없음(세션 없으면 수익 계산 보류)
    occ_used, occ_measured = None, False
    if occupancy and occupancy.get("ok"):
        occ_used, occ_measured = occupancy["combined_occ"], True

    # 4) MOLIT 밴드
    print(f"[4/4] MOLIT 실거래 수집(최근 {args.months}개월, "
          f"{'캐시 미사용' if args.no_cache else '캐시 우선'})...")
    key = molit.load_service_key()
    mo = molit.collect(key, lawd, dongs, args.months, use_cache=not args.no_cache)
    print(f"      필터 {mo['n_filtered']}건 · "
          f"500밴드 {mo['bands']['500']['n']} / 1000밴드 {mo['bands']['1000']['n']}")

    # 수익 계산: 보수 순수익(기본) + 상세 모델(보조) — 둘 다 실측 가동률만
    conservative = compute_conservative(supply["weekly"]["median"], occ_used,
                                        mo["bands"], args.mgmt)
    scenarios = compute_scenarios(supply["weekly"]["median"], occ_used,
                                  mo["bands"], args.mgmt)

    ctx = {
        "region": region, "desc": desc, "date": report._today(),
        "radius": args.radius, "months": args.months, "weeks": args.weeks,
        "window": args.window, "mgmt": args.mgmt, "supply": supply,
        "occupancy": occupancy, "occ_login_needed": occ_login_needed,
        "occ_used": occ_used, "occ_measured": occ_measured, "molit": mo,
        "conservative": conservative, "scenarios": scenarios,
        "locate_evidence": locate_evidence,
    }
    ctx["caveats"] = build_caveats(ctx)

    # 분석·판단(판단룰 엔진) — 품질교락·신뢰등급·타채널 해석·추천
    ctx["analysis"] = rules.analyze(ctx)

    # 리포트
    print("\n" + "=" * 68)
    print(report.console_summary(ctx))
    print("=" * 68)
    md_path, html_path = report.write_reports(ctx)
    print(f"\n리포트 생성:\n  {md_path}\n  {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
