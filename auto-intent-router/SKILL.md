---
name: auto-intent-router
description: 사용자 자연어 프롬프트를 9개 워크플로우 카테고리 중 하나로 분류 후 해당 복합 스킬을 체이닝. 명령어를 몰라도 "버그 고쳐", "배포하자", "Todo 앱 만들어줘" 같은 자연어로 충분. /auto 슬래시 또는 UserPromptSubmit hook 라벨이 트리거.
---

# auto-intent-router

## When to use

- 사용자가 `/auto "..."` 로 명시 호출
- UserPromptSubmit hook이 `[Auto-routing hint]` 라벨을 주입한 경우
- 사용자가 명령어/스킬 이름 없이 자연어로 작업 요청 (예: "이 버그 고쳐", "리팩터링하자")

## 분류 규칙

| 키워드 패턴 (KR/EN) | 분기 대상 |
|------------|------|
| 새 프로젝트, 처음부터, 0부터, 만들자, scaffold, greenfield | `project-genesis` |
| 기능 추가, 구현해줘, 만들어줘, feature, implement (기존 레포) | `feature-add` |
| 버그, 에러, 안 돼, 고쳐, 이상해, 망가졌, bug, broken, crash, regression | `bug-hunt` |
| 배포, 릴리즈, 올리자, 내보내, ship, PR, release, deploy, canary | `deploy-pipeline` |
| UI, 디자인, 화면, 레이아웃, ux, frontend review, visual | `ui-dual-audit` |
| 보안, 취약점, 공급망, OWASP, vuln, security | `security-audit` |
| 리팩터, 정리, 구조, cleanup, restructure, refactor | `refactor-safe` |
| 회고, 돌아보기, 주간, retro, learn, reflect | `weekly-reflect` |
| 검증, 철저히 검증, 제대로 검증, 적대적 리뷰, 완주검증, 끝까지 멈추지 않는 루프, 믿을 수 있어, 8프로 council, AI 코드 검증, verify thoroughly, adversarial review, trust this build, prove loop terminates | `ai-verification-pipeline` |
| (모호) | ask-for-clarification |

> **`ai-verification-pipeline`는 배타적 카테고리가 아니라 검증 *레이어*다.** 위 표의 다른 분기(특히 `project-genesis` / `feature-add` / `deploy-pipeline`)가 **비-trivial 다중 모듈 빌드·자율 `/loop`·서브에이전트 팬아웃 코드**를 만들 때, 그 워크플로우의 검증 단계로 이 스킬을 체이닝한다. traceability gate(Stage 9)는 그런 빌드에서 항상 실행. 사용자가 위 검증 키워드를 명시했거나, 산출물이 커밋/배포 전 신뢰가 필요하면 단독으로도 발동.

## 동원 자원

- 보조 스킬: `using-superpowers` (Superpowers), `manage-skills` (기존), `writing-skills`, `skill-creator`
- 보조 명령: `/work` (legacy 라우터, 공존), `/gsd`, `/gsd:next`, `/gsd:do`, `/gsd:manager`

## Chain

1. 사용자 프롬프트 읽기 (또는 hook 라벨)
2. 위 표로 의도 분류
3. 해당 복합 스킬 호출: `project-genesis` / `feature-add` / `bug-hunt` / `deploy-pipeline` / `ui-dual-audit` / `security-audit` / `refactor-safe` / `weekly-reflect`
4. 복합 스킬의 체인 실행
5. 완료 후 `/auto-save` 자동 호출 (deploy-pipeline은 자체 포함)

## Guards

- 분류 신뢰도가 낮으면 사용자에게 "이거 X 워크플로우로 보이는데 맞아?" 한 줄 확인
- 사용자가 특정 명령(`/gsd:ship` 등) 직접 호출했으면 라우팅 건너뛰기 (opt-out)
- 체인 중간 실패 시 `/gsd:health`로 상태 점검 후 재개 또는 수동 전환
