# Kraken Prop: Operational, Legal, and API Specification (GO/NO-GO Report)

## Verdict

**GO, with conditions.** Based on official Kraken support articles, Kraken's own blog announcement, and corroborating trader reports, automated/algorithmic trading is explicitly permitted on Kraken Prop, Washington State residents (and US residents generally) are eligible, standard Kraken API infrastructure (REST, WebSocket, FIX) is available for account and order management, and the daily-loss/max-drawdown mechanics are precisely documented. Several second-order items — whether the Prop trading terminal itself exposes API keys (as opposed to standard Kraken Pro), the exact behavior of broker-side stops during a client disconnect, and the full discretionary-disqualification language in Kraken's Prop-specific terms — remain **ambiguous or unavailable** from public sources and should be confirmed directly with Kraken Support or a signed Funded Trader Agreement before autonomous live capital is committed. Until confirmed, treat protective-stop persistence during disconnection as **unverified** and default to `SUPERVISED_LIVE` rather than `AUTONOMOUS_LIVE`.[^1][^2][^3]

***

## 1. Is automated trading explicitly permitted?

**Confirmed: Yes.** Kraken's own support article is unambiguous: "Clients are welcome to use trading bots to trade our markets". This is a platform-wide policy statement, not limited to spot trading. Kraken further operates a public-facing "Trading bot partners" program specifically for its derivatives products, stating that "the best AI crypto trading bots connect to Kraken Futures via API, letting you automate your strategy around the clock", and Kraken's own blog content instructs users on building REST and WebSocket-based indicator trading bots in Python and Node.js, describing this as "one of the intended uses of our REST API".[^4][^5][^6][^7]

For Kraken Prop specifically, community moderators (Kraken support staff responding under the "Athena" handle in official Kraken subreddits) have directly confirmed: "Yes, automated trading is supported. You're free to use bots and custom-coded strategies, including anything you've built for backtesting". This is corroborated across two independent Reddit threads with Kraken-affiliated responses, satisfying cross-validation. No official Kraken Prop support article was found that restricts trading to manual/discretionary execution only, and Kraken's public marketing explicitly states "no restrictions on trading strategy".[^8][^9][^10]

**Caveat:** These confirmations reference bot use on "Kraken markets" and "Kraken Prop" broadly. Kraken has not published a Prop-specific "algorithmic trading addendum" analogous to the third-party Breakout Prop's detailed Program Rules document. The absence of a published Prop-specific automation policy is itself a gap — Kraken Prop's Terms and Conditions (a legal document, not indexed in support articles) should be pulled in full and reviewed for automation-specific carve-outs before go-live.

## 2. Are US residents (specifically Washington State) eligible?

**Confirmed: Yes.** Kraken announced Washington State was brought fully online in July 2025: "Kraken is thrilled to announce that we are live and fully operational in Washington... residents of the Evergreen State can now access Kraken's full suite of cryptocurrency services". This is corroborated by an independent trade press report from the same period. A community moderator confirmed in June 2025 that WA is not on Kraken's list of restricted states (only Maine and New York are fully restricted; a few additional states are restricted from Babylon staking specifically, which is irrelevant to Prop trading).[^11][^12][^13]

For Kraken Prop specifically, one Reddit thread citing Kraken staff states availability currently spans "the United States, the Netherlands, and France" — narrower than base Kraken access, but inclusive of the US. Kraken Derivatives US (a related but distinct product) requires US-based verification, which is a positive signal for US operational maturity generally.[^14][^10]

**Caveat:** No official Kraken support article enumerates Prop-specific state restrictions the way the base-platform restricted-state list does. Given WA's general eligibility and the Reddit-sourced confirmation of US-wide Prop access, this should be treated as **confirmed with moderate confidence** — verify directly at account signup, since geo-eligibility gates are typically enforced at the point of purchase and would surface immediately.

## 3. Does API access exist for Prop accounts specifically?

**Ambiguous — the most important unresolved question.** Standard Kraken Pro and Kraken Derivatives both have mature, well-documented API infrastructure: a REST API, a WebSocket API (`wss://ws.kraken.com/` public, `wss://ws-auth.kraken.com/` private), and a FIX 4.4 protocol for institutional users, together supporting balances, positions, orders, fills, and account data. Kraken's own guide states the REST/WebSocket/FIX stack "supports automated crypto trading... across spot and futures from a single unified account" and explicitly mentions a dedicated UAT (sandbox) testing environment.[^15][^16][^17]

