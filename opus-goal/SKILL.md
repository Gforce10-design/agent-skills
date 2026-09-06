---
name: opus-goal
description: >-
  Arm a completion goal that Codex keeps working toward across turns — like the built-in
  /goal, but with the Stop-hook completion evaluator pinned to Opus (Codex-opus-4-8) instead
  of the default Haiku, so the "is it actually done?" judgment comes from a strong model.
  Use whenever the user wants Codex to autonomously continue turn after turn until a verifiable
  end-state holds AND wants that done/not-done check judged accurately — e.g. "opus goal로
  …까지 굴려줘", "골 평가자를 opus로 바꿔서 끝까지", "opus 평가자로 …완주시켜", "keep working
  until X but use opus to judge completion", "cheap/haiku 모델이 자꾸 가짜로 done 처리하니
  정확한 모델로 끝까지", or any request to arm/set/clear/teardown such an Opus-evaluated
  keep-going-until-done loop (the clear/teardown side counts too — "그 opus 골 hook 떼줘").
  Trigger on the intent even when neither "hook" nor "opus" is named, if they want /goal-style
  looping with a more trustworthy completion judge. Do NOT trigger for merely explaining what
  /goal or its evaluator model is (informational), switching the session model (/model opus),
  interval polling (/loop every N minutes), brute-force same-prompt loops (ralph-loop), a one-off
  "just run the tests once", generic add-a-hook-to-settings how-tos, debugging an unrelated hook,
  or reviewing this skill's own code — those are adjacent but not this. Installs or clears a
  prompt-based Stop hook via the bundled scripts (set_opus_goal.py / clear_opus_goal.py).
---

# opus-goal — keep working until done, judged by Opus

## 왜 이 스킬인가 (why)

내장 `/goal`은 "조건이 충족될 때까지 매 턴 계속 작업"하지만, 그 완료 판정을 **configured small-fast
model(기본 Haiku)**로 한다. `/goal`에는 **per-call 모델 override가 없다.** 더 정확한 판정자(Opus)를
쓰려면 `/goal`이 내부적으로 감싸는 그 메커니즘 — **prompt 기반 Stop hook** — 을 직접 쓰되 `model`을
Opus로 핀하면 된다. 이 스킬이 그 hook을 안전하게 설치/해제하는 일을 패키징한다.

핵심: **품질 엔진은 당신이 부여하는 "종결 조건"이고, 이 스킬은 그 조건을 Opus가 매 턴 정확히 판정하게
만드는 드라이버다.** 판정 정확도가 비용보다 중요할 때 쓴다.

## 언제 쓰나 / 안 쓰나

- **쓴다**: 여러 단계의 자율 작업을 "조건 충족까지" 굴리고 싶은데, 끝났는지 아닌지의 판정이 미묘해서
  약한 모델이 false-positive(가짜 완료)나 false-negative를 낼까 걱정될 때.
- **안 쓴다**: 한 번에 끝나는 단발 작업(루프 불필요), 또는 판정이 자명해서 기본 `/goal`(Haiku)로 충분할 때.
  Opus 판정은 턴당 비용↑·약간 느리다 — 정확도가 그만한 가치가 있을 때만.

## 동작 절차 (arm)

1. **종결 조건을 확보한다.** ⭐평가자는 **명령 실행·파일 읽기 불가** — 어시스턴트가 transcript에 surface한
   출력만 본다. 따라서 조건은 **당신의 출력으로 입증 가능한 형태**로 써라. 좋은 조건 = 측정 가능한 단일
   종결상태 + 증명 방법 + 바뀌면 안 되는 제약. 예: "`pytest`가 0 exit으로 끝나고 그 출력이 대화에 보임",
   "각 항목 완료 시 `✅ITEM <x> DONE` 마커 + 최종 `✅GOAL TERMINAL` 요약을 출력". 조건 안에 무엇을
   출력해 증명할지까지 넣을수록 판정이 정확해진다.

