# External reviews

Cross-provider reviews of Teyla itself, per POLICY.md §2. Each file is the reviewer's verbatim output;
the commit that follows it says what was accepted. 2026-09-09: Codex (GPT-5.6 Sol, read-only sandbox) and
Grok 4.6 (adversarial) reviewed 0.1.0 — accepted: redacted `--share` mode and fingerprints instead of
correction text (both), regex word-boundary bug (Codex), A5 threshold and A6 cross-harness (both), A9
fingerprints (both), xAI ladder corrected to Grok 4.6 → 4.5 with no third tier (Grok), Grok batch sessions
kept as sessions but excluded from human-turn metrics (Grok), Codex reasoning tokens not double-counted
(Codex), compaction detection by `compact_boundary` subtype (Codex), README overclaims narrowed (both).
Declined: dropping scaffold/products from the pitch (they are the "productize from day one" half of the method).

2026-09-10: Grok 4.6 reviewed the control plane (0.6.0) adversarially — seven P1s (single `&` segments,
env-prefix git aliases, redirection past fs.write, agent-writable grants and action log, approve
reloading tampered grants, kill switch not re-checked before act) and nine P2s. All P1s and P2s
8–16 fixed in 0.6.1 with an exploit test each; residual risks are listed in docs/CONTROL-PLANE.md.

2026-09-10, pass 2: Grok 4.6 re-reviewed the hardened control plane — five new P1s (newline never a
separator, `#` stripped mid-token, git's executable env vars, the HMAC key readable by the run,
promotion not bound to capabilities) and four P2s. All fixed in 0.6.2 with exploit tests; the
residual list in docs/CONTROL-PLANE.md now states that `shell:*` or any interpreter grant is full
trust and that reads are unconfined.

