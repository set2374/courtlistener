# Litigus PDF opinion extraction review

Native-Code-First Review:

- Need: Extract public opinions whose provider PDF URL and stored object suffix disagree, while preserving authoritative delta docket metadata.
- Search: Inspected `cl/scrapers/tasks.py:125`, `cl/lib/microservice_utils.py:62`, `cl/lib/privacy_tools.py:9`, `cl/scrapers/tests.py:477`, `pyproject.toml:115`, and installed `site-packages/juriscraper/opinions/united_states/state/me.py:64`.
- Native option: Extend `cl.scrapers.tasks.extract_opinion_content` and reuse the installed Juriscraper metadata extractor plus the existing Doctor `document-extract` then OCR microservice sequence.
- Gap: The task inferred PDF type only from `local_path` and always reparsed and saved docket metadata.
- Decision: Extend the task with a narrow file-type override from `download_url` and an optional metadata-extraction flag.
- Duplication check: This adds no task, parser, scraper, or extraction path.

Root-Cause Review:

- Symptom: PDF-backed public opinions can remain textless or fail before opinion save during delta ingestion.
- Root cause: Two input-contract mismatches affect the opinion class: the stored filename suffix is not always the file-format authority, and optional text-derived metadata is not always valid for persistence even when the opinion text is valid.
- Evidence: Production opinion 11398378 required forced PDF typing; opinion 11399761 emitted an empty `date_argued` value that blocked docket save.
- Scope: The affected class is any opinion whose stored suffix disagrees with a provider URL ending in `.pdf`; the metadata issue is bounded to callers that already hold authoritative docket metadata. A non-PDF URL and a default scraper call are counterexample cases that keep existing behavior.
- Fix strategy: Restore the file-format invariant at the native microservice call by passing `file_type="pdf"` when the provider URL establishes the format, and separate optional metadata persistence from required opinion and cluster persistence.
- Regression test: The unit test `IngestionTest.test_download_url_can_correct_mislabeled_pdf_path` covers format inference; the unit test `IngestionTest.test_extract_content_without_updating_docket_metadata` covers opinion persistence without docket mutation; the existing six `IngestionTest` format cases cover the counterexample paths.
- Blast radius: New metadata behavior is opt-in; task arguments remain backward compatible. The provider URL only overrides a misleading local suffix when it ends in `.pdf`.
