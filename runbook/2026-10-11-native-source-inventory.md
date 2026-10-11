# Native opinion source identity inventory

## Native-Code-First Review:

- Need: Give the nightly national coverage audit a machine-readable identity for every requested opinion source, its native court record, and its published source URL without fetching or mutating publisher data.
- Search: Reviewed `cl_scrape_opinions`, Juriscraper `build_module_list`, the native `Court` model, `courts_db.find_court_by_id`, and the Library runner artifacts `enabled-scrapers.json` and `scraper-run-inventory.json`.
- Native option: Reuse the existing CourtListener management command, Juriscraper module inventory, native `Court` rows, and `courts_db` court identities.
- Gap: Existing nightly artifacts retain module names and outcomes but omit court names, jurisdiction classes, state locations, active dates, and source URLs, so they cannot reconcile modules to the national court census.
- Decision: Extend the existing management command with an inventory-only mode and optional JSON output. Do not create another scraper, source registry, or parallel court vocabulary.
- Duplication check: The output is a projection of the command's native module list, `Court` model, scraper attributes, and `courts_db`; it introduces no independently maintained identities or source mappings.

## Root-Cause Review:

- Symptom: A nightly sweep can prove that a set of modules ran yet cannot prove which courts and public decision channels those modules cover, leaving national completeness unverified.
- Root cause: The controller logs execution identifiers only. The court and source identities used to execute those modules are discarded before the Library coverage audit can reconcile them.
- Evidence: `enabled-scrapers.json` is a string list and `scraper-run-inventory.json` contains module outcomes only; the native command already has the instantiated scraper, native `Court`, and `courts_db` record in scope.
- Scope: The affected class is every requested opinion module, including disabled sources. The bounded counterexamples are runtime outcome evidence and the auxiliary `courts_db` taxonomy: this inventory records identity and configuration but does not claim source success or that every public channel has been found. A native `Court` row is authoritative for execution; a missing `courts_db` match remains an explicit reconciliation gap without erasing the native source.
- Fix strategy: Repair the source identity invariant inside the native controller by projecting its own module, `Court`, scraper, and `courts_db` records before scraping, writing that projection atomically or to stdout, and allowing an inventory-only invocation that performs no publisher request.
- Regression test: Unit test `test_source_inventory_uses_native_court_identity` covers the identity projection and excluded payload fields; unit test `test_inventory_only_does_not_fetch_publishers` covers the no-network boundary; unit test `test_unmatched_courts_db_identity_is_reported_separately` covers the auxiliary-taxonomy counterexample.
- Blast radius: The new options are opt-in. Existing scrape behavior is unchanged when they are absent. Removing the options restores prior behavior while causing the Library census evidence gate to remain incomplete.
