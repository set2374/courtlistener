# Opinion scraper transient-failure retry

Native-Code-First Review:

- Need: Recover an official court source when a short transport interruption or HTTP 5xx outage outlasts the native command's immediate retry window.
- Search: Inspected `Command.parse_and_scrape_site` and `Command.handle` in `cl_scrape_opinions.py`, the shared `cl.lib.decorators.retry` helper, and the Library nightly runner. The October 10 production sweep journal was classified by final exception.
- Native option: `parse_and_scrape_site` already owns parsing, scraping, three immediate attempts, exponential backoff, and 5xx classification.
- Gap: After the three attempts occur within 15 seconds, `handle` records a terminal failure and never revisits the source during the remainder of the multi-hour court sweep.
- Decision: Extend `handle` to queue only the native transient exception classes and call the same `parse_and_scrape_site` method once after the first pass.
- Duplication check: This adds no scraper, parser, loader, transport, scheduler, or persistence path. It reuses the existing native command and retry decorator.

Root-Cause Review:

- Symptom: Thirty-nine enabled current sources ended the October 10 sweep on connection failures or HTTP 5xx responses, leaving those official channels stale for the night.
- Root cause: The controller's underlying retry invariant treats three attempts within a 15-second interval as final for the night, even though the full sweep continues for roughly two hours and a transport outage can outlive that narrow interval.
- Evidence: The production journal recorded 35 `httpx.ConnectTimeout` failures, two connection refusals, and two Mississippi 500 responses after the immediate retry decorator ran.
- Scope: `httpx.TransportError` and `TransientOpinionSourceError` failures only. HTTP 4xx/WAF responses, parser failures, invalid documents, and duplicate-integrity failures remain terminal and are not retried by this path.
- Fix strategy: Repair the controller invariant at its source by queueing transient failures during the first pass, waiting once, rerunning them through `parse_and_scrape_site`, and emitting the existing terminal failure marker only when that delayed pass also fails.
- Regression test: The `OpinionSweepControllerTest` unit test class covers recovery on the delayed pass and terminal failure after the delayed pass; its existing 5xx and 4xx cases remain counterexamples for immediate recovery and nonretryable responses.
- Blast radius: A sweep with transient failures may run longer. The second pass is bounded, the service's 12-hour timeout remains authoritative, native duplicate detection remains active, and reverting the controller commit removes the behavior.