However, **no official Kraken support article was found describing API key generation or authentication specifically scoped to a Prop evaluation or funded account.** All API-key documentation found ties to standard Kraken Pro or Kraken Derivatives account settings. Kraken Prop's trading terminal is described in third-party sources as syncing "across both Kraken Pro web and the Kraken Pro mobile app", which suggests Prop accounts sit inside the Kraken Pro account structure rather than as an entirely separate platform — this is a reasonable basis to infer that standard Kraken Pro API keys likely extend to Prop sub-accounts, but this is an **inference, not a confirmed fact.**[^18][^19][^20]

**Action required before engineering commitment:** Contact Kraken Support directly (or ask in the account dashboard) to confirm: (a) whether Prop account balances/positions/orders are queryable and tradable via the same API key used for the primary Kraken Pro account, (b) whether a distinct account/sub-account identifier is needed to route orders to the Prop wallet specifically, and (c) whether the UAT sandbox environment can be pointed at a Prop evaluation account for pre-live testing. This is the single highest-priority open item blocking Report 10 (execution engine) and the Kraken adapter design document.

## 4. Are identical strategies, multi-account automation, or copying prohibited?

**Confirmed for the comparable Breakout Prop platform; unconfirmed but likely analogous for Kraken Prop directly.** Kraken Prop's own FAQ confirms users **may run multiple simultaneous evaluation accounts**, up to an aggregate $200,000 across all evaluation and funded accounts combined — this is explicitly permitted, not prohibited: "Yes, you may have more than one active evaluation account, up to a limit of $200,000 across all evaluation accounts". This directly answers the multi-account question for Kraken Prop: **multiple accounts under the same identity are allowed**, subject to the aggregate capital cap, with no stated prohibition on running the same strategy across them.[^18]

No official Kraken Prop document was found addressing copy trading, identical-strategy prohibitions, or discretionary disqualification language comparable to Breakout Prop's detailed Program Rules. Since Kraken co-owns/backs the separate "Breakout" prop platform as well, and that platform's rules are exhaustively documented, it is useful context but **must not be treated as binding on Kraken Prop itself** — they are different products with different terms. For reference, Breakout's rules explicitly prohibit: copy trading of third-party signals, using one strategy to pass evaluation then switching strategies live, account sharing/multi-household trading, running more than one Breakout evaluation simultaneously, and arbitraging across accounts. Kraken Prop's explicit allowance of multiple simultaneous evaluation accounts is a **meaningfully more permissive stance** than Breakout's single-evaluation-at-a-time rule.[^21][^22][^23]

**Gap:** Kraken Prop's own Terms and Conditions (not retrieved in full text via public search) should be obtained and reviewed specifically for clauses on: identical/mirrored strategies across the permitted multiple accounts, "one strategy to pass, different strategy live" prohibitions, and any anti-arbitrage clause. Given the explicit multi-account allowance already confirmed, the risk profile here is lower than initially assumed, but the absence of a fully public terms document is a residual gap.

## 5. Does Kraken retain broad discretionary disqualification authority?

**Confirmed, but bounded.** Kraken's Global Terms of Service state: "We may reject any Trade or other transaction at our sole discretion, whether confirmed by you or not, and we are not liable to you for any rejection". Separately, Kraken's general account-restriction policy lists specific, enumerated grounds for restricting any account: security issue detection, suspected malicious activity, chargebacks, KYC/identity-information failures, failure to respond to information requests, and "a violation of our Terms of Service". This is a real discretionary-rejection power over individual trades, and a real account-restriction power for enumerated cause — but it is **narrower** than an open-ended "we may disqualify any behavior we deem unfair" clause. It reads as consistent with standard exchange risk-management practice (protecting against fraud, manipulation, and compliance failure) rather than a subjective performance-based disqualification lever aimed at penalizing profitable systematic traders.[^24][^25]

