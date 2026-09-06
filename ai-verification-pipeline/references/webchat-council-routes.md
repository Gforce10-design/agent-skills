# Webchat council — verified operational routes (Stage 3 mechanics)

The hard part of a cross-vendor `8프로` council is *physically getting a large prompt into each
surface* and *not stepping on a concurrent session*. The council's value (diversity > count) is
worthless if the prompt arrives corrupted or you fabricate a verdict because a route broke. Every
route below was **empirically verified in a live 2026-06-18 session** — treat these as the default
playbook, not theory.

Surfaces split into two classes, and you must label which is which in the synthesis:
- **CLI surfaces** (grok / agy-Gemini / codex) read the **actual repo** → code-level findings.
- **Webchat surfaces** (claude.ai / chatgpt / grok web) in a *general* (non-project) chat have
  **NO repo access** → design-level reviews, and they **may invent file/class names**. Weight a
  webchat's specific code-claim *lower* than a CLI's.

---

## 1. Webchat input — the hard part (getting a large prompt INTO a composer)

The composer's DOM type decides everything. Screenshot-verify fidelity **before** submit, always.

### Route matrix (memorize)

| Composer type | Surface | Route that works | Notes |
|---|---|---|---|
| `<textarea>` | grok.com | `computer type` (any language, incl. Korean) → `key Return` | clean, no CJK issue |
| **ProseMirror** (contenteditable) | **claude.ai** | `computer type` with **ASCII / English only** → `key Return` | CJK corrupts — see below |
| any contenteditable | claude.ai / grok | `form_input` ❌ | rejects DIV — see below |
| any contenteditable | (fallback) | `chair_upload_bridge` `cdp_type_text` | needs a live CDP station — see below |

### Why `type` corrupts CJK on claude.ai (the key trap)

Claude-in-Chrome `computer type` **CORRUPTS CJK/Korean inside ProseMirror composers** (claude.ai):
it drops syllables AND spaces — e.g. `9실(총괄/기획...)` arrived as `9(////////)`. The **same**
`type` works perfectly in a real `<textarea>` (grok.com). The corruption is **CJK-IME-composition
specific, not length-specific**.

★ **KEY WORKAROUND**: for a ProseMirror composer (claude.ai), type an **English/ASCII prompt** — it
enters cleanly. Romanize/translate department names etc. to English; **review quality is
unaffected** because the reviewer reasons about structure, not the Korean glyphs. (For grok's
textarea you can keep Korean.)

### Routes that do NOT work (don't waste a turn on them)

- **`form_input`** (set value by ref) **REJECTS contenteditable** → error `Element type DIV is not
  a supported form input`. It only works on real `<textarea>` / `<input>`. So `form_input` is **not**
  a route for claude.ai / grok contenteditable composers.
- **OS clipboard via Bash `pbcopy`** is **SANDBOX-BLOCKED** in this harness (`pbpaste` returns 0
  bytes) → there is **no clipboard-paste route from Bash**.
- **`chair_upload_bridge` `cdp_type_text`** is the *documented* contenteditable-safe route, BUT it
  requires a running **CDP station** (a Chrome launched with `--remote-debugging-port`). Verify with
  `curl http://127.0.0.1:9227/json/version` (also try `9222`). In the 2026-06-18 session **no CDP
  port was live** → bridge unusable without first standing up a logged-in remote-debugging Chrome
  (disruptive). Treat it as a **fallback that needs setup, not a default**.

### Submit discipline

- Keep the typed prompt a **SINGLE logical line** (no embedded newlines) so `type` doesn't submit
  early mid-prompt.
- Submit via `key Return` **only AFTER** a screenshot confirms the composer text is intact.
- If corrupted: clear with `cmd+a` then `Backspace`, and switch to the ASCII route.
- A **"Claude Design" promo modal** can pop mid-type on claude.ai — dismiss it ("나중에") before submit.

---

## 2. Collision avoidance — multiple sessions share the webchat tabs

★ **Principle (user-stated): a DIFFERENT session *generating/thinking* does NOT block you — ONLY the
input MOMENT must not overlap.** Don't over-avoid; you are allowed to use a tab another session also uses.

Routine before typing into any webchat tab:
1. **Screenshot the target tab** to confirm it is NOT mid-generation *right now*.
2. **Open a NEW chat** (새 채팅) per surface to isolate from existing council conversations.
3. A **stale unsent DRAFT** in the composer is *not* an active generation — it can be
   cleared+replaced, but be aware it may be another session's; **prefer a fresh chat**.
4. **Never interrupt an in-progress generation.**

Signals that another session is active: an *unrelated draft* sitting in the composer, or a chat with
a fresh unread / active marker.

---

## 3. CLI surface mechanics

- **grok**: `grok -p "$(cat prompt.txt)"` — first **strip backticks** (`sed 's/`//g'`) or the shell
  command-substitutes them inside the double quotes.
- **agy (Gemini via Antigravity OAuth)**: use the wrapper
  `~/.local/bin/agy-council PROMPT_FILE_PATH ["model"] [timeout_s]`. It takes a **FILE PATH** as
  arg1 (NOT the prompt text — passing text gives "empty prompt"); or pipe via stdin. `agy models`
  lists available models (Gemini 3.5 Flash, 3.1 Pro, …) and confirms OAuth works. (Known limit:
  large inline prompts hang — file-path / chunk it; see the agy memory note.)
- **codex**: `codex exec "<prompt>"` **auto-BACKGROUNDS** for long reviews → read its output file
  when notified. May hit rate limits — **note that honestly, don't fabricate** a verdict.
- **`timeout` is NOT on macOS by default** — use the Bash tool's own `timeout` param instead of the
  `timeout` binary.

---

## 4. Synthesis / honesty

- **Surfaces catch DIFFERENT real defects → diversity beats count** (the Stage 3 invariant, observed
  live). In the 2026-06-18 run: **agy CLI alone** caught a nav-grid `repeat(8,1fr)` layout bug;
  **codex** caught a ratified-backend-contract conflict *by reading the repo*; **claude.ai web Opus**
  gave the best framing; **grok web** converged but, lacking repo access, **hallucinated specific
  class names** — confirming: weight webchat code-claims lower than CLI code-claims.
- **Label repo-access vs not** in the synthesis: CLIs (esp. codex) read the real repo → code-level;
  webchats in a general chat → design-level + may invent file/class names. Say which finding came
  from which class.
- **"유효 N surfaces" honest pattern**: run what's feasible; **explicitly note any blocked/avoided
  surface + WHY** (tool limit, collision, rate limit); **never fabricate a verdict**. A 4–5 surface
  council *with honest notes* is valid — a "fake 8" is not.
- **Neutral framing, refute-first**: ask *"does X conflict?"* not *"X conflicts"* — don't lead the
  reviewer to the answer (same rule as Stage 8 adversarial verify).

---

## Quick checklist (run order)

1. CLIs first (grok / agy file-path / codex-backgrounded) — they read the repo.
2. For each webchat: screenshot tab → new chat → type (ASCII for claude.ai, any lang for grok
   textarea) → screenshot to verify fidelity → `key Return`.
3. Synthesize: tag each finding CLI(code) vs webchat(design), refute-first, report honest surface
   count with reasons for any skipped.
