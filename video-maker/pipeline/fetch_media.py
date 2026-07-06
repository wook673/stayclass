"""③ 장면 키워드 → Pexels 스톡 영상/사진 다운로드

Pexels 무료 API로 키워드 검색 후 영상 1개를 받아 assets/에 저장.
설치: pip install requests
키 발급: https://www.pexels.com/api/  (무료)

AI 영상을 붙이려면: scene.get("use_ai")가 True인 장면만 분기해
   여기서 Runway/Veo 등 호출 → 같은 media_path 규약으로 저장하면 끝.
"""
from pathlib import Path

PEXELS_VIDEO = "https://api.pexels.com/videos/search"


def run(scenes: list[dict], cfg: dict, assets_dir: Path) -> list[dict]:
    import requests

    headers = {"Authorization": cfg["pexels_api_key"]}
    for sc in scenes:
        query = " ".join(sc["keywords"])
        r = requests.get(PEXELS_VIDEO,
                         headers=headers,
                         params={"query": query, "per_page": 1, "orientation": "landscape"})
        r.raise_for_status()
        vids = r.json().get("videos", [])
        if not vids:
            sc["media_path"] = None  # 후속 단계에서 단색/이전소재로 대체
            continue
        # 적당한 화질 파일 링크 고르기
        files = sorted(vids[0]["video_files"], key=lambda f: f.get("width", 0))
        link = files[len(files) // 2]["link"]
        dest = assets_dir / f"media_{sc['index']}.mp4"
        with requests.get(link, stream=True) as dl:
            dl.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in dl.iter_content(1 << 16):
                    f.write(chunk)
        sc["media_path"] = str(dest)
    return scenes