2. **hook을 설치한다** (merge-safe·sentinel 태깅 — 기존 설정 보존, 재실행 시 교체):
   ```bash
   python3 ~/.Codex/skills/opus-goal/scripts/set_opus_goal.py \
     --condition "<종결 조건>" \
     --scope project        # 기본; cwd의 .Codex/settings.local.json (gitignored·격리). 전역은 --scope global
     # 선택: --model Codex-opus-4-8 (기본) · --turn-cap 150 (기본·안전상한) · --timeout 60
   ```
   `--scope project`가 기본이고 권장이다(프로젝트별 격리·gitignored·teardown 쉬움). 모든 프로젝트에서
   쓰려면 `--scope global`(`~/.Codex/settings.json`) — 단 그 스코프 모든 세션 종료마다 Opus 평가가 돈다.

3. **적용 확인.** Codex는 **file-watcher로 settings 변경을 라이브 반영**한다(몇 초 내 안 잡히면 세션
   재시작). `/hooks`(인터랙티브 터미널, read-only) → `Stop`에서 `model=Codex-opus-4-8` 확인 가능.

4. **무인 실행이면 auto mode도 켠다**(턴 내 툴 자동승인). auto mode=per-tool 승인 제거, 이 hook=per-turn
   정지 제거 — 둘이 상호보완.

5. **조건을 향해 작업을 시작한다(kickoff).** 매 턴 끝에 Opus hook이 조건 충족을 판정해 "no"면 그 이유를
   다음 턴 가이드로 넣고 계속, "yes"면 정지를 허용한다. **증거를 transcript에 명시적으로 출력하라** —
   평가자는 당신이 출력한 것만 본다.

## teardown — 실행자 self-clear (종결 시, 안전)

> ⚠️ 설계 교훈: 마커-grep 커맨드 hook(transcript에서 `✅GOAL TERMINAL —` 탐지) 방식은 **폐기**했다.
> 설명·인용으로 그 마커를 적기만 해도 오발동하는 **false-positive** 결함이 있었다(실측으로 hook이 조기 자가삭제됨).

대신 **종결 술어에 도달하면 실행자가 루프의 마지막 단계로 `clear_opus_goal.py`를 직접 실행**한 뒤 종결한다.
이건 prose 언급에 걸리지 않아 안전하고, 사용자 입장에선 자동(루프가 알아서 정리)이다. §동작 절차의 마지막 단계로 수행한다:
```bash
python3 ~/.Codex/skills/opus-goal/scripts/clear_opus_goal.py --scope project   # (또는 global)
```
중도 중단·수동 제거도 동일 명령. clear는 sentinel로 **이 skill이 설치한 hook만** 제거하고 다른 설정(다른 hook·MCP 등)은
보존한다. 잠깐만 끄려면 같은 settings 파일에 `"disableAllHooks": true`를 두면 모든 hook이 멈춘다(다시 켜려면 제거).

> ★ 주의(중요): goal을 arm한 **그 세션 안에서** 이 skill을 설명/인용하지 말 것 — 판정 hook이 매 Stop마다 도므로,
> arm된 세션에서 "지금 시작할까요?" 같이 yield하려 하면 hook이 막아 빌드를 강제 진행시킨다. arm은 **실제로 굴릴 직전**에 하고,
> 셋업·설명은 arm 전에 끝내라.

## `/goal`(내장)과의 차이

| | `/goal` (내장) | opus-goal (이 스킬) |
|---|---|---|
| 평가자 모델 | configured small-fast(기본 **Haiku**) | **Opus**(Codex-opus-4-8, 변경 가능) |
| 범위/수명 | 세션 스코프·자동 해제 | settings 파일 hook·**수동 teardown 필요** |
| 호출 | `/goal <조건>` | 스크립트로 arm + kickoff + clear |
| 비용/정확도 | 싸고 빠름 | 턴당 비싸고 약간 느림·판정 더 정확 |

## 요구·주의

- 신뢰(trust) dialog 수락된 workspace + `disableAllHooks`/`allowManagedHooksOnly` 미설정이어야 hook이 돈다.
- `--scope project`는 `.Codex/settings.local.json`(보통 gitignored)에 쓴다 → 커밋 안전. `--scope global`은
  `~/.Codex/settings.json` 전역.
- 안전상한 `--turn-cap`(기본 150)은 무한 루프 방지용 — 조건이 영영 충족 안 될 때 어시스턴트가 그 턴수
  초과를 보고하면 평가자가 정지를 허용한다.
- 스크립트는 순수 stdlib(파이썬3)·atomic write. 자세한 인자는 각 스크립트 `--help`.
