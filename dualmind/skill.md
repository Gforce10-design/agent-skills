---
name: dualmind
description: "Discovery/Validation 전용 엔진. 열린 문제 탐색, 설계 검증, 도구 비교, 벤치마킹에 사용. \"dualmind\", \"교차검증\", \"비교 분석\", \"벤치마킹\" 요청 시 사용."
---

# DualMind Skill

DualMind는 canonical discovery engine입니다.

## 기본 진입점

- 사용자가 엔진을 따로 고르지 않았다면 먼저 `/work`를 기본 진입점으로 봅니다.
- `/work`가 구현보다 탐색/검증이 먼저라고 판단한 경우에만 DualMind route로 보냅니다.

## 기본 라우팅

- 열린 탐색, 대안 비교 -> `/discover`
- 기존 설계/도구 검토 -> `/review`

## 출력

- `C:\Users\sudol\VibeCoding(codex)\.planning\harness\DECISION_PACKET.md`
- macOS/Gforce10: `/Users/gimsuyeong/Developer/VibeCoding/.planning/harness/DECISION_PACKET.md`

## 규칙

- 코드 작성보다 판단과 설계 검증을 우선합니다.
- 결과는 delivery engine이 바로 소비할 수 있는 decision packet이어야 합니다.

