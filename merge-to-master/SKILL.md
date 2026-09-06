---
name: merge-to-master
description: "dev → master 머지 + G3 운영 배포 + smoke check. verify 통과 필수."
---

# merge-to-master

dev 브랜치에서 master로 머지하고, G3 운영 서버에 배포하고, smoke check로 정상 동작을 확인한다.

## 전제조건 (Prerequisites)

**필수**: 모든 단계는 `set -euo pipefail` 환경에서 실행. 한 단계라도 실패하면 즉시 abort (Codex N-1 / M-5 보강).

```bash
set -euo pipefail
PROJECT_ROOT=$(git rev-parse --show-toplevel)
PROJECT_NAME=$(basename "$PROJECT_ROOT")
```

1. **verify 통과 파일 검증** (C-2 보강 — 파일 기반 영속 게이트)
   ```bash
   VERIFY_FILE="${PROJECT_ROOT}/.verify-pass"

   if [ ! -f "$VERIFY_FILE" ]; then
     echo "❌ .verify-pass 파일이 없습니다. 먼저 /verify를 실행하여 PASS 판정을 받으세요"
     exit 1
   fi

   VERIFY_SHA=$(grep '^sha=' "$VERIFY_FILE" | cut -d= -f2)
   HEAD_SHA=$(git rev-parse HEAD)

   if [ "$VERIFY_SHA" != "$HEAD_SHA" ]; then
     echo "❌ verify-pass가 오래되었습니다 (verify=$VERIFY_SHA, HEAD=$HEAD_SHA)"
     echo "   코드가 변경되었으니 /verify를 재실행하세요"
     exit 1
   fi

   echo "✅ verify 통과 확인 (SHA: $HEAD_SHA)"
   ```

2. **dev 브랜치 확인**: 현재 dev 브랜치에서 실행 중인지 확인
   ```bash
   CURRENT=$(git branch --show-current)
   if [ "$CURRENT" != "dev" ]; then
     echo "❌ dev 브랜치에서만 실행 가능합니다 (현재: $CURRENT)"
     exit 1
   fi
   ```

3. **워킹 트리 클린 확인**: 커밋되지 않은 변경이 없는지 확인
   ```bash
   if [ -n "$(git status --porcelain)" ]; then
     echo "❌ 커밋되지 않은 변경이 있습니다. 먼저 /auto-save를 실행하세요"
     exit 1
   fi
   ```

4. **PROJECT_NAME / CURRENT_BRANCH allowlist 검증** (Codex N-2 보강 — shell injection 차단)
   ```bash
   ALLOW='^[A-Za-z0-9._-]+$'

   if ! [[ "$PROJECT_NAME" =~ $ALLOW ]]; then
     echo "❌ PROJECT_NAME에 허용되지 않은 문자 포함: '$PROJECT_NAME'"
     echo "   허용 문자: [A-Za-z0-9._-]"
     exit 1
   fi

   if ! [[ "$CURRENT" =~ $ALLOW ]]; then
     echo "❌ 브랜치명에 허용되지 않은 문자 포함: '$CURRENT'"
     exit 1
   fi
   ```

## Step 1: dev → master ff-only 머지 + SHA 재검증

Codex M-1 / m-4 보강 — fast-forward만 허용하고, 머지 후 HEAD가 verify SHA와 동일함을 재확인한다. 이로써 verify→deploy SHA gate가 무력화되지 않는다.

```bash
# 1) origin 최신화 후 local master가 stale이면 ff로 맞춘다
git fetch origin
git checkout master
git pull --ff-only origin master

# 2) dev를 ff-only로 머지 — non-ff면 자동 실패
git merge --ff-only dev

# 3) 머지 후 SHA 재검증 — verify 시점 dev HEAD와 동일해야 함
POST_MERGE_SHA=$(git rev-parse HEAD)
if [ "$POST_MERGE_SHA" != "$VERIFY_SHA" ]; then
  echo "❌ 머지 후 HEAD($POST_MERGE_SHA)가 verify SHA($VERIFY_SHA)와 다릅니다"
  echo "   ff-only 조건 위반 또는 race condition. 배포 중단."
  exit 1
fi

echo "✅ ff-only 머지 완료 + SHA gate 통과 ($POST_MERGE_SHA)"
```

- **non-ff merge 거부**: master가 dev보다 앞서 있으면 `git merge --ff-only`가 실패 → 직접 dev rebase 후 재실행
- 충돌 발생 시 → `git merge --abort` 후 원인 분석
- `set -euo pipefail` 하에서는 실패 시 자동 abort

## Step 2: Push origin master

```bash
git push origin master
```

- push 실패 시 → 원인 분석 (권한, remote 상태 등)

## Step 3: G3 pull (운영 서버 동기화)

Codex M-1 보강 — `--ff-only`로 dirty/divergent working tree 배포 차단.
Codex N-2 보강 — Prerequisites 4번에서 PROJECT_NAME을 allowlist 검증했으므로 escaping 안전.
Codex R2-M1 보강 — pull 전에 G3 working tree가 clean한지 확인 (dirty면 abort).
Codex R2-C1 보강 — pull 후 G3 HEAD SHA가 로컬 master SHA와 일치하는지 재검증 (race window 차단).

