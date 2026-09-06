---
name: ui-dual-audit
description: UI·디자인·화면 리뷰 이중 감사. "UI 리뷰해줘", "디자인 봐줘", "화면 점검" 트리거. 라이브 DOM(gstack-design-review skill) + 정적 코드(gsd-ui-auditor) + UI-SPEC 계약(gsd-ui-checker) 3축 교차. BLOCK 판정 시 배포 차단.
---

# ui-dual-audit

## When to use

- 사용자가 "UI", "디자인", "화면", "레이아웃", "frontend review", "visual"
- 프론트엔드 코드 변경 직후 품질 감사
- 배포 전 UI-SPEC 계약 위반 확인

## 동원 자원

- 스킬: `frontend-design` (Superpowers, 제작 수준 구현), `gstack-design-review` (GStack, 라이브 DOM)
- 명령: `/gsd:ui-phase` (UI-SPEC.md 생성), `/gsd:ui-review` (6-pillar)
- 에이전트: `gsd-ui-auditor` (정적 코드 감사, UI-REVIEW.md), `gsd-ui-checker` (UI-SPEC 계약 검증, BLOCK/FLAG/PASS), `gsd-ui-researcher` (설계시스템 감지)

## Chain

1. **분기**:
   - 신규 화면 → `/gsd:ui-phase` (UI-SPEC.md 생성) + `gsd-ui-researcher` agent
   - 기존 화면 검사 → 2단계부터
2. `gstack-design-review` skill — Chromium 라이브 5-8페이지 감사
3. `gsd-ui-auditor` agent — 정적 코드 감사 (6 pillar)
4. `gsd-ui-checker` agent — UI-SPEC 계약 검증 (BLOCK/FLAG/PASS 판정)
5. `/gsd:ui-review` — retroactive 종합 감사
6. Superpowers `frontend-design` — 수정 필요 시 제작 수준 구현
7. 교차 리포트 생성: static + live + spec 3축 비교

## Guards

- `gsd-ui-checker` BLOCK 판정 → `deploy-pipeline` 진입 금지
- UI-SPEC.md 없는 신규 화면은 1단계부터 시작 (2단계 건너뛰기 금지)
- Chromium 프로세스 누수 방지: `/auto-save` 말미에 `pkill -f "gstack.*chrome"` (선택)
- 결과는 `docs/ui-audit/YYYY-MM-DD.md` 저장 + Obsidian raw/dev/ ingest
