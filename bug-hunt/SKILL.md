---
name: bug-hunt
description: 버그·에러·회귀 수정. "버그 고쳐", "에러 있어", "안 돼", "이상해" 같은 표현이 트리거. 기존 bugfix 5단계 + Superpowers systematic-debugging + /gsd:debug + gsd-debugger agent + 회귀 TDD를 전수 체이닝. 증상 수정 금지·ROOT CAUSE 우선 규칙 강제.
---

# bug-hunt

## When to use

- "버그", "에러", "안 돼", "이상해", "망가졌", "crash", "regression"
- 기존 동작이 깨진 상황 (새 기능 구현은 `feature-add`)
- 배포 후 canary 이상 감지 시 (deploy-pipeline에서 자동 호출도 가능)

## 동원 자원

- 스킬: **bugfix** (기존, 5단계 하드게이트), **systematic-debugging** (SP, ROOT CAUSE), **dispatching-parallel-agents** (SP, 3개+ 독립 버그), **verify-implementation** (기존), **xrev** (기존, 빡센 검증), **test-driven-development** (SP, 회귀 테스트), `gstack-investigate` (GStack, 4단계 근본원인)
- 명령: `/gsd:debug`, `/gsd:forensics` (워크플로우 실패 post-mortem), `/gsd:health` (.planning integrity), `/patch` (작은 수정)
- 에이전트: `gsd-debugger` (과학적 방법), `gsd-verifier` (목표 검증), `gsd-nyquist-auditor` (테스트 커버리지), `codex-rescue` (openai-codex 플러그인, 난제 재진단)

## Chain

1. `gstack-investigate` skill — 4단계 근본원인 조사
2. `/gsd:debug` — GSD 디버깅 세션 시작
3. Superpowers `systematic-debugging` — 재현·증거·원인분석 (증상 수정 금지)
4. `bugfix` skill (기존) — 5단계 프로세스:
   재현 → 가설 → 수정 범위 → **사용자 승인** → 구현 + 테스트
5. **복잡도 분기**:
   - 독립 버그 3개+ → Superpowers `dispatching-parallel-agents`
   - 난제 (이전 수정 실패) → `codex-rescue` agent (openai-codex)
   - 일반 버그 → `gsd-debugger` agent
6. Superpowers `test-driven-development` — 회귀 테스트 RED→GREEN
7. `gsd-nyquist-auditor` — 테스트 커버리지 갭 확인
8. `verify-implementation` skill — 모든 verify-* 통합 실행
9. `xrev` skill — 빡센 검증/보완 모드
10. `gsd-verifier` agent — 목표 달성 재검증
11. `/gsd:verify-work`

## Guards

- `bugfix` 스킬의 "사용자 승인 전 구현 금지" 하드게이트 유지
- 범위 초과 버그 발견 시 `/gsd:note`로 캡처 (세션 오염 방지)
- 증상 수정 금지 — 재현 불가능하면 3단계에서 재현 경로 확보까지 반복
- 배포 환경 크리티컬 버그는 `/patch` 빠른 경로 허용 (사용자 승인 후)
