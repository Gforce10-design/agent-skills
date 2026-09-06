---
name: "source-command-gsd"
description: "Migrated source command `gsd`"
---

# source-command-gsd

Use this skill when the user asks to run the migrated source command `gsd`.

## Command Template

﻿---
allowed-tools: Bash, Read
description: Route legacy GSD workflow requests to the new canonical engines
disable-model-invocation: false
---

# /gsd — Workflow Router

GSD는 이제 reasoning 엔진이 아니라 workflow/release 라우터입니다.

## 기본 매핑

- `quick` -> `/patch`
- `debug` -> `/review`
- `execute-phase` -> `/deliver`
- `release` -> `/release`

## 사용법

- `/gsd quick <요청>`
- `/gsd debug <요청>`
- `/gsd execute-phase <요청>`
- `/gsd release`

## 실행 규칙

1. 인자가 없으면 위 매핑을 보여줍니다.
2. `quick`이면 `/patch` 흐름으로 실행합니다.
3. `debug`이면 `/review` 흐름으로 실행합니다.
4. `execute-phase`이면 `/deliver` 흐름으로 실행합니다.
5. `release`이면 `/release` 흐름으로 실행합니다.
