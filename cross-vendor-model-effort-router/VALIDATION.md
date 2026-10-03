# Router 2.7.0 validation checkpoint — 2026-10-03

The publication candidate passed 190 unit tests using `python3 -m unittest discover -s tests -v` from this skill directory. Fixtures contain model metadata only; machine-specific fixture home paths are replaced with `/Users/test-user`.

The installed runtime completed bounded read-only delegation with Claude Sonnet 5.5, Grok 4.7 and Gemini 3.8 Flash Medium, each at medium effort, followed by independent source/response verification and hash-bound result publication. This does not establish write delegation, all models' task quality or provider-signed identity. Earlier failed attempts remain part of the local record.

The companion runtime publication candidate passed 27 integration/regression tests and three standalone predispatch tests. Its project overlay includes current model-loadout modules and transitive dependencies. Automatic model refresh occurs at the next routed call after the account catalog changes; fixed calls preserve their configured defaults.

Production provider resolver SHA256: `e0e9b09b7154ab48cd696925c336f9f93c2e3da979a5eb00cdcd2d095f2bff26`.
Codex inventory SHA256: `fde644aec53b363ef15825fe43f573067d2bd73d618bf6a7f54020972aa268ab`.

The commit excludes local registry additions, credentials, account runtime files, raw provider output and private task/approval records. Repository publication is separate from installation and mainline integration.
