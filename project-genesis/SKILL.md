---
name: project-genesis
description: 0→1 신규 프로젝트를 시작할 때 호출. "새 프로젝트 시작", "0부터 만들자", "Todo 앱 만들어줘" 같이 빈 레포에서 출발해야 하는 경우. CEO 역질문→spec→plan→메가리뷰→GSD 워크스페이스 생성까지 10단계 체인.
---

# project-genesis

## When to use

- 빈 디렉토리 또는 방금 만든 신규 레포
- 사용자가 "처음부터", "0부터", "새 프로젝트", "scaffold" 유사 표현
- 요구사항이 아직 구체화되지 않은 상태 (아이데이션 단계)

기존 레포에 기능 추가는 `feature-add` 사용.

## 동원 자원

- 스킬: `brainstorming` (Superpowers, spec 생성), `writing-plans` (Superpowers), `dualmind` (기존, Discovery), `webchat-brainstorm-bridge` (기존), `/ultrathink` (사용자 명시 호출 시, 대형 아키텍처용 deep-thinking 스킬), `gstack-office-hours` (GStack), `gstack-plan-ceo-review` (GStack)
- 명령: `/discover`, `/brainstorm-webchat`, `/gsd:new-project`, `/gsd:new-milestone`, `/gsd:plant-seed`
- 에이전트: `gsd-project-researcher`, `gsd-research-synthesizer`, `gsd-roadmapper`, `gsd-assumptions-analyzer`

## Chain

1. `gstack-office-hours` skill — YC 스타일 CEO 역질문 (15-20분, 요구사항 구체화)
2. `/discover` (DualMind) — 기존 생태계·대안 비교 탐색
3. Superpowers `brainstorming` skill — `docs/superpowers/specs/` spec 문서화
4. Superpowers `writing-plans` skill — 단계별 plan 생성
5. `gsd-project-researcher` agent — 도메인 생태계 연구
6. `gsd-research-synthesizer` agent — 병렬 연구 출력 통합
7. `gsd-roadmapper` agent — 로드맵 + 페이즈 분해
8. `gstack-plan-ceo-review` skill — 11단계 메가리뷰 (최종 검증)
9. `/gsd:new-project` — GSD 워크스페이스 생성
10. `/gsd:new-milestone` — 첫 마일스톤 세팅

## Guards

- 큰 아키텍처 결정이 필요하면 3-4단계 사이에 `/ultrathink` 슬래시 명령 (사용자 명시 호출) 경유
- 사전 연구가 불충분하면 5-7단계 반복
- CEO 역질문에서 사용자가 답답해하면 2-4단계만 돌리고 바로 9단계로 스킵 허용
- 웹챗에서 브레인스토밍한 내용 있으면 1단계 대신 `/brainstorm-webchat` 시작
