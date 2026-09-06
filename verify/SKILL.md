---
name: verify
description: "작업완료전 실제로 작동하는지 검증하라. vite build + pytest + 브라우저 UI 확인 통합 검증."
---

# verify

코드 수정 후 실제로 동작하는지 검증한다. 빌드 성공, 테스트 통과, 브라우저 UI 렌더링 3가지 축을 모두 확인해야 PASS.

**필수**: `set -euo pipefail` 환경에서 실행. 빌드/테스트 중 하나라도 실패하면 즉시 abort, `.verify-pass`는 생성하지 않는다.

## Step 1: 프로젝트 감지 + 실패 경로 trap 등록 (R2-M3)

git root에서 프로젝트 타입을 자동 판별한다. 이후 `set -e`로 중간 종료되더라도 `.verify-pass`가 무효화되도록 EXIT trap을 등록한다.

```bash
set -euo pipefail
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
PROJECT_NAME=$(basename "$PROJECT_ROOT")

# R2-M3: 비정상 종료(exit code ≠ 0) 시 .verify-pass 자동 무효화.
# set -e 하에서 테스트/빌드 실패로 중간 종료돼도 이전 PASS 파일이 stale하게 남는 위험 차단.
VERIFY_VERDICT="FAIL"   # Step 6에서 PASS로 덮어쓸 때까지 FAIL 상태 유지
cleanup_on_fail() {
  local rc=$?
  if [ "$VERIFY_VERDICT" != "PASS" ] && [ -f "${PROJECT_ROOT}/.verify-pass" ]; then
    rm -f "${PROJECT_ROOT}/.verify-pass"
    echo "🧹 trap: .verify-pass 무효화 (exit=$rc, verdict=$VERIFY_VERDICT)"
  fi
  return $rc
}
trap cleanup_on_fail EXIT
```

| 조건 | 타입 |
|------|------|
| `package.json` 존재 | 프론트엔드 |
| `pyproject.toml` 또는 `requirements.txt` 존재 | Python |
| 둘 다 존재 | 풀스택 |

## Step 2: 빌드 검증 (프론트엔드 / 풀스택)

프론트엔드 프로젝트일 때 실행.

```bash
# package.json의 build 스크립트 확인
npm run build   # 또는 npx vite build
```

확인 항목:
- 빌드 에러 0개
- 빌드 산출물 존재 (`dist/` 또는 `build/` 디렉토리)
- 빌드 경고 중 치명적인 것 없음

## Step 3: 테스트 검증 (Python / 풀스택)

Python 프로젝트일 때 실행.

```bash
# pytest 존재 시
pytest --tb=short -q

# coverage 리포트 존재 시 출력
pytest --cov --cov-report=term-missing
```

확인 항목:
- 테스트 실패 0개
- 새로 추가된 코드에 대한 테스트 존재 여부

## Step 4: 브라우저 UI 확인 (프론트엔드 / 풀스택)

프론트엔드 코드 변경 시 실행. Playwright MCP 도구를 사용하여 실제 렌더링을 확인한다.

```bash
# 개발 서버 기동
npm run dev          # React/Vue/Vite 프로젝트
# 또는
streamlit run app.py # Streamlit 프로젝트
```

Playwright 브라우저 도구로 localhost 접속:

1. `mcp__plugin_playwright_playwright__browser_navigate` — localhost URL 접속
2. `mcp__plugin_playwright_playwright__browser_take_screenshot` — 스크린샷 캡처
3. `mcp__plugin_playwright_playwright__browser_console_messages` — 콘솔 에러 0개 확인
4. `mcp__plugin_playwright_playwright__browser_snapshot` — DOM 요소 존재 체크

확인 항목:
- 페이지 로드 성공 (HTTP 200)
- JavaScript 콘솔 에러 0개
- 핵심 UI 요소 렌더링 확인 (DOM 요소 존재)
- 레이아웃 깨짐 없음

## Step 5: 기존 검증 스킬 연계 (선택적)

대규모 변경이나 UI 변경이 있을 때만 추가 실행:

| 스킬 | 용도 | 실행 조건 |
|------|------|-----------|
| `gstack-health` | 코드 품질 점수 (0-10) | 항상 권장 |
| `gstack-design-review` | 시각 QA | UI 변경 있을 때만 |
| `gstack-qa` | 체계적 QA 테스트 | 대규모 변경 시 |

## Step 6: 검증 리포트 출력

모든 검증 완료 후 아래 형식으로 리포트를 출력한다.

```
📋 verify 검증 리포트
| # | 항목              | 결과   | 상세                    |
|---|-------------------|--------|-------------------------|
| 1 | vite build        | ✅ PASS | dist/ 생성, 에러 0      |
| 2 | pytest            | ✅ PASS | 42 passed, 0 failed     |
| 3 | 브라우저 UI 확인  | ✅ PASS | 콘솔 에러 0, DOM 정상   |
| 4 | gstack-health     | ⬜ SKIP | 선택적 (미실행)         |

🏁 전체 판정: ✅ PASS
```

### FAIL 시 처리

- FAIL 항목이 하나라도 있으면 전체 판정 = ❌ FAIL
- FAIL 원인 분석 + 수정 가이드 제공
- 수정 후 `/verify` 재실행 안내

### PASS 판정 영속화 (C-2 보강)

세션 컨텍스트 기록만으로는 compaction/새 세션 시 소실되므로, 파일 기반으로 영속화한다.

```bash
# 전체 PASS가 확정된 직후에만 VERIFY_VERDICT 갱신 + 파일 atomic 생성
HEAD_SHA=$(git rev-parse HEAD 2>/dev/null)
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)

TMP_FILE=$(mktemp "${PROJECT_ROOT}/.verify-pass.XXXXXX")
cat > "$TMP_FILE" <<EOF
sha=${HEAD_SHA}
branch=${BRANCH}
timestamp=${TIMESTAMP}
verdict=PASS
EOF
mv "$TMP_FILE" "${PROJECT_ROOT}/.verify-pass"

# R2-M3: PASS 확정 — Step 1의 trap이 무효화하지 않도록 verdict 플래그 전환
VERIFY_VERDICT="PASS"
```

- `.verify-pass`는 프로젝트 루트에 저장 (`.gitignore`에 추가)
- `/merge-to-master`가 파일 존재 + `sha=$(git rev-parse HEAD)` 일치 여부 검증
- FAIL 시 별도 삭제 로직 불필요 — Step 1의 EXIT trap이 `VERIFY_VERDICT != "PASS"`인 모든 종료 경로에서 `.verify-pass`를 자동 제거
