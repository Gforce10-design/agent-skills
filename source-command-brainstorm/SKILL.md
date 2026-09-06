---
name: "source-command-brainstorm"
description: "Cross-model brainstorm. Codex와 Hermes Codex(gpt-5.5)가 번갈아 제안/비판/합의. MCP `hermes-codex` 서버 필요. 호출 예 `/brainstorm <주제>`."
---

# source-command-brainstorm

Use this skill when the user asks to run the migrated source command `brainstorm`.

## Command Template

# /brainstorm — Codex ↔ Codex Cross-Model Brainstorm

Codex(나)와 Hermes Codex(gpt-5.5)가 **번갈아 제안·비판·반제안**을 주고받아 합의안을 도출한다. DualMind는 동일 가족(Codex×Codex)이라 수렴이 빠른 대신 다양성이 낮다. 이 스킬은 진짜 이질 모델을 끌어와 **다른 훈련 데이터의 시각**을 얻는다.

## 사용법

- `/brainstorm <주제>` — 기본 2라운드
- `/brainstorm <주제> --rounds 3` — 3라운드까지
- `/brainstorm --compare "A vs B"` — 두 대안 비교 모드

## 머신 요구사항 (중요)

- **이 스킬은 A8(아팔)에서만 동작함**. Codex 호출이 WSL Ubuntu + `/home/sudol/.hermes/` 설치를 요구한다.
- Desktop/G3에서 `/brainstorm`을 쓰면 MCP 스폰이 실패해 즉시 에러. 이 경우 `/brainstorm-webchat`(Codex.ai ↔ ChatGPT.com 브라우저) 또는 `/dualmind`(Codex 단독) 로 대체하라.

## 언제 쓰나

- ✅ 아키텍처 결정, 트레이드오프 토론, 불확실한 접근 선택
- ✅ 내가 낸 제안을 적대적 관점에서 뚫어보고 싶을 때
- ❌ 사실 조회, 단순 코딩 (오버킬)
- ❌ 레이턴시 민감 작업 (회당 15~30초 × 라운드 수)

## 실행 순서

### 전제: MCP 서버 가동 확인

시작할 때 `mcp__hermes-codex__ask_codex` 도구가 로드되어 있는지 확인. 없으면 사용자에게 "Codex 재시작 필요" 안내 후 중단.

### R1 — 내 초기 제안 (Codex)

주제를 보고 **3개의 서로 다른 접근**을 1-2줄씩 제시한다. 각 접근엔:
- 핵심 아이디어
- 주된 장점
- 예상되는 리스크 1개

출력 형식:
```
[R1 Codex] <주제>
옵션 A — <한 줄>
  + <장점>
  − <리스크>
옵션 B — ...
옵션 C — ...
```

### R2 — Codex 비판 (`codex_critique`)

R1 출력 전체를 `claude_proposal` 인자로 넣어 `codex_critique`를 호출. 결과는 "3-5개 비판 bullet"이 나옴.

```
mcp__hermes-codex__codex_critique(
  claude_proposal="<R1 원문>",
  topic="<사용자 주제>"
)
```

반환된 `hermes_session_id`를 **기억하고** 다음 호출에 전달 (세션 이어가기).

### R3 — 내 재반응 (Codex)

Codex의 비판을 읽고:
- 유효한 비판: 받아들여 옵션을 조정
- 부당한 비판: 반박 근거 1문장씩
- 새로운 관점이 나왔으면: 옵션 D 추가

출력:
```
[R3 Codex 반응]
비판 수용: <항목> → <수정>
반박: <항목> → <근거>
새 옵션 D — ...
```

### R4 — Codex 반제안 (`ask_codex`, session_id 전달)

Codex에게 "내 수정본을 보고 **너라면 어떻게 할지**" 물어봄. session_id 전달해서 비판-반제안 맥락 연속성 확보.

