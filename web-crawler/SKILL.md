---
name: web-crawler
description: URL과 수집 항목을 받아 사이트를 정찰하고 데이터를 수집하여 엑셀로 출력하는 범용 웹 크롤링 에이전트. 사용자가 URL과 함께 데이터 수집/크롤링/스크래핑을 요청하거나, 웹사이트에서 정보를 추출하고 싶다고 할 때 반드시 이 스킬을 사용한다. "이 사이트에서 ~를 모아줘", "~를 크롤링해줘", "입찰공고를 수집해줘" 등의 요청에도 트리거된다.
---

# web-crawler — 전역 진입점 (레포 바인딩 래퍼)

이 파일은 **워크플로우가 아니다.** 실행 환경을 레포에 묶는 일만 한다.
정본 워크플로우는 아래 규칙 1의 SKILL.md 에 있고, 이 파일은 그것을 대체하지 않는다.

## 규칙 0 — 무엇보다 먼저 레포로 이동한다

```
REPO = /Users/gimsuyeong/Developer/web-crawler
```

- **모든 작업의 cwd 는 REPO 다.** 정찰·수집·검증·출력 전부.
- **Python 은 `./.venv/bin/python` 만 쓴다.** 시스템 `python3`(3.14)에는 scrapling·playwright 가 없다.
- **왜 cwd 가 강제인가** — 생성하는 `crawl_script.py` 가 `sys.path.insert(0, './scripts')` 로
  `utils` / `domain_profile` / `export_excel` 을 import 하고, 셀렉터 자가치유 DB 도
  `./fingerprints/elements_storage.db` 로 연다. 전부 **상대경로**라 다른 디렉터리에서는
  import 부터 깨진다. `cd` 없이 시작하지 말 것.
- **산출물 위치**: `REPO/output/<도메인>/<주제_YYYYMMDD_HHMMSS>/` (gitignore 됨).
  사용자가 다른 경로를 원하면 거기서 만든 뒤 **마지막에 복사**해서 준다 — 작업 디렉터리를 옮기지 않는다.
- **REPO 가 없으면 멈추고 사용자에게 알린다.** 임의로 다른 경로를 찾거나 재설치를 시작하지 말 것.
  재설치가 승인되면:
  ```bash
  git clone https://github.com/byungjunjang/web-crawler.git /Users/gimsuyeong/Developer/web-crawler
  cd /Users/gimsuyeong/Developer/web-crawler
  /opt/homebrew/bin/python3.13 -m venv .venv && .venv/bin/python scripts/bootstrap.py
  ```

## 규칙 1 — 정본을 전문 읽고 그대로 따른다

`cd` 한 직후, 아래를 **읽고 나서** 움직인다. 이 래퍼의 요약만 보고 시작하지 말 것.

| 파일 | 내용 |
|------|------|
| `REPO/.claude/skills/web-crawler/SKILL.md` | **정본 워크플로우** (553줄, Step 1 ~ Step 6 + 게이트 전부) |
| `REPO/CLAUDE.md` | 저자의 에이전트 지시서 (양 host SSOT) |
| `REPO/.claude/skills/web-crawler/references/fetcher-patterns.md` | Step 4 수집 코드 템플릿 |
| `REPO/.claude/skills/web-crawler/references/antibot-strategies.md` | Step 3 안티봇 대응 |
| `REPO/.claude/skills/web-crawler/references/troubleshooting.md` | 수집 실패 진단 |
| `REPO/scripts/scrapling_reference.md` | Scrapling API 레퍼런스 |

## 규칙 2 — 건너뛰면 안 되는 게이트

정본에 정의돼 있고 이 래퍼가 **면제하지 않는다.** 상세 조건은 정본을 볼 것.

- **Step 2-0 robots.txt 확인** — 정찰 전 필수 (`from utils import check_robots`)
- **사다리 A→B 이음매 통지 게이트** — 자동 접근 차단(WAF·봇탐지·CAPTCHA)을 만나면
  자동으로 넘어가지 않고 사용자에게 알린 뒤 진행 여부를 묻는다
- **Step 3.5 API 필드 매핑 검증**
- **Step 5.0 소프트블록 게이트** — 다른 검증보다 **먼저**. HTTP 200 인데 내용이 빈/봇확인 페이지인 경우
- **Step 5-A 도메인 프로필 저장** — 필수 게이트. 누락하면 파이프라인 미완료
- **CAPTCHA 자동 풀이 금지** — 위 통지 게이트와는 별개의 절대 금지

## 규칙 3 — 레포 안에서 세션을 열었다면 이 파일은 무시된다

`cd REPO` 후 Claude Code 를 띄우면 프로젝트 스킬
`REPO/.claude/skills/web-crawler/` 가 우선한다(정본이 직접 뜬다). 정상이며 그게 더 낫다.
이 래퍼는 **레포 밖에서 크롤링 요청을 받았을 때만** 쓰인다.

## 설치 상태 (2026-08-31 확인)

- upstream commit `c64cfbf` (github.com/byungjunjang/web-crawler, master)
- venv Python **3.13.14** — 3.14 가 아닌 이유는 `scrapling[fetchers]` 컴파일 의존성
  (curl_cffi·msgspec·patchright) 휠 지원. 실제 cp313 휠로 설치됨
- agent-browser **0.27.0** — npm 전역 prefix(`~/.hermes/node/bin`)가 PATH 에 없어
  `~/.local/bin/agent-browser` 심링크로 도달성 확보
- Chrome for Testing 152.0.7977.64 (`~/.agent-browser/browsers/`)

**환경 재검증** (수집이 이상하면 먼저 이것부터):
```bash
cd /Users/gimsuyeong/Developer/web-crawler && .venv/bin/python scripts/preflight.py
# exit 0 = 전체통과 / 1 = core만 통과(agent-browser 미완료) / 2 = core 실패
```
