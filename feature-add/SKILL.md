---
name: feature-add
description: 기존 레포에 새 기능을 추가할 때 호출. "기능 추가", "구현해줘", "만들어줘" + 기존 .git 레포 감지. discover→research→plan→phase→구현(subagent or execute-phase or harness)→TDD→리뷰→검증 12단계 체인. 가치투자 로직 같은 결정적 코드는 TDD 필수 적용.
---

# feature-add

## When to use

- 기존 레포 (`.git` 존재) 에 새 기능·모듈 추가
- 사용자가 "기능 추가", "구현", "만들어줘", "feature"
- 신규 레포는 `project-genesis` 사용

## 동원 자원

- 스킬: `harness` (기존, canonical delivery), `writing-plans` (SP), `subagent-driven-development` (SP), `executing-plans` (SP), `test-driven-development` (SP), `using-git-worktrees` (SP), `requesting-code-review` (SP), `receiving-code-review` (SP), `verification-before-completion` (SP)
- 명령: `/deliver`, `/deliver-deep` (고위험), `/gsd:add-phase`, `/gsd:add-todo`, `/gsd:add-tests`, `/gsd:plan-phase`, `/gsd:execute-phase`, `/gsd:autonomous`, `/gsd:do`, `/gsd:verify-work`, `/discover`
- 에이전트: `gsd-planner`, `gsd-executor`, `gsd-phase-researcher`, `gsd-plan-checker`, `gsd-advisor-researcher`, `gsd-integration-checker`

## Chain

1. `/discover` (DualMind) — 영향 범위·기존 패턴 탐색
2. `gsd-phase-researcher` agent — `RESEARCH.md` 사전 연구
3. (선택) Superpowers `brainstorming` — 복잡 기능일 때만
4. Superpowers `writing-plans` — `docs/superpowers/plans/`
5. `gsd-plan-checker` agent — 목표역방 계획 품질 검증
6. `/gsd:add-phase` — 마일스톤에 phase 추가
7. **분기**:
   - 복잡 기능 → Superpowers `subagent-driven-development` (implementer → spec-review → quality-review, fresh context per task)
   - 단순 기능 → `/gsd:execute-phase` (wave-parallel)
   - harness 스타일 → `/deliver` 또는 `/deliver-deep`
8. Superpowers `test-driven-development` — RED→GREEN→REFACTOR 결정적 로직
9. Superpowers `requesting-code-review` — subagent `code-reviewer` 파견
10. `gsd-integration-checker` agent — E2E 흐름 검증
11. Superpowers `verification-before-completion` — 증거 기반 완료 선언
12. `/gsd:verify-work` — 최종 목표 검증

## Guards

- 가치투자 로직·금융 계산 등 신뢰도 결정적 코드는 TDD 필수 (8단계 스킵 금지)
- 단순 UI 조정은 TDD 스킵 허용 (사용자 확인 후)
- 웹챗 브레인스토밍 결과 있으면 3단계 대신 기존 spec 활용
- 큰 아키텍처 변경 감지 시 `refactor-safe` 로 전환
