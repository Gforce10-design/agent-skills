---
name: harness
description: "Codex-first delivery engine. 새 기능 구현, 일반 구현, 패치, 릴리즈 게이트에 사용. \"하네스로 구현해\", \"deliver\", \"patch\", \"release\" 요청 시 사용."
---

# Harness Skill

Harness는 이제 canonical delivery engine입니다.

## 기본 진입점

- 사용자가 엔진을 따로 고르지 않았다면 먼저 `/work`를 기본 진입점으로 봅니다.
- `/work`가 patch / deliver / deliver-deep / release 중 가장 싼 충분한 경로를 고릅니다.
- 사용자가 특정 엔진을 명시했을 때만 해당 엔진을 강제로 탑니다.

## 기본 라우팅

- 일반 구현 -> `/deliver`
- 고위험/대형 작업 -> `/deliver-deep`
- 기존 기능 수정/보완 -> `/patch`
- 배포 게이트/배포 -> `/release`

## 핵심 규칙

- 별도 UltraThink 엔진을 추가로 만들지 말고 `deliver-deep`의 deep architect profile로 처리합니다.
- xrev, verifier, auditor는 별도 파이프라인으로 흩뿌리지 말고 examiner/release gate에 흡수합니다.
- OAuth 토큰/쿠키 파일은 직접 읽지 않습니다.

