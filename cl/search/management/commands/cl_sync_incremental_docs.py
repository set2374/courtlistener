"""Apply an enumerated set of record changes to Elasticsearch incrementally.

Why this exists
---------------
`cl_index_parent_and_child_docs` is a BACKFILL tool. Its only scoping flag is
`--pk-offset`, which is a starting floor: there is no upper bound and no
id-list option, so every invocation rewrites each document from the offset to
the top of the corpus. Each rewrite is an `_op_type: "index"` full replace
assembled by `prepare()` from PostgreSQL, and no `prepare_embeddings` exists,
so a rewritten document is written complete in every field the indexer knows
about and simply does not carry an `embeddings` value. Nested fields are not
merged on an index operation, so the previous vector goes with the previous
document.

That is correct behaviour for standing up an index from empty. It is the wrong
tool for incremental maintenance, and the difference is invisible when changes
arrive in ascending id order: new records carry the highest ids, so the floor
sits at the top of the corpus and the sweep looks like a delta. A repair pass
that re-applies one old record drops the floor to the bottom and rewrites
everything above it. In one such run this stripped roughly 6.6M vectors and
forced a re-download of 8,638,532 embeddings from S3 to repair a change set of
a few thousand rows.

Deployments that write to PostgreSQL in bulk with raw SQL cannot rely on the
`post_save` signals that normally drive `cl.lib.es_signal_processor`, and the
one non-signal reconciliation mode, `--update-from-event-tables`, covers only
`search.Docket`, `search.DocketEntry` and `search.RECAPDocument`. This command
fills that gap for opinions and clusters without introducing any new indexing
logic:

  * a document already in Elasticsearch takes a partial `Document.update()`
    carrying the prepared field values minus the structural fields. A partial
    update writes only the fields it names, so the nested `embeddings` value is
    left exactly as it was. This is the same call `update_es_document` ends in.
  * a document not yet present takes `es_save_document`, the ordinary create
    path. A new document has no vector to lose.

Blast radius is therefore bounded by the size of the change set, and stripping
is structurally impossible rather than merely unlikely.

Usage
-----
    manage.py cl_sync_incremental_docs \
        --opinion-ids litigus/semantic/sync-<run>-opinion-ids.txt \
        --cluster-ids litigus/semantic/sync-<run>-cluster-ids.txt \
        --report      litigus/semantic/sync-<run>-report.json

Paths are relative to MEDIA_ROOT, matching how `cl_index_embeddings` addresses
its inventory file. Id files are newline-delimited primary keys. The command
exits non-zero if any document errored, or if the vectored-document count fell
while it ran -- the latter cannot happen on this path, so it is a backstop
against a future change reintroducing a full replace.
"""

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management import CommandError
from elasticsearch.dsl import Document, Q

from cl.lib.command_utils import VerboseCommand, logger
from cl.search.documents import OpinionClusterDocument, OpinionDocument
from cl.search.models import Opinion, OpinionCluster
from cl.search.tasks import es_save_document, get_doc_from_es

# Fields describing a document's identity or placement rather than its content.
# A partial update must never write these.
#   embeddings    - the provider vectors this command exists to protect.
#                   prepare() cannot populate them, so naming the key at all
#                   would blank them.
#   cluster_child - the parent/child JoinField. Rewriting it breaks the join.
STRUCTURAL_FIELDS = ("embeddings", "cluster_child")

TARGETS = (
    # (label, id option, model, ES document, app label)
    # Parents first: an opinion's create path resolves its cluster, so a
    # freshly-added cluster should already be present when its opinions index.
    ("clusters", "cluster_ids", OpinionCluster, OpinionClusterDocument, "search.OpinionCluster"),
    ("opinions", "opinion_ids", Opinion, OpinionDocument, "search.Opinion"),
)


def read_ids(media_relative_path: str) -> list[int]:
    """Read newline-delimited ids from a MEDIA_ROOT-relative file."""
    path = Path(settings.MEDIA_ROOT) / media_relative_path
    if not path.exists():
        raise CommandError(f"id file does not exist: {path}")
    ids = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                ids.append(int(line))
            except ValueError as exc:
                raise CommandError(
                    f"{path}:{line_number} is not an integer id: {line!r}"
                ) from exc
    # Deterministic: the same input does the same work in the same order, so a
    # rerun is a no-op rather than a different traversal.
    return sorted(set(ids))