```bash
# R2-M1: G3 working tree clean 확인 — dirty면 pull 충돌 위험, abort
G3_DIRTY=$(ssh -o ConnectTimeout=10 sudol@192.168.0.12 "cmd /c \"cd /d D:\\\"Vibe Coding\\\"\\${PROJECT_NAME} && git status --porcelain\"")
if [ -n "$G3_DIRTY" ]; then
  echo "❌ G3 working tree에 커밋되지 않은 변경 존재:"
  echo "$G3_DIRTY"
  echo "   G3에서 수동 정리 후 재실행하세요. 배포 중단."
  exit 1
fi
echo "✅ G3 working tree clean"

# G3 master ff-only pull (경로 공백은 escaped double quote로 처리)
ssh -o ConnectTimeout=10 sudol@192.168.0.12 "cmd /c \"cd /d D:\\\"Vibe Coding\\\"\\${PROJECT_NAME} && git pull --ff-only origin master\""

# R2-C1: pull 후 G3 HEAD SHA 재검증 — push와 G3 pull 사이 race로 다른 SHA를 받지 않았는지 확인
G3_SHA=$(ssh -o ConnectTimeout=10 sudol@192.168.0.12 "cmd /c \"cd /d D:\\\"Vibe Coding\\\"\\${PROJECT_NAME} && git rev-parse HEAD\"" | tr -d '[:space:]\r\n')
if [ "$G3_SHA" != "$POST_MERGE_SHA" ]; then
  echo "❌ G3 HEAD($G3_SHA)가 로컬 master HEAD($POST_MERGE_SHA)와 다릅니다"
  echo "   원인 후보: (1) push 후 다른 머신에서 추가 push (2) G3 git 상태 이상"
  echo "   배포 중단 — 수동 점검 필요"
  exit 1
fi
echo "✅ G3 동기화 완료 + SHA gate 통과 ($G3_SHA)"
```

- `--ff-only`: G3에 local commit이 있어 divergent 상태면 실패 → 운영 서버 상태 이상 감지
- Prerequisites 4번이 통과했으므로 `PROJECT_NAME`은 `[A-Za-z0-9._-]+`만 포함 (shell meta 안전)
- `ConnectTimeout=10`: 네트워크 지연 대비
- 서브모듈 존재 시:
  ```bash
  ssh -o ConnectTimeout=10 sudol@192.168.0.12 "cmd /c \"cd /d D:\\\"Vibe Coding\\\"\\${PROJECT_NAME} && git submodule update --init --recursive\""
  ```

## Step 4: G3 서비스 재시작 (PID 캡처 → restart)

프로젝트와 변경 내용에 따라 `SERVICE_NAME`을 결정한다 (Step 5의 PID 비교에서 사용).

| 조건 | SERVICE_NAME |
|------|--------------|
| Dashboard 코드/프론트 변경 | `AlphaMate-Dashboard` |
| Agent1 변경 | `AlphaMate-Agent1` |
| Agent2 변경 | `AlphaMate-Agent2` |
| 문서만 변경 | (skip — `SERVICE_NAME=""`) |
| AlphaMate 이외 프로젝트 | (skip — `SERVICE_NAME=""`) |

```bash
# 예: Dashboard 배포
SERVICE_NAME="AlphaMate-Dashboard"

if [ -n "$SERVICE_NAME" ]; then
  # R2-M2 보강: 재시작 전 PID 캡처 (Step 5에서 비교)
  PID_BEFORE=$(ssh -o ConnectTimeout=10 sudol@192.168.0.12 "sc queryex $SERVICE_NAME" 2>/dev/null \
    | grep -i 'PID' | head -1 | awk -F': ' '{print $2}' | tr -d '[:space:]\r\n' || echo "")
  echo "재시작 전 PID: ${PID_BEFORE:-(unknown)}"

  ssh -o ConnectTimeout=10 sudol@192.168.0.12 "cmd /c \"nssm restart $SERVICE_NAME\""
fi
```

- 프론트엔드 변경 + dist/ 미커밋이면 G3에서 `npm run build` 선행 (현재는 dist/ 커밋 정책이라 생략)
- `SERVICE_NAME`이 빈 문자열이면 Step 5 PID 비교/HTTP 검증을 모두 skip

## Step 5: Smoke check (PID 변화 + HTTP 200, 실패 시 hard abort)

Codex N-1 / M-5 보강 — smoke check 실패는 반드시 `exit 1`로 배포를 중단한다. 그래야 Step 6의 `.verify-pass` 삭제와 auto-save가 실행되지 않아 실패 상태가 보존된다.
Codex R2-M2 보강 — HTTP 200만으로는 신버전 로드를 보장 못 함 (옛 프로세스가 응답 가능). 재시작 전후 PID가 변했는지 추가로 확인한다.

