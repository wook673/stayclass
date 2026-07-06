# 모션 연출 시스템 설계서 (Claude-디렉티드 애니메이션)

사진(스톡/AI생성) 위에 코드로 만든 애니메이션을 얹어, 내레이션 스토리에
맞춰 화면을 연출하는 시스템. AI 영상 생성 API 없이(무료) "움직이는
스토리텔링 영상"을 만든다.

## 핵심 설계 사상: "연출 대본(direction.json)" 분리

지금 파이프라인은 "무엇을 보여줄지(소재)"만 다뤘다. 여기에
**"어떻게 보여줄지(연출)"를 별도 데이터로 분리**한다.

```
script.txt   →  무엇을 말하는가        (작가)
state.json   →  언제 말하는가(타이밍)   (편집기사)
direction.json → 어떻게 보여주는가(연출) (감독 = Claude)   ← 신규
```

Claude(채팅, Max 요금제 포함 = 추가비용 0원)가 대본을 읽고 장면마다
"여기는 줌인, 여기는 숫자 카운트업, 이 단어는 강조" 같은 연출을
direction.json으로 작성한다. 렌더러(코드)는 그 지시대로만 그린다.

→ 연출을 바꾸고 싶으면 코드가 아니라 direction.json만 고치면 된다.
→ Claude가 프로젝트마다 다른 연출을 설계할 수 있다 (스토리 맞춤).

## direction.json 스키마 (연출 계약)

```json
{
  "style": "docu",                  // 전체 톤 프리셋: docu|vlog|info|brand
  "bgm": {"path": "", "volume": 0.12, "duck": true},
  "scenes": [
    {
      "index": 0,
      "media": {"type": "stock"},   // stock(영상) | photo(사진) | ai(생성이미지)
      "motion": {                   // 사진일 때 켄번스, 영상일 때 speed/crop
        "type": "kenburns",
        "zoom": "in",               // in | out | none
        "pan": "left",              // left | right | up | down | none
        "strength": 1.1             // 최종 배율 (1.05 은은 ~ 1.25 강함)
      },
      "transition": {"type": "fade", "dur": 0.5},
                                    // fade | slideleft | zoomin | wipeleft |
                                    // circleopen | fadeblack (ffmpeg xfade 계열)
      "subtitle": {
        "anim": "fadeup",           // none | fadeup | pop | typing(2단계)
        "highlight": ["92%"],       // 강조 단어(색상 변경)
        "position": "bottom"        // bottom | center(타이틀용)
      },
      "overlays": [                 // 2단계 모션그래픽 (0개 이상)
        {"type": "countup", "to": 420, "suffix": "만원", "at": 0.3, "dur": 1.2},
        {"type": "lowerthird", "title": "정욱진", "sub": "다니엘스테이 대표", "at": 0.0}
      ]
    }
  ]
}
```

규칙:
- direction.json이 없으면 → 렌더러가 style 프리셋으로 기본 연출 자동 생성
  (사진=켄번스 랜덤방향, 전환=fade 0.4s). 즉 **연출 파일은 선택사항**.
- scene index는 state.json의 장면과 1:1 대응.
- 렌더러가 모르는 필드는 무시(전방호환).

## 렌더링 아키텍처 (2단 레이어)

```
[레이어 1: 베이스 영상]  FFmpeg만 사용 (1단계 범위)
  사진 → zoompan(켄번스) → 장면클립
  영상 → trim/scale       → 장면클립
  장면클립들 → xfade 체인(장면별 전환) → base.mp4

[레이어 2: 그래픽 오버레이]  (2단계 범위)
  자막: ASS 포맷(libass) — 페이드/팝/타이핑/단어색상 애니메이션 내장
  모션그래픽: HTML/CSS 템플릿 → Playwright(헤드리스 크롬)로
             투명배경 WebM/PNG시퀀스 렌더 → FFmpeg overlay로 합성
  오디오: 내레이션 + BGM 덕킹(sidechaincompress: 말할 때 음악 자동 감소)
```

### 왜 자막을 SRT→ASS로 바꾸나
SRT는 "글자 띄우기"만 가능. ASS는 자막 자체에 애니메이션 태그가 있어
FFmpeg(libass)만으로 페이드인·팝업·이동·단어별 색상·정확한 위치제어가
된다. 추가 설치 0개로 자막 연출력이 방송 수준으로 올라간다.

### 왜 모션그래픽을 HTML/CSS로 만드나
로어써드·카운트업·키네틱 타이포는 FFmpeg 필터로 짜면 지옥이다.
HTML/CSS 애니메이션으로 짜면 Claude가 가장 잘 다루는 언어라 품질이
높고, Playwright로 투명배경 녹화 → FFmpeg overlay 한 줄로 합성된다.
requestAnimationFrame을 가상시계로 돌려 프레임 단위 정확 렌더 가능.