```
mcp__hermes-codex__ask_codex(
  question="Codex가 다음과 같이 수정했음: <R3 원문>. 네가 이 주제를 처음부터 설계한다면 어떤 안을 고를지 이유와 함께 제시하라. Codex 안과 다른 지점을 명확히 대비시켜라.",
  session_id="<R2에서 받은 sid>"
)
```

### R5 — 합의 시놉시스 (Codex 단독)

양쪽 입력 전부 모아서:
- **공통 합의 지점** (양쪽 다 동의하는 것)
- **남은 분기** (의견 갈린 것, 각자 근거)
- **내 최종 권고** (선택한 옵션 + 이유 + 포기한 것)

출력 형식:
```markdown
## 합의 지점
- ...
- ...

## 분기된 지점
| 쟁점 | Codex | Codex | 내 판단 |
|---|---|---|---|
| ... | ... | ... | ... |

## 최종 권고
<선택 옵션>

**이유**: ...
**포기한 것**: ...
**잔존 리스크**: ...
```

### 추가 라운드 (rounds > 2)

`--rounds 3`이면 R4 뒤에 R4.5 Codex 재반응 + R4.6 Codex 재반제안 추가. 단, 두 모델이 같은 자리에서 맴돌면 **조기 종료** 판단:
- 양쪽 입장이 바뀌지 않고 2라운드 반복 → "수렴 실패, 근본 가정 불일치" 노트 붙여 R5로 넘어감

## 저장

완료 시 패킷 저장:

```powershell
$vibe = if ($env:VIBECODING_HOME) { $env:VIBECODING_HOME }
        elseif (Test-Path "C:\Users\sudol\Vibe Coding") { "C:\Users\sudol\Vibe Coding" }
        elseif (Test-Path "D:\Vibe Coding") { "D:\Vibe Coding" }
        else { $null }

$date = Get-Date -Format "yyyy-MM-dd-HHmm"
$slug = "<주제-슬러그>"
$out = "$vibe\.planning\brainstorm\$date-$slug.md"
New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
```

패킷 구조:
```markdown
# Brainstorm: <주제>
Generated: <ISO timestamp>
Rounds: <N>
Models: Codex (이 세션) + Hermes Codex (gpt-5.5 via ChatGPT Pro)

## 주제
<사용자 원문>

## R1 — Codex 초안
<R1 출력>

## R2 — Codex 비판
<codex_critique 반환값>

## R3 — Codex 반응
<R3 출력>

## R4 — Codex 반제안
<ask_codex 반환값>

## R5 — 합의/권고
<R5 출력>
```

## 주의

- **레이턴시**: Codex 호출 회당 15~30초. 2라운드 = 약 1분. 사용자에게 진행 상태 알림 (라운드 시작 시 "Codex에 비판 요청 중..." 한 줄).
- **session_id**: R2에서 받은 걸 R4에 전달. 없으면 두 Codex 호출이 서로 모름. 있으면 "R4에서 이전 비판 맥락 참조" 가능.
- **조기 종료**: Codex가 "The proposal is solid, no significant issues" 류로 끝내면 R3 건너뛰고 R5로 직행.
- **실패 처리**: Codex가 timeout/오류 시 패킷에 `[R2 FAILED: <사유>]` 기록하고 Codex 단독 합의 (경고 명시).
- **민감 정보**: 시크릿/키/토큰은 프롬프트에 포함하지 말 것 (Codex는 외부 ChatGPT 서버로 전송됨).
- **비용**: ChatGPT Pro Codex 사용량이 소진됨. 라운드당 1회 호출 = 2라운드 3호출. 하루 10회 이상이면 한도 주의.

## 디버그

- Hermes MCP 서버 살아있는지: `wsl -d Ubuntu bash -c "source /home/sudol/.hermes/hermes-agent/venv/bin/activate && hermes chat -q '핑' -Q"` (16초 안에 응답 와야 함)
- MCP 툴이 Codex에 안 보이면: Codex 재시작
- Codex OAuth 만료: `hermes status`에서 확인
