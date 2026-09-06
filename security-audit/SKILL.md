---
name: security-audit
description: 보안·취약점·공급망 감사. "보안", "취약점", "OWASP", "공급망" 트리거. gstack-cso skill (OWASP+STRIDE) + /review DualMind validate + 공급망 체크리스트 + Hermes 수동 감사. 이상 감지 시 패키지 고정 + 프로덕션 차단.
---

# security-audit

## When to use

- 사용자가 "보안", "취약점", "OWASP", "공급망", "security", "vuln"
- 배포 전 의존성·인증·권한 점검
- 공급망 이슈 뉴스 감지 시 (axios npm, litellm PyPI 등)
- 정기 주간 감사 (Hermes와 별개로 수동 집중 감사)

## 동원 자원

- 스킬: `gstack-cso` (GStack, OWASP + STRIDE + 의존성)
- 명령: `/review` (DualMind validate)
- 에이전트: `security-architect` (BKIT 설치 시만)
- 참조 문서: `reference_supply_chain_attacks_2026_04.md` (글로벌 메모리)
- 인프라: Hermes 주간 감사 (수동 트리거 가능)

## Chain

1. `gstack-cso` skill — OWASP Top 10 + STRIDE + 의존성 스캔
2. `/review` (DualMind validate) — 설계/도구 검증 모드
3. `reference_supply_chain_attacks_2026_04.md` 체크리스트 실행 (axios/litellm 같은 알려진 패턴)
4. (BKIT 설치 시) `security-architect` agent 호출
5. Hermes audit 수동 트리거 (`hermes audit`) — 1회 전체 감사
6. 결과 Obsidian `raw/dev/Codex-YYYY-MM-DD-security-audit.md` ingest

## Guards

- 공급망 이상 감지 시 즉시 패키지 버전 고정 (package-lock / poetry.lock)
- `deploy-pipeline` 에서 `gstack-cso` 실패 시 이 스킬 자동 호출
- 프로덕션 배포 차단 트리거 (cso 심각도 critical 시)
- 발견된 취약점은 팀·사용자에게 메시지로 즉시 공유 (Telegram α No.1 등)
