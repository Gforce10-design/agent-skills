---
name: "source-command-auto"
description: "자연어 의도 분석 후 9개 복합 워크플로우 스킬 중 하나로 자동 분기. 명령어 모를 때 사용. 예 /auto \"이 버그 고쳐줘\" /auto \"배포하자\" /auto \"Todo 앱 만들어줘\""
---

# source-command-auto

Use this skill when the user asks to run the migrated source command `auto`.

## Command Template

# /auto

사용자가 제시한 자연어 요청을 `auto-intent-router` 스킬에 전달한다.

## 동작

1. 입력 텍스트를 `auto-intent-router` SKILL.md 의 분류 규칙으로 판별
2. 해당 카테고리의 복합 스킬 호출 (project-genesis / feature-add / bug-hunt / deploy-pipeline / ui-dual-audit / security-audit / refactor-safe / weekly-reflect)
3. 복합 스킬의 Chain 섹션을 따라 단계별 실행
4. 완료 후 `/auto-save` 자동 호출 (deploy-pipeline 체인은 자체 포함)

## 사용 예

- `/auto Todo 앱 만들어줘` → project-genesis
- `/auto 이 함수 버그 있어` → bug-hunt
- `/auto 배포하자` → deploy-pipeline
- `/auto 이 화면 리뷰` → ui-dual-audit
- `/auto 리팩터링` → refactor-safe
- `/auto 이번주 돌아보자` → weekly-reflect

## 명령어 직접 호출과 공존

`/gsd:ship` 슬래시 명령, `gstack-health` 등 GStack 스킬 직접 호출은 그대로 동작. 자동 라우팅은 opt-out 가능.

## 관련

- Skill: `auto-intent-router`
- Hook: `~/.Codex/hooks/auto-intent-classifier.js` (UserPromptSubmit, 슬래시 없이 자연어만 써도 힌트 주입)