## 파일 구조 (증분 — 기존 구조 유지)

```
video-maker/
  pipeline/
    direct.py        # direction.json 로드/기본연출 자동생성   [1단계]
    motion.py        # 사진 켄번스, 영상 트림 (build_clips 대체) [1단계]
    transitions.py   # xfade 체인 조립                        [1단계]
    subtitle_ass.py  # scenes+direction → .ass 자막 생성       [1단계]
    assemble.py      # (수정) base + ass + 오디오덕킹          [1단계]
    mograph/                                                  [2단계]
      render.py      # Playwright로 HTML→투명 WebM 렌더
      templates/
        lowerthird.html   # 이름/직함 하단바
        countup.html      # 숫자 카운트업
        titlecard.html    # 오프닝 타이틀
        chart.html        # 간단 막대/추이 그래프
  projects/<이름>/
    direction.json   # (선택) Claude가 쓰는 연출 대본
```

## 스타일 프리셋 (direction.json 없을 때의 기본값)

| 프리셋 | 켄번스 | 전환 | 자막 | 용도 |
|--------|--------|------|------|------|
| docu   | 느린 zoom-in 1.08 | fadeblack 0.6s | fadeup, 흰+노랑강조 | 다큐/스토리 |
| vlog   | 팬 위주 1.12 | slideleft 0.35s | pop, 두꺼운 외곽선 | 일상/후기 |
| info   | zoom-out 1.10 | fade 0.4s | fadeup + 로어써드 | 정보전달 |
| brand  | 아주 느린 1.05 | circleopen 0.7s | center 타이틀형 | 소개/브랜드 |

## 스토리-싱크 원리 (이 시스템의 심장)

TTS 경계 타이밍(voice.words.json) 덕분에 각 문장의 시작·끝 초를
정확히 안다. 연출은 전부 그 타이밍에 걸린다:

- 장면 전환 = 문장 경계에서 발생 (이미 구현됨)
- overlay의 `at`(등장시점)은 장면 시작 기준 상대초 → 절대초로 환산
- 강조 단어 하이라이트는 그 단어가 포함된 자막 표시 구간에 적용
- BGM 덕킹은 내레이션 파형 자체에 반응(자동)

→ "매출 420만 원" 문장이 나오는 순간 화면에 0→420 카운트업이 뜨는
   식의 '말과 그림이 맞물리는' 연출이 데이터만으로 성립한다.

## AI 이미지와의 관계 (선택 결합)

media.type="ai"인 장면은 fetch_media에서 분기해 이미지 생성 API를
호출하고, 이후 처리는 photo와 동일(켄번스). 즉 **이 설계는 이미지
출처와 무관**하다 — 지금은 무료 스톡으로 시작하고, 나중에 유료 이미지
API 키가 생기면 direction.json에서 type만 "ai"로 바꾸면 된다.

## 구현 순서와 검증 계획

| 순서 | 작업 | 검증 |
|------|------|------|
| 1 | direct.py + 스키마, 기본연출 자동생성 | direction.json 생성 확인 |
| 2 | motion.py 켄번스 (사진 1장→움직이는 6초 클립) | 프레임 2장 비교(줌 확인) |
| 3 | transitions.py xfade 체인 | 전환 구간 프레임 확인 |
| 4 | subtitle_ass.py (fadeup/pop/하이라이트) | 프레임에서 자막스타일 확인 |
| 5 | assemble 통합 + BGM 덕킹 | daniel-intro 재생성 before/after |
| 6 | (2단계) Playwright 설치 + lowerthird/countup | 오버레이 합성 프레임 확인 |
| 7 | (2단계) titlecard/chart, 프리셋 4종 완성 | 스타일별 샘플 영상 |

의존성: 1~5단계 추가 설치 **0개**(FFmpeg에 xfade/zoompan/libass 내장).
6~7단계만 `pip install playwright` + 크로미움 다운로드(~150MB).

## 한계(정직하게)

- 정지 이미지 기반 모션디자인이다. 인물이 걷고 말하는 실사 AI 영상이
  필요하면 이 시스템 밖(유료 Runway/Veo 등)이며, 그 경우에도
  media.type="ai_video"로 같은 계약에 끼워넣을 수 있게 자리를 남긴다.
- zoompan은 저해상도 사진에서 화질 저하 → 소재는 1920px 이상 권장,
  줌 배율 1.25 상한.
- xfade는 전환 시간만큼 클립이 겹쳐야 함 → 장면 길이가 전환보다 짧으면
  전환을 자동 축소하는 가드 필요(구현 시 포함).
