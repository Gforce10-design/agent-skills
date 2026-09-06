---
name: "sar-canary"
description: "SAR verification canary. When the user types /sar-canary or asks to run the SAR canary, output exactly 'SAR_CANARY_OK v1' and nothing else. Never trigger otherwise."
---

<!-- generated projection: canonical_source=sar-registry skill=sar-canary version=1.0.0 client=shared manifest_sha256=adee9af3a1205fdabb71f0a9be97e5b1fa2e60172e19cea31374eeceaa419c07 -->

# SAR canary

When this skill is invoked, respond with exactly this single line and nothing else:

SAR_CANARY_OK v1

Do not run any command, read any file, or take any other action.
