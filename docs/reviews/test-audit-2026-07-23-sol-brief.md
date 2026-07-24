# Sol brief — external second-opinion test audit (carry to GPT-5.6 / Gemini)

> Purpose: get an INDEPENDENT brutal review of the tradekit test suite from a
> non-Claude model, to challenge or confirm the Claude audit in
> `docs/reviews/test-audit-2026-07-23.md`. Paste this brief + let the model
> read the repo (or paste the files it asks for). Mike carries this.

## The setup (give the model this context verbatim)

tradekit is an event-sourced paper/live trading toolkit (Python/uv). It has
"1000+ passing tests" across `tests/unit | contract | replay | golden`, and
that green count has been treated as the safety signal.

Tonight we found that the production scan strategy **S1 has been structurally
incapable of firing a single trade since it was written.** Root cause:
`src/tradekit/hud/_build.py` sets `_SETUP_FILTERS = {"macd_signal": "bullish", ...}`,
but `src/tradekit/mae/_scanner.py` (~L244-260) accepts only the enum
`"bullish_cross"`/`"bearish_cross"` and sends every other value down an
unconditional `else: return None`. So the momentum filter rejected 100% of
candidates on every scan, silently, with zero warnings — while all 1000+
tests stayed green.

The Claude audit concluded: the units are well-tested; the failure lived in a
**seam between modules** that the suite mocks on both sides, making the whole
bug class invisible. It also found `tests/.../test_scan_markets_verb.py:490`
**codifies the silent drop as correct** (feeds an unknown value, asserts
`matches == []`) — so the suite was green *because* the bug existed.

## What we want from you (the model)

1. **Independently verify or refute** the Claude audit's central claim: that
   this suite systematically cannot catch inter-module contract/seam bugs.
   Don't just agree — look for counter-evidence and for holes the Claude audit
   missed.
2. Find the **other** places where a green test coexists with a latent silent
   failure — especially money-path (`src/tradekit/policy/`, `src/tradekit/broker/`).
3. Assess the project's testing DOCTRINE itself (stated in CLAUDE.md: "tests
   protect behavior, not implementation"; sanctioned monkeypatch seams are
   only `mae._runtime.get_closed_bars`/`_clock`). Is the doctrine sound but
   unevenly applied, or is the doctrine itself the problem?
4. Give a prioritized, concrete TDD action list (money-path first), and
   explicitly say where you DISAGREE with the Claude audit's action list.

## Questions to force a sharp answer
- What is the single highest-risk untested behavior in the money path?
- Which existing tests would survive a real bug (i.e. are theater)?
- If you could add only 5 tests, which 5, and what bug does each catch?

Return: a blunt verdict paragraph + a disagreement section vs the Claude audit
+ your top-10 TDD items. Mike will reconcile both audits into the tk-implement
backlog.