def vectored_count() -> int:
    """Count documents holding a vector, by nested-exists.

    A plain document count says nothing about vector coverage, because a
    stripped document still counts.
    """
    return (
        OpinionDocument.search()
        .query(
            "nested",
            path="embeddings",
            query=Q("exists", field="embeddings.embedding"),
        )
        .count()
    )


def sync_one(instance, es_document, app_label: str) -> str:
    """Update an existing document in place, or create it if absent."""
    es_doc = get_doc_from_es(es_document, instance)
    if es_doc is None:
        es_save_document.apply(
            args=[instance.pk, app_label, es_document.__name__],
            kwargs={"skip_percolator_request": True},
        )
        return "created"

    fields = es_document().prepare(instance)
    for key in STRUCTURAL_FIELDS:
        fields.pop(key, None)
    if not fields:
        return "skipped"
    Document.update(
        es_doc,
        **fields,
        refresh=settings.ELASTICSEARCH_DSL_AUTO_REFRESH,
    )
    return "updated"


class Command(VerboseCommand):
    help = (
        "Incrementally sync an enumerated set of opinions and clusters into "
        "Elasticsearch without disturbing their embeddings."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--opinion-ids",
            required=True,
            help="MEDIA_ROOT-relative path to newline-delimited Opinion ids.",
        )
        parser.add_argument(
            "--cluster-ids",
            required=True,
            help="MEDIA_ROOT-relative path to newline-delimited OpinionCluster ids.",
        )
        parser.add_argument(
            "--report",
            required=True,
            help="MEDIA_ROOT-relative path for the JSON report.",
        )

    def sync_batch(self, ids, model, es_document, app_label: str) -> dict:
        counts = {
            "requested": len(ids),
            "updated": 0,
            "created": 0,
            "skipped": 0,
            "missing": 0,
        }
        failures = []
        for pk in ids:
            instance = model.objects.filter(pk=pk).first()
            if instance is None:
                # Named in the change set but absent from the table. Reported
                # rather than fatal; the caller's plan is the authority on what
                # should exist.
                counts["missing"] += 1
                continue
            try:
                counts[sync_one(instance, es_document, app_label)] += 1
            except Exception as exc:  # noqa: BLE001 - recorded, then reported
                logger.exception("Failed to sync %s %s", app_label, pk)
                failures.append(
                    {
                        "id": pk,
                        "error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(),
                    }
                )
        counts["failed"] = len(failures)
        if failures:
            counts["failures"] = failures[:20]
        return counts

    def handle(self, *args, **options):
        super().handle(*args, **options)

        id_sets = {
            label: read_ids(options[option]) for label, option, _, _, _ in TARGETS
        }
        report_path = Path(settings.MEDIA_ROOT) / options["report"]

        before = vectored_count()
        logger.info("Vectored documents before sync: %s", before)

        results = {}
        for label, _, model, es_document, app_label in TARGETS:
            results[label] = self.sync_batch(
                id_sets[label], model, es_document, app_label
            )
            logger.info("%s: %s", label, results[label])

        after = vectored_count()
        vectors_preserved = after >= before
        failed = sum(result.get("failed", 0) for result in results.values())
        overall = "pass" if (vectors_preserved and not failed) else "fail"

        report = {
            "overall": overall,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "method": "incremental",
            "native_update_call": "elasticsearch.dsl.Document.update",
            "native_create_call": "cl.search.tasks.es_save_document",
            "full_replace_performed": False,
            "vectored_before": before,
            "vectored_after": after,
            "vectors_preserved": vectors_preserved,
            **results,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))

        if not vectors_preserved:
            raise CommandError(
                f"Vectored documents fell from {before} to {after}. This path "
                "issues partial updates and cannot strip vectors, so something "
                "reintroduced a full replace. Find the writer rather than "
                "re-importing over it."
            )
        if failed:
            raise CommandError(f"{failed} document(s) failed to sync; see {report_path}")
