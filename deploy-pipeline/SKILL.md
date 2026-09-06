---
name: deploy-pipeline
description: 배포·릴리즈·PR·ship 워크플로우. "배포하자", "release", "ship" 트리거. 13단계: health→verify-work→cso→finishing→merge-worktree→pr-branch→ship→release→verify→merge-to-master→canary→document→auto-save. cso 실패 시 배포 차단, canary 이상 시 즉시 롤백.
---

# deploy-pipeline

## When to use

- 사용자가 "배포", "릴리즈", "올리자", "내보내", "ship", "PR" 표현
- 기능 구현이 완료되어 master 브랜치 병합·배포 단계
- canary 후 정리 단계 (또는 복합 스킬 체인 말미)

## 동원 자원

- 스킬: `harness` (canonical delivery), `finishing-a-development-branch` (SP, merge/PR/discard), `using-git-worktrees` (SP), `merge-worktree` (기존, squash-merge), `executing-plans` (SP), `gstack-health` (GStack), `gstack-cso` (GStack), `gstack-land-and-deploy` (GStack), `gstack-canary` (GStack), `gstack-document-release` (GStack), `verify` (빌드+테스트+UI 실동작 검증), `merge-to-master` (dev→master 머지 + G3 배포 + smoke check)
- 명령: `/release` (기본 게이트), `/gsd:ship`, `/gsd:pr-branch` (.planning 필터링), `/auto-save` (세이브+동기화), `/verify` (실동작 검증), `/merge-to-master` (운영 배포)
- 에이전트: `infra-architect` (BKIT 설치 시)

## Chain

1. `gstack-health` skill — 타입·린트·테스트·데드코드 점수
2. `/gsd:verify-work` — Phase 목표 달성 확인
3. `gstack-cso` skill — OWASP + 공급망 체크 (배포 전 필수)
4. Superpowers `finishing-a-development-branch` — merge/PR/discard 결정
5. `merge-worktree` skill — 워크트리 사용 시 squash-merge
6. `/gsd:pr-branch` — `.planning/` 필터링 clean PR branch
7. `/gsd:ship` — PR 생성 + review + merge 준비
8. `/release` — 배포 entrypoint 최종 확인
9. `/verify` — 빌드+테스트+UI 실동작 검증
10. `/merge-to-master` — dev→master 머지 + G3 배포 + smoke check
11. `gstack-canary` skill — 10분 모니터링
12. `gstack-document-release` skill — 문서 동기화
13. `/auto-save` — 세이브 파이프라인 (3-PC 동기화, Obsidian ingest)

## Guards

- `gstack-cso` 실패 시 배포 차단 (3단계에서 중단)
- canary 이상 감지 시 즉시 `bug-hunt` 로 전환 + 롤백 고려
- master 브랜치만 배포 대상. dev 브랜치 감지 시 사용자 확인
- `/verify` PASS 필수 — `/merge-to-master` 진입 전 검증 통과해야 함
- `/auto-save` 는 WORKLOG → HANDOFF → git → remote sync → Obsidian 순서 자동
- G3·A8·Desktop 3-PC 동기화 누락 0개 보장 (6.5단계 검증 테이블 필수)
