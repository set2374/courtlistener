# Native opinion sweep controller reliability

## Native-Code-First Review:

- Need: Preserve the production multi-court opinion sweep's ability to identify every enabled module, retry ordinary transient failures, and return a failed process status when any source fails.
- Search: Reviewed `cl/scrapers/management/commands/cl_scrape_opinions.py`, `cl/lib/decorators.py`, Juriscraper's native `build_module_list`, the production source-engine diff, and the Library native-sweep log parser.
- Native option: Reuse the existing CourtListener management command, retry decorator, Juriscraper module loader, logging path, and `CommandError` exit behavior.
- Gap: The deployed retry and per-enabled-module failure contract existed only as a dirty production overlay and was absent from the fork's `main` branch.
- Decision: Extend the native management command with the narrow behavior already running in production and cover it with command-level regressions.
- Duplication check: This adds no scraper, runner, queue, source adapter, or monitoring path; the existing command remains the only ingestion controller.

## Root-Cause Review:

- Symptom: A clean source-engine rebuild could remove the module start/failure markers and final nonzero verdict required by the Library nightly sweep, allowing failed sources to become unobservable or ambiguously attributed.
- Root cause: The underlying source-of-truth invariant was broken: production command behavior lived in an uncommitted deployment overlay instead of the publishable CourtListener fork from which clean images are built.
- Evidence: The production diff contains transient retry, invalid-document failure, enabled-module markers, and aggregate `CommandError`; commit `8e25c701081e2af8ca0a05e7c5dcf359263986fc` does not.
- Scope: The affected class is current multi-court opinion scraping across every enabled module. Transport failures and HTTP 5xx responses are transient; the bounded counterexamples are HTTP 4xx responses, which remain immediate failures, and disabled court modules, which remain skipped. A skipped invalid opinion makes its enabled source fail.
- Fix strategy: Restore the source-of-truth invariant with a source-level repair in the native management command, then keep the Library runner as a consumer of that command's logs and exit status.
- Regression test: The named tests in `OpinionSweepControllerTest` cover the failed-module fixture and nonzero completion, the transient-5xx retry class, and the non-retryable-4xx counterexample; the nightly Library sweep remains the production canary for marker conservation.
- Blast radius: The opinion-scraper management command only. Existing successful source ingestion is unchanged. Reverting the command commit restores prior behavior; the Library sweep will then fail its controller-completeness contract rather than silently certify coverage.
