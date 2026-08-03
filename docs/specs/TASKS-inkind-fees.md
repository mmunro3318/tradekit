# TASKS — in-kind crypto fee fix (SPEC-inkind-fees.md)

### T1: fill payload field + fee_rate accessor
satisfies: AC-1, AC-10
files: src/tradekit/contracts/_event_payloads.py, src/tradekit/costs.py, tests/unit/contracts/test_event_payloads.py, tests/unit/test_costs.py
done: AC-1/AC-10 tests green via tk-gate

### T2: broker fill physics (paper + alpaca in-kind withhold)
satisfies: AC-2, AC-3, AC-4, AC-5, AC-6
files: src/tradekit/broker/_paper.py, src/tradekit/broker/_alpaca.py, tests/unit/broker/test_paper_fills.py, tests/unit/broker/test_paper_account_state.py, tests/unit/broker/test_alpaca_broker.py
done: AC-2..6 tests green via tk-gate; MONEY-PATH (broker/) — review round before commit

### T3: compute_pnl in-kind arithmetic + live-receipts golden + docs
satisfies: AC-7, AC-8, AC-9, AC-11
files: src/tradekit/thesis/_grade_wiring.py, tests/golden/test_inkind_fee_pnl.py, tests/unit/thesis/test_grade_verb.py, docs/GLOSSARY.md, tests/ASSUMPTIONS.md
done: AC-7..9 tests green via tk-gate; GLOSSARY + ASSUMPTIONS entries landed
