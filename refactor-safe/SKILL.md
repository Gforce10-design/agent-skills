---
name: refactor-safe
description: 안전 리팩터링·코드 정리·구조 개선. "리팩터", "정리", "구조" 트리거. worktree 격리→코드베이스 맵→분업 병렬→회귀 TDD→code review→diff 검증→finishing. 테스트 없는 파일은 리팩터 전 회귀 테스트 추가 강제.
---

# refactor-safe

## When to use

- 사용자가 "리팩터", "정리", "구조 개선", "cleanup", "restructure"
- 기존 기능 동작 유지하며 내부 구조만 변경
- 큰 아키텍처 변경은 `project-genesis` 또는 `feature-add` 우선 고려
- 버그로 인한 구조 변경은 `bug-hunt` 먼저

## 동원 자원

- 스킬: `using-git-worktrees` (SP, 격리), `subagent-driven-development` (SP, 병렬 분업), `test-driven-development` (SP, 회귀 방지), `receiving-code-review` (SP), `finishing-a-development-branch` (SP), `manage-skills` (기존), `xrev` (빡센 검증), `/ultrathink` (사용자 명시 호출, 대형 아키텍처용 deep-thinking)
- 명령: `/discover` (영향 범위), `/patch` (작은 수정), `/review` (최종 diff), `/gsd:map-codebase`, `/gsd:cleanup`, `/gsd:remove-phase`
- 에이전트: `gsd-codebase-mapper` (focus 분석), `code-reviewer` (Superpowers, 계획 vs 코드 품질)

## Chain

1. Superpowers `using-git-worktrees` — 격리 작업 공간 생성
2. `/discover` 또는 `/gsd:map-codebase` — 영향 범위 분석
3. `gsd-codebase-mapper` agent — tech/arch/quality focus 문서
4. **분기**:
   - 대형 아키텍처 변경 → `/ultrathink` 슬래시 명령 (사용자 명시 호출) 경유
   - 일반 리팩터 → 5단계부터
5. Superpowers `subagent-driven-development` — 병렬 분업
6. Superpowers `test-driven-development` — 회귀 방지 테스트
7. `xrev` skill (기존) — 빡센 검증 모드
8. `code-reviewer` agent (Superpowers) — 계획 vs 코드 품질
9. `/review` (DualMind) — 최종 diff 종합 검증
10. Superpowers `finishing-a-development-branch` — worktree 정리 + PR

## Guards

- 테스트 없는 파일은 리팩터 전 TDD로 회귀 테스트 먼저 추가 (6단계 우선)
- 대규모 리팩터는 `/ultrathink` 슬래시 명령 (사용자 명시 호출) 경유 필수 (건너뛰기 금지)
- worktree 정리 실패 시 `merge-worktree` skill 수동 호출
- 배포 대기 중인 변경과 충돌 시 사용자에게 병합 전략 확인
