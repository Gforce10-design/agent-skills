---
name: weekly-reflect
description: 주간 회고·학습·행동 프로필 갱신. "회고", "돌아보자", "이번주 정리" 트리거. gstack-retro skill + /gsd:session-report + gsd-user-profiler + gstack-learn skill + Obsidian ingest 8단계. 일주일 커밋 없으면 /gsd:progress 단독 경로.
---

# weekly-reflect

## When to use

- 사용자가 "회고", "돌아보기", "이번주", "주간 정리", "retro", "reflect"
- 일주일 단위 습관적 실행 (매주 일요일 등)
- 큰 이정표 완료 직후 학습 정리

## 동원 자원

- 스킬: `dualmind` (기존, 의사결정 회고), `gstack-retro` (GStack), `gstack-learn` (GStack)
- 명령: `/gsd:progress` (점검), `/gsd:session-report` (SESSION_REPORT.md), `/gsd:note` (idea 캡처), `/gsd:thread` (크로스세션 맥락), `/handoff`
- 에이전트: `gsd-user-profiler` (8차원 행동 프로필)

## Chain

1. `gstack-retro` skill — 주간 커밋 분석
2. `/gsd:session-report` — 토큰·작업 요약
3. `gsd-user-profiler` agent — 8차원 행동 프로필 갱신
4. `gstack-learn` skill — `~/.gstack/projects/{SLUG}/learnings.jsonl` 저장
5. `dualmind` skill — 의사결정 합성·회고 작성
6. Obsidian `raw/dev/Codex-YYYY-WW-retro.md` ingest
7. AlphaVaults 정제 트리거 (자동 포스트-수집)
8. `/handoff` — `HANDOFF.md` 갱신

## Guards

- 일주일 분량 커밋 없으면 `gstack-retro` 대신 `/gsd:progress` 단독 경로
- 학습 저장 파일이 비어있어도 생성 (다음 주 누적용)
- 주간이 아니라 월간/분기 회고가 필요하면 사용자 확인 후 범위 확장
- AlphaVaults 에러 시 Obsidian raw/만 저장하고 나중에 컴파일