Kraken Prop's evaluation-specific breach mechanics are entirely rules-based and deterministic — breach triggers are limited to the MDL/MDD thresholds being touched, with no discretionary "trading style" review mentioned in any official Prop article. This is a meaningfully lower-risk profile than firms with vague "unrealistic trading" clauses. That said, the enumerated ground "a violation of our Terms of Service" is only as narrow as the Terms of Service themselves, and since Kraken Prop's full ToS text was not retrieved, an unreviewed automation-specific restriction could theoretically exist there. This should be treated as the second-highest-priority follow-up after the API-scoping question in Section 3.[^26][^1]

***

## 6. Daily-loss and maximum-drawdown mechanics (worked examples)

Kraken Prop's loss-limit mechanics are precisely and consistently documented across three official support articles.[^2][^3][^1]

**Maximum Daily Loss (MDL):**
- Recalculated once per day, at 00:30 UTC, based on the account's **balance** (not equity) at that moment.[^1][^2]
- MDL = 3% of that balance, for all Kraken Prop plan tiers.[^1]
- Breach condition: current **equity** (balance plus unrealized P&L on open positions) falling below `(balance at 00:30 UTC) − 3%` at any point during the following 24 hours.[^1]
- Worked example (official): on a $100,000 account, MDL = $3,000. If equity falls $3,000 or more from the day's starting point, breach triggers immediately.[^1]
- Both realized and unrealized P&L count in real time — open positions affect the limit continuously, not just at close.[^1]
- Trading fees (commission + margin funding) reduce balance and therefore count against MDL.[^18][^1]

**Maximum Drawdown (MDD):**
- Cumulative, account-lifetime limit measured from the **starting balance**; does not reset daily.[^3]
- Tier-dependent, and **static** (does not trail up with gains) on the base plan structure Kraken documents:

| Tier | Max Drawdown |
|---|---|
| Starter | 6%[^1] |
| Intermediate | 5%[^1] |
| Advanced | 3%[^1] |

- Breach condition: equity dropping to or below `starting balance − MDD%` at any point in the account's life.[^3][^1]

**Breach consequences (both MDL and MDD identical):** all open positions and pending orders are closed immediately and automatically; the account is marked Breached and disabled; a notification specifies the breach reason, timestamp, and equity at breach; the breached account remains visible for 7 days before removal from the account switcher; a new evaluation can be purchased immediately, with **no waiting period**.[^26][^1]

**Profit target and completion:** there is no time limit on evaluations — "take as long as you need". On reaching the profit target, all open positions are automatically closed, the evaluation is marked Passed, and a new funded account is created (initially with trading disabled) pending KYC verification and signature of a Funded Trader Agreement. This directly validates the CTO's decision-tree assumption in Section H of the questionnaire: since positions are forcibly flattened at target, a strategy that stops trading and flattens deliberately on hitting target loses nothing versus letting Kraken force it, and gains determinism and journal clarity.[^2][^1]

**This resolves the "does the daily reset snapshot use balance or equity" open question decisively:** the reset snapshot uses **balance**, explicitly excluding open positions/unrealized P&L, at the moment of calculation. This means the "flat 30 minutes before reset" policy in the questionnaire is not strictly required by the mechanics of the MDL calculation itself (the balance snapshot at 00:30 UTC is unaffected by concurrently open positions), but remains prudent because equity is what determines *breach* against the newly calculated limit for the next 24 hours, and any open position at the exact snapshot moment carries forward its unrealized P&L into the new day's exposure base.[^22][^1]

## 7. Do broker-side protective stops remain active during a client disconnect?

**Unavailable from public sources — treat as unverified and design defensively.** No official Kraken Prop or Kraken Pro article was found explicitly confirming that resting stop-loss, stop-loss-limit, or take-profit orders continue to be held and triggered by Kraken's matching engine independent of the client's live connection. This is standard behavior for exchange-native (as opposed to client-side/EA-simulated) stop orders on essentially all major exchanges, since the order sits on the venue's books once submitted — Kraken's own tutorials describe stop-loss orders as being "in the system" once the trigger price condition is met, waiting server-side "in the wings" until triggered, which is consistent with server-side (not client-side) order management. Kraken Pro's dedicated bracket order (Take Profit/Stop Loss, OCO-style) feature is available "when placing most order types... on any Kraken Pro spot market," reinforcing that these are exchange-native order types, not third-party client software constructs.[^27][^28][^29]

