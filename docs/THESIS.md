# Thesis evidence demo

Research only. Not a recommendation. This is an independent, unverified third-party
integration, not verified or endorsed by HPSILab.

## What it is

`hpsilab_research_adapter.thesis` takes the six normalized research results for one
ticker and lines each observed value up against a thesis that **you** state. For each
value it reports one of four stances: `supports`, `challenges`, `neutral` or `context`
(a value that carries no direction). It never chooses a thesis, never produces a
verdict and never gives advice. The live demo is `tools/thesis_demo.py`, run by hand;
the module command is:

```
python -m hpsilab_research_adapter.thesis NVDA --direction up --horizon 10 [--json]
```

## The user-supplied thesis

A thesis is three things you provide: a ticker, a direction (`up`, `down` or `range`)
and a horizon in whole days (1 to 365). Nothing is defaulted inside the module.

## The live demo

`tools/thesis_demo.py [DIRECTION [HORIZON_DAYS]] [--ledger PATH]` (default `up`, 10)
makes exactly one pass over the six GET tools for NVDA with a persistent ledger: by
default `.credits/ledger.json` under the repository root, or the file given with
`--ledger PATH` (for example the main repository's ledger, used directly instead of a
copy). The limits are the same either way:
`max_credits=40`, `total_budget=190` and `min_balance=1800`. The owner approved +40
credits on 2026-11-26 for exactly one NVDA pass beyond the original 150 cap. The script
refuses to start if the remaining total budget is below the price of one pass. It writes
`.probe/thesis_NVDA.md` and `.probe/thesis_NVDA.json` (git-ignored; real values are never
committed) and prints only stance tallies, the missing count and the credits used. Every refusal
(bad thesis, unreadable ledger, budget too low, bad configuration) happens before any
request is sent.

To share a report with an external reviewer, run `tools/thesis_summary.py` on the JSON
file. It prints a Markdown summary that contains no observed value; see the next section.

## The share-safe summary

`python tools/thesis_summary.py .probe/thesis_NVDA.json` reads a report JSON (the file
`thesis_demo.py` or `thesis.to_dict` writes) and prints Markdown with: the thesis
(ticker, direction, horizon), which tools were called and which succeeded, each field
used with its stance label, horizon status and rule text, tallies per stance, the
missing list with reasons, the credits used if the file records them, and the fixed
disclaimer. It never prints an observed price, probability, score, date, level or word
from HPSILab responses; only field names, labels, rule text, counts and reasons.

## Rules (verbatim)

Every rule's text is printed next to the evidence it produced.

- `ai_probability`: Latest ai_prediction item (greatest last_date, else last in list), field ensemble_up_probability (0-1). up: above 0.5 supports, below 0.5 challenges. down: the inverse. range: from 0.45 to 0.55 inclusive supports, otherwise challenges. Exactly 0.5 is neutral for up and down. Horizon unstated.
- `ai_consensus`: model_consensus of the latest ai_prediction item, shown as context only.
- `signal_word`: analyze_stock signal word: a word starting with bull is bullish, bear is bearish, neutral is neutral. up: bullish supports, bearish challenges, neutral is neutral. down: the inverse. range: neutral supports, bullish or bearish challenges. Any other word is unparseable. Horizon unstated.
- `factor_count`: analyze_stock count of bullish_factors versus bearish_factors. up: more bullish supports, more bearish challenges, equal is neutral. down: the inverse. range: equal counts support, unequal counts challenge. Horizon unstated.
- `confidence_score`: analyze_stock confidence_score, shown as context only.
- `mc_median`: monte_carlo median_price versus start_price. up: median above start supports, below challenges, equal is neutral. down: the inverse. range: start_price inside [lower_bound, upper_bound] supports, outside challenges. This range rule is weak because a central interval usually contains the start price. The horizon is the response's horizon_days; evidence for a different horizon is shown but tallied separately.
- `mc_probability`: monte_carlo prob_above and prob_below (0-1), shown as context only. Same horizon handling as the median rule.
- `regime_word`: pretrade_risk_scan regime: a word starting with bull or bear maps like the analyze_stock signal word, neutral is neutral, any other word carries no direction and is context only. Horizon unstated.
- `regime_confidence`: pretrade_risk_scan regimeConfidence, shown as context only.
- `range_90`: pretrade_risk_scan range_90 (lower and upper), shown as context only.
- `option_context`: option_pressure fields are volatility and options-market context only and carry no direction. days_to_expiry is not treated as a horizon.
- `iv_context`: iv_radar fields are volatility context only and carry no direction. Its regime label is a skew description, not a stance.

## Missing evidence and a different horizon

- A tool that failed, a field that is absent and a value of an unexpected type are never
  guessed. Each is listed under **Missing** with the tool, the field (when known) and a
  reason: `tool failed`, `field missing` or `unparseable`. A failed tool records only the
  error class name.
- Only `monte_carlo` states a horizon. Its evidence is marked `match` or `different`
  against your stated horizon; every other tool is `unstated`.
- Tallies are split into two buckets: `matching_or_unstated_horizon` and
  `different_horizon`. Evidence for a different horizon is shown but is never mixed into
  the first bucket.

