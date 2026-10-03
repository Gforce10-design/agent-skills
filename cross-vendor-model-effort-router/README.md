# Provider catalog router 2.7.0

`python3 router.py catalog --provider all` lists the full observed catalog. Each row includes exact
CLI identity, family/version, supported effort, eligibility and reason. `current_by_family` and
complete alternatives make newer and older models visible without an arbitrary inventory cap.

`python3 provider_catalog.py resolve --provider codex --executable /absolute/path/to/codex
--codex-home /actual/account/home --model latest:gpt-sol --effort medium` returns a JSON binding.
The same module resolves router DIRECT and dispatcher DELEGATE choices. Use `router.py recommend`
with all four core and five break-even axes; optional `--model` and `--effort` select an observed pair.
This general option cannot bypass the separate Fable shadow experiment contract.

Metadata sources: current-account Codex `model/list`; Claude SDK control initialize with no user
messages/tools/MCP/settings/session persistence; native Grok/AGY `models`. Claude native `cc` cache
mapping is fresh, single-account and expected-identity-only. Ambiguous/stale caches never establish
identity; cache-only fallback is visible but unselectable. Live alias-only Claude rows carry empty
usage proof keys. Claude/Grok/AGY live receipts expire after 15 minutes and Codex after 24 hours.
Native Claude cache expiry remains authoritative. Selection revalidates expiry.

Claude Haiku uses no effort flag. AGY uses the exact observed human label with embedded effort.
Grok documented versions accept their exact documented efforts; unknown versions use native default
only unless metadata establishes a dial. Unknown/hidden/ineligible rows remain visible with reasons.

Worker roles, permissions, executable/account staging and usage-proof gates stay intact. Router
DELEGATE forwards its pair; bare dispatcher without a pair retains legacy defaults. Non-Codex DIRECT
is current-session selection only and emits no guessed headless fallback. Codex DIRECT has its
existing bounded `codex exec` contract. Catalog discovery/recommendation never runs a user generation,
logs in, changes a registry, or proves quota, billing, runtime identity or task completion.

Run `python3 -m unittest discover -s tests -q` for parser, expiry, identity, effort, pin and actual
metadata-only CLI/new-backend integrations across four providers and both routes.