This is a **reasonable inference but not a documented guarantee for Prop specifically.** Given the CTO's hard requirement (H.164 in the questionnaire) that broker-side protection must survive disconnection or the venue is "unfit for autonomous operation," this question should be **directly confirmed with Kraken Support in writing** before promoting past `SUPERVISED_LIVE`. Until written confirmation exists, the system design should default to the supervised posture the CTO already recommended.

## 8. Order types, instruments, leverage, and execution mechanics

**Order types available on Kraken Prop** (confirmed via official FAQ): Market, Limit, Stop Loss, Stop Loss Limit, Take Profit, Take Profit Limit; all limit-type orders are Good-Til-Cancelled (GTC). This directly satisfies the questionnaire's v1 order-type requirement (limit, marketable limit, stop-market protective, reduce-only-limit take-profit) — Kraken Prop natively supports stop-loss (market-triggered) and take-profit (limit-triggered) order types matching the CTO's design.[^18]

**Bracket/OCO behavior:** Kraken Pro's spot platform supports native Take Profit/Stop Loss bracket orders in Simple or Advanced mode for most order types. This is evidence (though not Prop-specific confirmation) that bracket-style order linkage does not need to be fully emulated in the trading engine — native support likely exists. This should be validated directly on a Prop evaluation account before finalizing the execution engine design in Report 10, but reduces the CTO's assumed engineering burden.[^28]

**Instruments and leverage:** Kraken Prop trades "crypto contracts," with the specific pairs shown in the platform's own market selector. Third-party video walkthroughs (non-official, treat as indicative only) describe BTC and ETH as available at 5x leverage on Starter-tier accounts specifically. No official Kraken Prop article enumerating the full initial tradable-instrument list was retrieved; this should be confirmed live in the Kraken Prop terminal, consistent with the questionnaire's own decision to start with BTC and ETH only regardless.[^30][^2]

**Fees:** Commission of 4 basis points (0.04%) per side of every trade; margin funding fee of 0.033% per day, charged every 4 hours on open positions; all fees reduce account balance and therefore count toward MDL/MDD calculations. This gives an exact, official cost model input for Report 2's execution-cost work and for the risk kernel's cost-share gate (I.137–138 in the questionnaire).[^18]

**Payouts (funded accounts only):** requested via "Request Payout" in the Portfolio page; requires no open positions/orders and balance equal to equity; processed as an internal ledger transfer to the main Kraken Pro wallet, typically under 12 hours and guaranteed within 24 hours; default profit split is 80/20, upgradeable to 90/10 for an additional fee at evaluation purchase time. A community-support response confirms that during a pending payout, the daily-loss equity limit is reduced by the withdrawal amount until the payout completes, then recalibrated at the next 00:30 UTC roll based on the updated balance — meaning a payout request does not create a "free" exposure gap, but neither does it permanently affect the drawdown floor after the next reset.[^31][^32][^18]

## 9. Rule-change history and notification practice

