# -*- coding: utf-8 -*-
"""tlpcserver.imakeweb.co.kr 제품 카탈로그 크롤러
카테고리 구조 파싱 → 목록 페이지 순회(페이지네이션 포함) → catalog.json 저장
"""
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://tlpcserver.imakeweb.co.kr"
OUT_DIR = Path(__file__).parent
DELAY = 0.3  # 서버 부하 방지

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (catalog-builder)"})


def get_soup(url):
    r = session.get(url, timeout=20)
    r.raise_for_status()
    r.encoding = "utf-8"
    return BeautifulSoup(r.text, "html.parser")


def parse_categories():
    """메인 페이지 내비게이션에서 root/subcategory 이름과 코드 추출"""
    soup = get_soup(BASE + "/")
    cats = {}  # root_code -> {"name": str, "subs": {cat_code: name}}
    for a in soup.select('a[href*="/kor/mall/list.asp"]'):
        href = a.get("href", "")
        qs = parse_qs(urlparse(href).query)
        root = qs.get("root", [None])[0]
        cat = qs.get("category", [None])[0]
        name = a.get_text(strip=True)
        if not root or not name:
            continue
        entry = cats.setdefault(root, {"name": None, "subs": {}})
        if cat:
            entry["subs"].setdefault(cat, name)
        else:
            if entry["name"] is None:
                entry["name"] = name
    return {k: v for k, v in cats.items() if v["name"]}


def parse_list_page(soup):
    """목록 페이지에서 제품 항목 파싱"""
    items = []
    for a in soup.select('a[href*="view.asp?goodscode="]'):
        dl = a.find("dl")
        if not dl:
            continue
        m = re.search(r"goodscode=(\d+)", a["href"])
        if not m:
            continue
        code = m.group(1)
        img = dl.select_one("dt img")
        h3 = dl.select_one("h3")
        h4 = dl.select_one("h4")
        price1 = dl.select_one("ul.price1")
        price2 = dl.select_one("ul.price2")

        def price_val(ul):
            if not ul:
                return None
            lis = ul.find_all("li")
            return lis[-1].get_text(strip=True) if len(lis) >= 2 else None

        items.append({
            "goodscode": code,
            "model": h3.get_text(strip=True).replace("\xa0", " ").strip() if h3 else "",
            "name": h4.get_text(strip=True) if h4 else "",
            "image": urljoin(BASE, img["src"]) if img and img.get("src") else None,
            "price_monthly": price_val(price1),
            "price_card": price_val(price2),
            "url": urljoin(BASE, a["href"]),
        })
    return items


def max_page(soup):
    """페이지네이션에서 최대 페이지 번호"""
    pages = [1]
    for a in soup.select('div.box_paging a[href*="gopaging"]'):
        m = re.search(r"gopaging\('(\d+)'\)", a["href"])
        if m:
            pages.append(int(m.group(1)))
    return max(pages)


def crawl_category(root, cat=None):
    """한 카테고리의 전체 페이지 크롤링"""
    seen = {}
    page = 1
    while True:
        url = f"{BASE}/kor/mall/list.asp?root={root}"
        if cat:
            url += f"&category={cat}"
        if page > 1:
            url += f"&gopage={page}"
        soup = get_soup(url)
        for it in parse_list_page(soup):
            seen.setdefault(it["goodscode"], it)
        last = max_page(soup)
        if page >= last:
            break
        page += 1
        time.sleep(DELAY)
    return list(seen.values())


def main():
    cats = parse_categories()
    print(f"루트 카테고리 {len(cats)}개 발견:")
    for root, info in cats.items():
        print(f"  root={root} {info['name']} (하위 {len(info['subs'])}개)")

    catalog = []
    total = 0
    for root, info in cats.items():
        root_products_codes = set()
        subs_out = []
        sub_list = list(info["subs"].items()) or [(None, info["name"])]
        for cat, cat_name in sub_list:
            time.sleep(DELAY)
            try:
                items = crawl_category(root, cat)
            except Exception as e:
                print(f"  ! root={root} cat={cat} 실패: {e}")
                continue
            if items:
                subs_out.append({"category": cat, "name": cat_name, "products": items})
                root_products_codes.update(i["goodscode"] for i in items)
                print(f"  {info['name']} > {cat_name}: {len(items)}개")
        total += len(root_products_codes)
        if subs_out:
            catalog.append({"root": root, "name": info["name"], "subcategories": subs_out})

    out = OUT_DIR / "catalog.json"
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n완료: 고유 제품 약 {total}개 → {out}")


if __name__ == "__main__":
    main()