## Deliberately excluded fields

The `ai_prediction` response contains two suggested price-level fields. They are never
read, never shown and never tallied, because they are phrased as instructions rather
than research observations and this module does not pass such guidance on:

- `ai_prediction` / `suggested_stop_loss_price`
- `ai_prediction` / `suggested_take_profit_price`

## Example report (SYNTHETIC)

Everything below was produced by running `render_markdown` on made-up data: a fake
ticker `SYNTH`, invented numbers, a monte_carlo horizon of 5 days against a stated
horizon of 10, and a deliberately failed `iv_radar` call. None of it is real HPSILab
output and none of it says anything about any security.

````markdown
# Thesis evidence: SYNTH

Stated by the user: direction **up**, horizon **10** days.

> Research only. This is not a recommendation and has not been verified by HPSILab. It applies fixed, documented rules to third-party research output and does not predict or advise.

## Tallies

| Horizon | supports | challenges | neutral | context |
|---|---|---|---|---|
| matching or unstated | 2 | 1 | 0 | 8 |
| different | 1 | 0 | 0 | 2 |

## Evidence

- **analyze_stock** `signal` = "Bearish"
  - stance: challenges; horizon: unstated (unstated)
  - rule: analyze_stock signal word: a word starting with bull is bullish, bear is bearish, neutral is neutral. up: bullish supports, bearish challenges, neutral is neutral. down: the inverse. range: neutral supports, bullish or bearish challenges. Any other word is unparseable. Horizon unstated.
- **analyze_stock** `bullish_factors/bearish_factors` = {"bearish_factors": 1, "bullish_factors": 3}
  - stance: supports; horizon: unstated (unstated)
  - rule: analyze_stock count of bullish_factors versus bearish_factors. up: more bullish supports, more bearish challenges, equal is neutral. down: the inverse. range: equal counts support, unequal counts challenge. Horizon unstated.
- **analyze_stock** `confidence_score` = 55
  - stance: context; horizon: unstated (unstated)
  - rule: analyze_stock confidence_score, shown as context only.
- **ai_prediction** `ensemble_up_probability` = 0.7
  - stance: supports; horizon: unstated (unstated)
  - rule: Latest ai_prediction item (greatest last_date, else last in list), field ensemble_up_probability (0-1). up: above 0.5 supports, below 0.5 challenges. down: the inverse. range: from 0.45 to 0.55 inclusive supports, otherwise challenges. Exactly 0.5 is neutral for up and down. Horizon unstated.
- **ai_prediction** `model_consensus` = "synthetic-consensus"
  - stance: context; horizon: unstated (unstated)
  - rule: model_consensus of the latest ai_prediction item, shown as context only.
- **option_pressure** `atm_iv` = 0.3
  - stance: context; horizon: unstated (unstated)
  - rule: option_pressure fields are volatility and options-market context only and carry no direction. days_to_expiry is not treated as a horizon.
- **option_pressure** `gex_total` = 5.0
  - stance: context; horizon: unstated (unstated)
  - rule: option_pressure fields are volatility and options-market context only and carry no direction. days_to_expiry is not treated as a horizon.
- **option_pressure** `weekly_expected_move` = 1.5
  - stance: context; horizon: unstated (unstated)
  - rule: option_pressure fields are volatility and options-market context only and carry no direction. days_to_expiry is not treated as a horizon.
- **pretrade_risk_scan** `regime` = "chop"
  - stance: context; horizon: unstated (unstated)
  - rule: pretrade_risk_scan regime: a word starting with bull or bear maps like the analyze_stock signal word, neutral is neutral, any other word carries no direction and is context only. Horizon unstated.
- **pretrade_risk_scan** `regimeConfidence` = 0.5
  - stance: context; horizon: unstated (unstated)
  - rule: pretrade_risk_scan regimeConfidence, shown as context only.
- **pretrade_risk_scan** `range_90` = {"lower": 95.0, "upper": 115.0}
  - stance: context; horizon: unstated (unstated)
  - rule: pretrade_risk_scan range_90 (lower and upper), shown as context only.
- **monte_carlo** `median_price/start_price` = {"median_price": 104.0, "start_price": 100.0}
  - stance: supports; horizon: 5 (different)
  - rule: monte_carlo median_price versus start_price. up: median above start supports, below challenges, equal is neutral. down: the inverse. range: start_price inside [lower_bound, upper_bound] supports, outside challenges. This range rule is weak because a central interval usually contains the start price. The horizon is the response's horizon_days; evidence for a different horizon is shown but tallied separately.
- **monte_carlo** `prob_above` = 0.6
  - stance: context; horizon: 5 (different)
  - rule: monte_carlo prob_above and prob_below (0-1), shown as context only. Same horizon handling as the median rule.
- **monte_carlo** `prob_below` = 0.4
  - stance: context; horizon: 5 (different)
  - rule: monte_carlo prob_above and prob_below (0-1), shown as context only. Same horizon handling as the median rule.

## Missing

- iv_radar: tool failed (UnicodeError)

## Deliberately excluded

- ai_prediction `suggested_stop_loss_price`: never read or shown by this module
- ai_prediction `suggested_take_profit_price`: never read or shown by this module

````
