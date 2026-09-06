---
name: xrev
description: "독립 엔진이 아니라 strict examiner 규칙 세트. 구현 수정 후 빡센 검증이 필요할 때 patch/deliver examiner를 엄격 모드로 사용."
---

# xrev Skill

xrev는 이제 독립 3단계 리뷰 파이프라인이 아니라 examiner strict 규칙 세트입니다.

## 라우팅

- 구현 후 빡센 검증/보완 -> `/patch`
- 큰 작업 후 빡센 검증까지 포함 -> `/deliver-deep`

## 규칙

- codex rescue, adversarial review, verifier 관점은 examiner 내부에서 한 번에 처리합니다.
- 별도 xrev 루프를 다시 돌려 토큰을 이중 소비하지 않습니다.