```bash
if [ -n "$SERVICE_NAME" ]; then
  # 10초 대기 (서비스 기동 시간 확보)
  sleep 10

  # 1) PID 변화 확인 (R2-M2)
  PID_AFTER=$(ssh -o ConnectTimeout=10 sudol@192.168.0.12 "sc queryex $SERVICE_NAME" 2>/dev/null \
    | grep -i 'PID' | head -1 | awk -F': ' '{print $2}' | tr -d '[:space:]\r\n' || echo "")
  echo "재시작 후 PID: ${PID_AFTER:-(unknown)}"

  if [ -z "$PID_AFTER" ] || [ "$PID_AFTER" = "0" ]; then
    echo "❌ 서비스 PID를 가져올 수 없거나 0입니다 — 서비스 비정상 종료 의심"
    exit 1
  fi

  if [ -n "$PID_BEFORE" ] && [ "$PID_BEFORE" = "$PID_AFTER" ]; then
    echo "❌ 서비스 PID가 재시작 전후 동일($PID_BEFORE) — restart 미반영, 옛 프로세스 잔존"
    exit 1
  fi
  echo "✅ PID 변화 확인 (${PID_BEFORE:-?} → $PID_AFTER)"

  # 2) HTTP 200 확인 (set -e 하에서도 비교문은 exit code 처리 필요)
  STATUS=$(ssh -o ConnectTimeout=10 sudol@192.168.0.12 'curl -s -o /dev/null -w "%{http_code}" http://localhost:8501' || echo "000")

  if [ "$STATUS" = "200" ]; then
    echo "✅ Smoke check PASS — HTTP 200 OK + PID 변화 확인"
  else
    echo "⚠️  HTTP 1차 실패 — HTTP $STATUS, 10초 후 재시도"
    sleep 10
    STATUS=$(ssh -o ConnectTimeout=10 sudol@192.168.0.12 'curl -s -o /dev/null -w "%{http_code}" http://localhost:8501' || echo "000")

    if [ "$STATUS" = "200" ]; then
      echo "✅ Smoke check 재시도 PASS — HTTP 200 OK"
    else
      echo "❌ Smoke check 재시도도 실패 — HTTP $STATUS"
      echo ""
      echo "배포를 중단합니다. 현재 상태:"
      echo "  - master: $POST_MERGE_SHA (이미 push됨)"
      echo "  - G3: git pull 완료, 서비스 재시작 완료(PID=$PID_AFTER), HTTP 응답 이상"
      echo ""
      echo "롤백 가이드:"
      echo "  cd \"$PROJECT_ROOT\""
      echo "  git revert --no-edit HEAD  # 단일 commit 가정, merge commit이면 -m 1 필요"
      echo "  git push origin master"
      echo "  ssh -o ConnectTimeout=10 sudol@192.168.0.12 \"cmd /c \\\"cd /d D:\\\\\\\"Vibe Coding\\\\\\\"\\\\${PROJECT_NAME} && git pull --ff-only origin master\\\"\""
      echo "  ssh sudol@192.168.0.12 'cmd /c \"nssm restart $SERVICE_NAME\"'"
      echo ""
      echo ".verify-pass는 유지됩니다 (이번 배포 실패 상태 보존)."
      exit 1
    fi
  fi
else
  echo "ℹ️  SERVICE_NAME이 비어 있어 PID/HTTP 검증을 skip합니다 (문서/외부 프로젝트)"
fi
```

## Step 6: dev 브랜치 복귀 + `.verify-pass` 제거 + auto-save 호출

이 단계는 **Step 5 smoke check PASS**가 선행조건. Step 5에서 실패하면 `exit 1`로 여기 도달하지 않으므로, `.verify-pass`가 유지되어 실패 상태가 보존된다 (Codex N-1 보강).

```bash
git checkout dev

# 배포 full success 확인 후에만 .verify-pass 제거
rm -f "${PROJECT_ROOT}/.verify-pass"
echo "✅ 배포 성공 — .verify-pass 제거됨, 다음 변경 시 /verify 재실행 필요"
```

- `/auto-save` 스킬 호출하여 WORKLOG/HANDOFF/3PC 동기화 완료
- auto-save 내에서 G3 pull은 실행하지 않음 (이미 Step 3에서 완료)

## 리포트 출력

```
📋 merge-to-master 리포트
| # | 단계                      | 결과    | 상세                                      |
|---|---------------------------|---------|-------------------------------------------|
| 0 | verify 통과 + allowlist   | ✅ PASS | SHA 일치, PROJECT_NAME/BRANCH 안전         |
| 1 | ff-only merge + SHA gate  | ✅ PASS | master HEAD == VERIFY_SHA                  |
| 2 | push origin master        | ✅ PASS | 정상 push                                  |
| 3 | G3 clean + pull + SHA gate | ✅ PASS | working tree clean, G3 HEAD == master SHA |
| 4 | G3 서비스 재시작(PID 캡처) | ✅ PASS | PID_BEFORE 기록 후 nssm restart            |
| 5 | Smoke check (PID+HTTP)    | ✅ PASS | PID 변화 확인 + HTTP 200 OK (8501)         |
| 6 | dev 복귀 + .verify-pass 제거 | ✅ PASS | 배포 성공 후 gate 초기화                |

🏁 배포 완료
```
