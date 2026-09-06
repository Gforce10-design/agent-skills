---
name: "source-command-handoff"
description: "Migrated source command `handoff`"
---

# source-command-handoff

Use this skill when the user asks to run the migrated source command `handoff`.

## Command Template

﻿# Handoff — 진행 상태 자동 갱신

v5_CLI_handoff.md의 "현재 진행 상태" 섹션을 현재 작업 컨텍스트 기반으로 갱신한다.

## 대상 파일

```
C:\Users\sudol\Vibe Coding\AlphaMate Archive\AlphaMate v5\v5 프로젝트 지침 및 지식\v5_CLI_handoff.md
```

## 갱신 대상

파일 내 아래 테이블을 찾아서 값을 교체한다:

```markdown
## 2. 현재 진행 상태

| 항목 | 값 |
|------|-----|
| 현재 Phase | **[값]** |
| 마지막 완료 TASK | [값] |
| 마지막 커밋 | [값] |
| 알려진 이슈 | [값] |
```

## 값 결정 방법

1. **현재 Phase**: 이번 세션에서 작업 중인 TASK-ID에서 추출 (TASK-2-03 → Phase 2). Phase 사이라면 "Phase N 완료, Phase N+1 대기"로 기록.
2. **마지막 완료 TASK**: 이번 세션에서 완료+검증된 마지막 TASK-ID. 없으면 기존 값 유지.
3. **마지막 커밋**: `git log -1 --oneline` 실행 결과 (해시 + 메시지).
4. **알려진 이슈**: 세션 중 발견된 블로커, 실패, [UNRESOLVED]. 없으면 "-".

## 실행 순서

1. handoff 파일을 Read로 읽는다
2. `git log -1 --oneline` 실행
3. 대화 컨텍스트에서 Phase/TASK 상태 파악
4. Edit 도구로 테이블 값 교체
5. 단독 호출 시: handoff 파일만 커밋 (`chore: update handoff progress`)
6. auto-save 호출 시: 다른 변경사항과 함께 커밋에 포함

## auto-save 연동

`/auto-save` 실행 시 git commit 직전에 이 커맨드를 먼저 수행한다.
순서: handoff 갱신 → git add → commit → push
