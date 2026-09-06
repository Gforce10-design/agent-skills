---
name: "source-command-release"
description: "Migrated source command `release`"
---

# source-command-release

Use this skill when the user asks to run the migrated source command `release`.

## Command Template

﻿---
allowed-tools: Bash, Read
description: Run the release gate and deploy only when the current project has an explicit deploy entrypoint
disable-model-invocation: false
---

# /release — GSD Release Gate

배포 전 게이트를 확인하고, 현재 프로젝트에 명시적 deploy entrypoint가 있을 때만 배포를 진행합니다.

## 실행 규칙

1. 먼저 아래 파일을 읽습니다.

```text
C:\Users\sudol\VibeCoding(codex)\.planning\harness\RELEASE_GATE.md
C:\Users\sudol\VibeCoding(codex)\.planning\harness\EXAM_REPORT.md
C:\Users\sudol\VibeCoding(codex)\.planning\harness\AUDIT_REPORT.md
```

2. `RELEASE_GATE.md` 첫 판정이 `RELEASE: FAIL`이면 중단하고, 먼저 `/deliver` 또는 `/deliver-deep`를 안내합니다.

3. 현재 프로젝트 디렉토리를 기준으로 아래 deploy entrypoint를 순서대로 찾습니다.
   - `deploy.ps1`
   - `package.json`의 `deploy` script
   - `wrangler.toml` 또는 `wrangler.json*`

4. entrypoint가 있으면 그 경로만 실행합니다.
   - `deploy.ps1` -> `powershell -ExecutionPolicy Bypass -File .\deploy.ps1`
   - `package.json deploy` -> `npm run deploy`
   - `wrangler.*` -> `npx wrangler deploy`

5. entrypoint가 없으면 release-ready 상태까지만 보고하고 배포는 시도하지 않습니다.
