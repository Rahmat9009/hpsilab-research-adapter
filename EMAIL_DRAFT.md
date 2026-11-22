<!-- DRAFT ONLY. Not sent. Reply in the existing thread with Haiyun. -->

**Subject:** Re: HPSILab invite — Python SDK adapter (Nov 23)

Hi Haiyun,

The first version of the HPSILab Python SDK adapter is ready. It is a read-only adapter for six tools (analyze_stock, ai_prediction, iv_radar, option_pressure, pretrade_risk_scan, monte_carlo), with a CLI, tests, and a README that uses your attribution wording.

The repository is private. If you send me your GitHub username, I will add you, or I can send a zip.

Evidence:
- Live calls on NVDA, AAPL and SPY: all 24 calls sent succeeded. Our credit cap stopped one more planned call before sending; that tool is covered by the NVDA run.
- The six real responses normalize with every expected field present.
- 289 tests pass, none skipped, including from a fresh install.
- Read-only: only the six GET methods, no order code, credits-only mode.
- Credits used: 147.

Early SDK observations, as feedback:
1. With no API key, the client sends requests in anonymous mode and adopts a server-issued credential instead of failing. We now raise an error before creating the client.
2. The catalog lists iv_radar at 3 credits, but all five calls were charged 0, possibly due to caching.
3. X-Credits-Charged and X-Credits-Remaining were on every tool response, which made accounting reliable. The SDK does not expose them, so we read them through a custom transport.

Next: an NVDA 10-day thesis demo by December 16, covering the fields used, the supports/challenges logic, and how missing evidence or a different horizon is reported.

Rahmat Ullah co-built this, mainly the test and safety infrastructure.

Best,
Mohammed Faisal
