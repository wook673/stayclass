"""오케스트레이터 CLI (엔진은 core.py 공유) — 영상 1개 = 폴더 1개

사용법:
  python make_video.py <프로젝트>           영상 제작 (생략 시 1개면 자동)
  python make_video.py <프로젝트> --from 3   3단계부터 재시작
  python make_video.py --new <이름>          새 프로젝트 폴더 생성
  python make_video.py --list                프로젝트 목록

* 그래픽 화면(UI)으로 쓰려면: start.bat 더블클릭 (app.py)
"""
import argparse

import core


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project", nargs="?")
    ap.add_argument("--from", dest="start", type=int, default=1)
    ap.add_argument("--new", metavar="이름")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.new:
        core.create_project(args.new)
        print(f"생성됨 → projects/{args.new}/  (대본 작성 후: python make_video.py {args.new})")
        return
    if args.list:
        for n in core.list_project_names():
            print(f"  - {n}")
        return

    names = core.list_project_names()
    if args.project:
        name = args.project
    elif len(names) == 1:
        name = names[0]
    elif not names:
        raise SystemExit("프로젝트가 없습니다. python make_video.py --new <이름>")
    else:
        print("프로젝트를 지정하세요:")
        for n in names:
            print(f"  - {n}")
        return

    print(f"■ 프로젝트: {name}")
    try:
        out = core.run_pipeline(
            name, start=args.start,
            on_progress=lambda step, label: print(f"{'①②③④⑤'[step-1] if step else '·'} {label}"))
    except RuntimeError as e:
        raise SystemExit(f"[중단] {e}")
    print(f"\n완료 → {out}")


if __name__ == "__main__":
    main()