**Unavailable.** No public archive of Kraken Prop rule-change history was found; the program was only announced/launched around May 2026, giving it a short public track record. No dedicated changelog or rule-change-notification article was located. This should be tracked internally going forward (per the questionnaire's S. section requirement for a rule-change audit trail) since no external source can substitute for direct monitoring of Kraken's own support-article updates and email notifications.[^9]

***

## Summary table: GO/NO-GO criteria

| Question | Status | Confidence |
|---|---|---|
| Automated trading explicitly permitted | Confirmed — yes[^8][^5][^10] | High |
| US / Washington State eligibility | Confirmed — yes[^11][^13][^10] | High |
| API access exists for Prop accounts | Ambiguous — standard Kraken API stack exists[^15][^17]; Prop-specific scoping unconfirmed | Medium — requires direct confirmation |
| Multi-account / identical-strategy restrictions | Partially confirmed — multiple accounts explicitly allowed[^18]; identical-strategy language not found in Kraken's own terms | Medium |
| Broad discretionary disqualification authority | Confirmed but bounded to enumerated causes plus general ToS violation[^24][^25] | Medium-High |
| Exact MDL/MDD formulas | Confirmed, with worked examples[^1][^2][^3] | High |
| Venue-side stop persistence during disconnect | Unavailable — inferred from exchange-native order architecture[^27][^28] | Low — must be confirmed directly |

## Recommendation

Proceed to Report 2 and the remaining research track under a **provisional GO**, but hold the architecture at `SUPERVISED_LIVE` (per the questionnaire's own B.11 answer) rather than advancing toward `AUTONOMOUS_LIVE` until three items are confirmed in writing directly from Kraken Support or the Funded Trader Agreement: API key scoping for Prop sub-accounts, venue-side stop persistence during disconnection, and the full text of Kraken Prop's Terms and Conditions regarding automation and multi-account strategy identity. None of these findings surfaced information that would force a pivot to a BLOCKED or SUPERVISED-ONLY-PERMANENT verdict — the platform's public posture is unusually automation-friendly relative to comparable prop platforms, and its loss-limit mechanics are fully deterministic and already compatible with tradekit's existing risk kernel design.

---

## References

1. [How Kraken Prop Evaluations Work](https://support.kraken.com/articles/how-kraken-prop-evaluations-work) - Rules of the evaluation. Every evaluation has three key parameters: Profit Target The percentage gai...

2. [What is Kraken Prop?](https://support.kraken.com/articles/what-is-kraken-prop) - Kraken Prop follows a simple two-stage model: Stage 1: Evaluation You purchase an evaluation account...

3. [Maximum Drawdown (MDD) Explained](https://support.kraken.com/articles/maximum-drawdown-mdd-explained) - The Maximum Drawdown (MDD) is the total amount your Kraken Prop account can lose from the starting b...

4. [Trading bot partners](https://support.kraken.com/articles/360041402071-trading-bot-partners-derivatives) - The best AI crypto trading bots connect to Kraken Futures via API, letting you automate your strateg...

5. [Does Kraken allow trading bots?](https://support.kraken.com/articles/360001373983-does-kraken-allow-trading-bots-) - Clients are welcome to use trading bots to trade our markets. Kraken does not. Geographic restrictio...

6. [REST API indicator based trading bot (Python)](https://support.kraken.com/articles/4462673939220-rest-api-indicator-based-trading-bot-python-) - One of the intended uses of our REST API is to create automated trading bots that interact with our ...

7. [REST API - Indicator based trading bot (Node.js)](https://support.kraken.com/articles/5831222353556-rest-api-indicator-based-trading-bot-nodejs-) - One of the intended uses of our REST API is to create automated trading bots that interact with our ...

8. [Kraken Prop Question trading : r/KrakenSupport](https://www.reddit.com/r/KrakenSupport/comments/1u4qxf1/kraken_prop_question_trading/) - Yes, automated trading is allowed on Kraken Prop. You're free to use bots and custom-built strategie...

9. [Introducing Kraken Prop: trade with our money, not yours](https://blog.kraken.com/product/prop/introducing-kraken-prop) - There are no time limits on evaluations, no consistency rules, no profit caps, and no restrictions o...

10. [Introducing Kraken Prop : r/Kraken](https://www.reddit.com/r/Kraken/comments/1tpcfu1/introducing_kraken_prop/) - Yes, automated trading is supported. You're free to use bots and custom-coded strategies, including ...

11. [Washington State: Kraken is open for business!](https://blog.kraken.com/news/welcome-washington-state) - Washington State residents can now create accounts, trade and access the full suite of our crypto se...

12. [Digital Assets Platform Kraken Now Operational In ...](https://www.crowdfundinsider.com/2025/07/245903-digital-assets-platform-kraken-now-operational-in-washington-state/) - Kraken noted after a period of regulatory alignment and platform enhancement, Washington resident ma...

13. [Is kraken available in WA now? : r/KrakenSupport](https://www.reddit.com/r/KrakenSupport/comments/1lkqure/is_kraken_available_in_wa_now/) - Noticed that the kraken page doesn't list WA as unsupported anymore, with an exception of "Bablylon ...

14. [Kraken Derivatives eligibility requirements](https://support.kraken.com/articles/360023786632-kraken-derivatives-eligibility) - Kraken Derivatives US is only available to clients in the United States. Verification requirements G...

15. [Kraken API | REST, WebSocket and FIX APIs](https://www.kraken.com/features/trading-api) - Automate your first trade in minutes Connect to every Kraken market through dedicated REST, WebSocke...

16. [Kraken WebSocket API - Frequently Asked Questions](https://support.kraken.com/articles/360022326871-kraken-websocket-api-frequently-asked-questions) - Trading via the WebSocket API is available via the addOrder and cancelOrder endpoints, which are use...

17. [Kraken API Unlocked: automated crypto trading on Kraken](https://blog.kraken.com/product/api/unlocked-1-strategies-infrastructure-and-where-to-start) - Kraken's API supports automated crypto trading via REST, WebSocket, and FIX 4.4 protocols across spo...

18. [Kraken Prop Frequently Asked Questions](https://support.kraken.com/articles/kraken-prop-faq) - You complete an evaluation to prove your trading skills, then receive a funded account where you kee...

19. [How to create an API key on Kraken Pro](https://support.kraken.com/articles/how-to-create-an-api-key-on-kraken-pro) - API keys are one of the primary components of API authentication; they are the API equivalent of you...

20. [How to create an API key for Kraken Derivatives](https://support.kraken.com/articles/360022839451-how-to-create-an-api-key-for-kraken-derivatives) - 1. Sign in to your Kraken Derivatives account. · 2. Click on your name on the upper-right corner. · ...

21. [Get Funded to Trade Crypto | Breakout x Kraken](https://www.kraken.com/breakout) - Breakout is a crypto-native prop trading platform backed by Kraken. It provides qualified traders wi...

22. [Mastering Drawdown: A Guide to Equity Limits at Breakout](https://www.breakoutprop.com/article/mastering-drawdown-a-guide-to-equity-limits-at-breakout/) - The calculation is based on the balance, which means that at 0030 UTC the maximum daily loss equity ...

23. [Breakout vs Crypto Fund Trader: full crypto prop firm comparison (2026)](https://www.kraken.com/learn/breakout-vs-cryptofundtrader) - Breakout has zero consistency rules — there are no restrictions on how your profits are distributed ...

24. [Global Terms of Service](https://www.kraken.com/legal/global-terms) - We may reject any Trade or other transaction at our sole discretion, whether confirmed by you or not...

25. [Why is my account restricted?](https://support.kraken.com/articles/why-is-my-account-restricted) - 1. Ensure that your account is fully verified and meets our eligibility criteria, that you reside in...

26. [Kraken Prop Account States Explained](https://support.kraken.com/articles/kraken-prop-account-states-explained) - Every Kraken Prop account has a status that determines what you can do with it. Here's what each sta...

27. [Kraken Pro Stop Loss Order Tutorial (How to Set a Stop Loss)](https://www.youtube.com/watch?v=jBoBpWqOdfw) - Kraken Pro stop loss order tutorial - how to set a stop loss on Kraken Pro. How to Use a Trailing St...

28. [Take Profit / Stop Loss (bracket) orders](https://support.kraken.com/articles/bracket-orders-on-kraken-pro) - “Take Profit / Stop Loss” is available when placing most order types (except Trailing Stop orders) o...

29. [KRAKEN PRO - HOW TO SET A STOP LOSS - TUTORIAL ...](https://www.youtube.com/watch?v=udFm9JJl4Dg) - In this video I will show you how to set a stop loss on Kraken Pro. You can set stop loss market ord...

30. [How Kraken Prop Works (Beginner Guide)](https://www.youtube.com/watch?v=fGSb-Y-LUm8) - This material has been prepared for entertainment purposes only, relied on for, tax, legal or accoun...

31. [Kraken Prop Question : r/KrakenSupport](https://www.reddit.com/r/KrakenSupport/comments/1ty3q5d/kraken_prop_question/) - If I open no new trades and withdraw $500 bringing my total equity to $10,100, will my account be cl...

32. [Payout Review & Approval Process](https://support.kraken.com/articles/payout-review-and-approval-process) - The guaranteed maximum review time is 24 hours. After approval. The payout amount is removed from yo...

