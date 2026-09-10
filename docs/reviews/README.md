# External reviews

Cross-provider reviews of Teyla itself, per POLICY.md §2. Each file is the reviewer's verbatim output;
the commit that follows it says what was accepted. 2026-09-09: Codex (GPT-5.6 Sol, read-only sandbox) and
Grok 4.6 (adversarial) reviewed 0.1.0 — accepted: redacted `--share` mode and fingerprints instead of
correction text (both), regex word-boundary bug (Codex), A5 threshold and A6 cross-harness (both), A9
fingerprints (both), xAI ladder corrected to Grok 4.6 → 4.5 with no third tier (Grok), Grok batch sessions
kept as sessions but excluded from human-turn metrics (Grok), Codex reasoning tokens not double-counted
(Codex), compaction detection by `compact_boundary` subtype (Codex), README overclaims narrowed (both).
Declined: dropping scaffold/products from the pitch (they are the "productize from day one" half of the method).
