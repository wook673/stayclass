# 롱폼 영상 자동제작 파이프라인 (설계도)

대본 + 본인 녹음 → 자막·스톡영상 자동매칭 → 완성 롱폼 MP4

## 전체 흐름

```
[입력]
  script.txt      ← 대본 (장면 구분: 빈 줄)
  voice.mp3       ← 본인이 직접 녹음한 음성 (대본 전체를 읽은 것)
  config.json     ← API키, 화면비율, 폰트 등 설정
      │
      ▼
① transcribe.py   녹음(mp3) → Whisper → 타이밍 박힌 자막(segments)
      │           "어느 문장이 몇 초~몇 초에 나오는지" 확보
      ▼
② segment.py      자막 타이밍 + 대본 → 장면(scene) 단위로 분할
      │           각 장면의 검색 키워드 추출 (예: "서울 야경", "커피")
      ▼
③ fetch_media.py  장면 키워드로 Pexels 검색 → 영상/사진 다운로드
      │           (AI 영상 자리도 여기에 — 지금은 스톡만)
      ▼
④ build_clips.py  장면별: 소재를 음성 타이밍 길이에 맞춰 클립화
      │           (사진은 켄번스 줌, 영상은 트림)
      ▼
⑤ assemble.py     클립 concat + 자막 burn-in + 배경음악 믹스
      │
      ▼
[출력] output/final.mp4   완성된 롱폼 영상
```

## 모듈 인터페이스 (계약)

각 모듈은 **JSON 한 덩어리(state)**를 주고받습니다. 중간 결과가 파일로 남아
어디서 멈춰도 그 지점부터 다시 시작할 수 있습니다.

```
state = {
  "scenes": [
    {
      "index": 0,
      "text": "안녕하세요, 오늘은...",   # 자막 문장
      "start": 0.0, "end": 4.2,         # 음성 타이밍(초)
      "keywords": ["서울", "도시"],      # 검색어 (②에서 채움)
      "media_path": "assets/clip_0.mp4", # 소재 경로 (③에서 채움)
      "clip_path": "work/clip_0.mp4"     # 가공 클립 (④에서 채움)
    },
    ...
  ]
}
```

## 폴더 구조

```
video-maker/
  make_video.py        ← 오케스트레이터 (전체 순서 실행)
  config.example.json  ← 설정 템플릿
  pipeline/
    transcribe.py      ① 녹음 → 자막
    segment.py         ② 장면 분할 + 키워드
    fetch_media.py     ③ 스톡 다운로드
    build_clips.py     ④ 장면 클립화
    assemble.py        ⑤ 최종 합성
  inputs/   (script.txt, voice.mp3 넣는 곳)
  work/     (중간 산출물 - state.json, 클립들)
  assets/   (다운로드된 스톡 소재)
  output/   (final.mp4)
```

## 무료 도구 매핑

| 단계 | 도구 | 비용 |
|------|------|------|
| 자막 | faster-whisper | 무료 (로컬) |
| 키워드 | 규칙기반/로컬 | 무료 |
| 스톡 | Pexels API | 무료 (키 발급) |
| 합성 | FFmpeg | 무료 |
| AI 영상 | (자리만) Runway 등 | 나중에 유료 |

## 실행

```
python make_video.py            # 전체 실행
python make_video.py --from 3   # 3단계부터 재시작
```
