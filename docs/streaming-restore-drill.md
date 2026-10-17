# Isolated streaming restore drill

`tools.streaming_restore_drill` restores an existing canonical archive into a
new private directory without either extracted compressed snapshot tree. It
never activates restored data, starts network services, or changes production.
The existing snapshot-based restore and drill APIs remain supported.

Use a published archive's immutable filename (not the mutable `latest` symlink)
and its verified SHA-256 receipt. Coordinate with the canonical export/deployment
locks: do not run a drill concurrently with export or deployment. Run the command
under the approved bounded systemd recovery service and its resource limits:

```sh
python -m tools.streaming_restore_drill \
  --archive /absolute/path/published-backup.tar.gz \
  --expected-sha256 VERIFIED_ARCHIVE_SHA256 \
  --destination /absolute/path/new-isolated-drill \
  --timeout-seconds 7200
```

The complete first streaming pass validates the archive SHA, gzip integrity,
member types, paths, counts, sizes, exact manifest membership and file hashes
before executing any SQL. The same open source descriptor is rewound for restore;
its identity, member hashes and full archive hash are checked again. The original
manifest is retained separately from the materialized manifest.

`estimate_restore_workspace(manifest)` provides a conservative admission estimate
from a validated manifest. It is planning information, **not archive verification**.
It sums every database's unchanged `min(32 GiB, 1.5 * logical_bytes + 16 MiB)` budget,
all nonlogical output, metadata/slack, and the unchanged 2 GiB runtime reserve.
Per-database admission, maximum page allocation, bounded statements, stream
hashes, SQL restrictions and continuous free-space checks remain mandatory.
The drill also verifies the final file manifest, full SQLite integrity, source
identity and final reserve before reporting success.

Only `restore_drill_report.json` with `status=ok` establishes completion.
`in_progress`, a service start, or exit without the report is not acceptance.
An error preserves diagnostics in the exclusively created directory and never
publishes success. Do not delete source archives, production files or other runs
when cleaning a failed drill. A completed disposable restored copy may be removed
only after its report and required history/accounting comparisons are preserved.

This tool does not itself prove deployment identity, PAPER profitability, or
production accounting reconciliation. Those remain separate acceptance stages.
