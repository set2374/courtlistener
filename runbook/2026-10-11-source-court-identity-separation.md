# Native source and court identity separation

Native-Code-First Review:

- Need: retain a stable scraper-source identity while assigning opinions to the scraper's native Court identity.
- Search: inspected `cl/scrapers/management/commands/cl_scrape_opinions.py:320`, `cl/scrapers/tests.py:3062`, the installed dependency pin at `pyproject.toml:145`, and the installed Juriscraper module `juriscraper/opinions/united_states/state/tenn_workers_comp.py`.
- Native option: reuse `build_module_list` output from `cl/scrapers/management/commands/cl_scrape_opinions.py:635` as the canonical scraper identities and the installed Juriscraper `Site.court_id` API as the Court identity.
- Gap: the controller used `site.court_id` for both concepts, so correcting a Court changed the source key.
- Decision: extend the existing inventory and controller boundaries to keep the two native values separate.
- Duplication check: this adds no registry, resolver, inventory, logger, scraper, or ingestion path.

Root-Cause Review:

- Symptom: assigning the Tennessee workers-compensation scraper to `tennworkcompapp` changed its source key and destabilized the 246-source baseline.
- Root cause: the controller violated the source-identity invariant by using one `site.court_id` value both as the scraper-module key and as the destination Court key; those identifiers belong to different classes and can legitimately differ.
- Evidence: the production full-package inventory emitted `source_id=tennworkcompapp` instead of the requested module path, and the controller derived its log key through the same expression.
- Scope: any scraper whose native Court ID differs from its module path. Ordinary one-to-one modules remain unchanged.
- Fix strategy: preserve the requested module path as the source and log key, and derive only the Court lookup from `site.court_id`.
- Regression test: Two unit tests in `cl/scrapers/tests.py`, `OpinionSweepControllerTest::test_source_inventory_separates_module_and_court_identity` and `OpinionSweepControllerTest::test_handle_logs_stable_module_identity_for_distinct_court_id`, cover inventory projection and controller logging when the identities differ.
- Blast radius: source keys stabilize while Court assignment remains correct. The baseline returns to its prior module identity; rollback restores the two original expressions.
