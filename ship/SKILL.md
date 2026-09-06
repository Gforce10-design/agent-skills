---
name: ship
description: "AlphaMate 경량 배포 체인. /verify → /merge-to-master → /데브 자동 연결. 사용자가 '베리파잉', '배포', '쉽', 'ship'으로 트리거하면 세 스킬을 순차 실행하고 중간 실패 시 안전하게 abort."
---

# ship

dev 브랜치의 변경을 `/verify` → `/merge-to-master` → `/데브` 순으로 한 번에 통과시킨다. 각 sub-skill의 safety gate는 그대로 존중하며, 어느 단계든 실패하면 `.verify-pass`가 자동 무효화되고 사용자에게 즉시 리포트한다.

## 언제 쓰나

사용자가 아래 표현을 쓸 때 (명시적 호출 없어도 자동 라우팅 가능):
- "베리파잉", "베리파잉해", "verify 시작"
- "배포", "쉽", "ship"
- "머지-배포-데브 한번에"

본인이 bugfix/feature 이후 "이거 올리자" 같은 흐름이면 이 스킬이 맞다. 정식 PR 흐름이나 canary가 필요하면 `deploy-pipeline` 스킬을 쓴다 (13단계 전체).

## 전제조건 (Prerequisites)

```bash
set -euo pipefail

# 1) git 저장소 확인
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "❌ git 저장소 아님"; exit 1; }

# 2) dev 브랜치 필수 (실수로 master에서 실행 방지)
CURRENT=$(git branch --show-current)
if [ "$CURRENT" != "dev" ]; then
  echo "❌ dev 브랜치에서만 실행 가능합니다 (현재: $CURRENT)"
  echo "   먼저 /데브 실행 후 재시도하세요"
  exit 1
fi

# 3) 사용자 승인 확인
# /ship 호출 자체가 "verify + master push + G3 배포"를 포함한 전체 체인 승인으로 간주된다.
# 단, 각 sub-skill의 샌드박스 승인 규칙(특히 master push, G3 SSH)은 그대로 유지된다.
# 샌드박스가 "G3 배포승인" 같은 문구를 요구하면 사용자에게 한 줄로 확인한다.
```

## Step 1: /verify

```bash
echo "==== Step 1/3: /verify 실행 ===="
```

`verify` 스킬을 직접 호출한다. 호출 방식은 Skill 도구 사용:

- `Skill` tool with `skill=verify`
- verify가 내부적으로 trap을 걸어 FAIL 시 `.verify-pass`를 자동 무효화
- verify가 PASS로 종료하면 `.verify-pass` 파일이 현재 HEAD SHA와 함께 생성됨

**FAIL 처리**: verify가 FAIL 리포트를 출력하면 ship은 **즉시 abort**하고 다음 단계 진입하지 않는다. 사용자에게 verify 리포트를 그대로 전달.

## Step 2: /merge-to-master

```bash
echo "==== Step 2/3: /merge-to-master 실행 ===="
```

`merge-to-master` 스킬을 직접 호출한다 (Skill tool with `skill=merge-to-master`).

- 내부적으로 verify 통과 게이트 재확인 (HEAD SHA vs `.verify-pass`)
- ff-only 머지 실패 시 abort — dev ↔ master divergent 상태 해소 후 `/ship` 재실행 필요
- master push + G3 pull + NSSM restart + smoke check까지 수행
- Step 6에서 `git checkout dev`로 자동 복귀 + `.verify-pass` 자동 제거

**ff-only 실패 패턴**: 사용자가 dev에 세션 간 origin/master 최신 merge를 누락했을 때 자주 발생. 해소 절차:

```bash
git fetch origin
git merge origin/master --no-edit
# HANDOFF/WORKLOG 충돌 시: git checkout --ours HANDOFF.md WORKLOG.md && git add -A && git commit --no-edit
# 이후 /ship 재실행 (verify부터 다시)
```

**FAIL 처리**:
- Step 1-2 사이 실패(ff-only 거부, push 권한 등) → master 변경 없음. 사용자에게 원인 보고 후 abort
- Step 3-5 사이 실패(G3 pull 충돌, service restart 실패, smoke 실패) → master push는 이미 완료. 사용자에게 롤백 가이드(merge-to-master 스킬 내부에 이미 있음) 전달

## Step 3: /데브 (안전망)

```bash
echo "==== Step 3/3: /데브 확인 ===="
```

일반적인 경우 `merge-to-master` Step 6에서 이미 dev로 복귀했다. 하지만 중간 실패로 master에 남았다면 `/데브` 스킬로 강제 전환.

- `Skill` tool with `skill=데브`
- 이미 dev면 no-op
- master에 dirty tree가 있으면 사용자에게 stash/commit/discard 유도 (자동 stash 금지)

## 최종 리포트

```
🚢 /ship 배포 체인 리포트
| # | 단계                  | 결과    | 상세                                         |
|---|-----------------------|---------|----------------------------------------------|
| 1 | /verify               | ✅ PASS | .verify-pass @ <SHA>                         |
| 2 | /merge-to-master      | ✅ PASS | master @ <SHA> pushed + G3 배포 + smoke 200  |
| 3 | /데브 복귀            | ✅ PASS | dev @ <SHA>                                  |

🏁 배포 완료 — 이후 누적 작업은 dev 위에서 진행
```

FAIL 경우 실패 단계만 ❌ 표기하고, 그 이후 단계는 ⬜ SKIP 표기한 뒤 abort.

## 안전 규칙

1. **자동 승인 상승 금지** — `/ship` 호출이 샌드박스의 destructive 승인을 대체하지 않는다. master push/G3 SSH가 차단되면 사용자 승인 문구("머지배포승인", "G3 배포승인") 요청.
2. **중간 실패 시 상태 보존** — `.verify-pass` 무효화는 verify/merge-to-master 스킬 자체 trap이 처리. ship은 별도로 건드리지 않는다.
3. **dev 강제 체크** — Prerequisites에서 이미 dev 확인. 예외 없음.
4. **verify 재실행 요구** — master push 이후 G3 단계에서 abort해도 `.verify-pass`는 merge-to-master Step 6이 실행되지 않아 유지됨. 다음 재시도 시 동일 SHA면 verify 통과 상태 재사용 가능.

## 관련 스킬

- `/verify` — 빌드+테스트+UI 실동작 검증 (단독 실행 가능)
- `/merge-to-master` — dev→master 머지 + G3 배포 (verify 통과 전제)
- `/데브` — dev 브랜치 전환
- `/마스터` — master 브랜치 전환
- `/auto-save` — WORKLOG/HANDOFF 세이브 + push + G3 pull
- `deploy-pipeline` — 13단계 정식 배포 (PR + canary + release document)
