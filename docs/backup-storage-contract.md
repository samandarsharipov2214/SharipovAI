# Backup storage and publication contract

Owner: General Controller operations; durable data remains owned by ProjectDatabase.
The exporter is `deploy/vps/export_backup.sh`. Deploy, recovery and the systemd
backup service invoke the same exporter. No application schema changes are needed.

The 20 GiB free floor and 512 MiB concurrency reserve remain unchanged. Existing
source files and retained archives already consume disk and must not be added
again to `df` usage. A backup creates a SQLite snapshot/copy staging directory and
a compressed archive simultaneously. Two raw source sizes were a conservative
peak estimate, not a guaranteed exact compression size: archive headers can even
make incompressible data larger. On 2026-09-07 that estimate left only about
20 MiB of headroom after safe BuildKit cache reclamation.

The exporter now reserves one full source-size staging copy, checks free space
while copying and snapshotting, and then writes a compressed archive with both
an immutable byte cap and a current free-space check before every archive write.
It does not assume a compression ratio. A large incompressible archive may fail
after staging; it cannot publish a truncated archive or spend the protected floor.
Concurrent external consumption is additionally covered by the 512 MiB reserve;
no userspace exporter can reserve disk against an unrelated unlimited writer.

Publication still requires archive decompression/list verification and SHA-256,
followed by atomic rename. Failure removes only this export's staging and partial
archive. Retention runs under the exclusive exporter lock after publication and
protects the active archive and latest symlink target, including with skewed mtimes.
No production volumes, existing latest backup, or retained images are reclaimed.

The timer has one hourly calendar with `Persistent=true`. It has no independent
45-minute or boot trigger. Installation explicitly runs and verifies one backup.
Backup freshness monitoring must allow the bounded duration of an in-flight run;
hourly start time and snapshot completion time are different facts.

Rollback: revert this commit and reinstall the previous timer configuration.
Archives keep manifest schema 1 and the existing `manifest.json`/`data` topology;
the existing restore verifier remains compatible. Reverting restores the stricter
two-copy preflight and can block backups again when disk is tight.

The restore verifier's independent 5 GiB per-file limit also rejected the real
6+ GiB canonical SQLite database. Its per-file budget now equals the existing
20 GiB total snapshot budget; aggregate extraction limits, member counts, path
validation, symlink rejection and exact manifest hashes remain enforced.

Verification: `tests/test_backup_phase_budget.py` exercises insufficient/exact
capacity, arithmetic above 64-bit range, large-source estimates, delayed allocation,
concurrent disk consumption, compressible/incompressible archive budgets and
active/latest retention. Existing exporter/runtime/timer/deploy tests remain gates.
Production acceptance separately requires a fresh hash-verified manifest, isolated
restore, and `PRAGMA quick_check` for all three canonical application databases.
An application-volume backup alone does not certify off-host or complete VPS recovery.

## Large SQLite fallback (September 2026)

When the native raw stage cannot fit, the same exporter uses schema 2 logical
SQLite snapshots. The 20 GiB floor and 512 MiB reserve are unchanged. Each database
is read through SQLite in a pinned read-only transaction, quick_checked and emitted
as gzip-compressed JSON-lines of SQL statements. A lossless quote encoder preserves
embedded NULs, blobs and Unicode; supported FTS/rtree shadow tables are retained
without duplicate virtual-table inserts. Unknown virtual modules fail closed.
Each stream has a hash, byte/statement counts, source logical size and quick_check
result. The compressed bytes are read back before archive publication. Neither
source DB nor WAL is copied at file level. Non-SQLite files retain existing capture
semantics. Consumption is checked per compressed write with a fixed byte budget;
a source larger than the existing 20 GiB restore envelope is rejected.

`verify_snapshot` accepts both schemas. `restore_verified_backup` and
`isolated_restore_drill` verify schema-2 archives, then materialize SQLite only in
disposable staging. Statement/byte/hash limits, SQL filesystem-action denial,
SQLite page limits and quick_check precede installation. Isolated restoration
requires 1.5x source logical size plus 2 GiB runtime headroom; this is temporary
recovery workspace, not a lower persistent-backup floor. A failed restore never
installs partial data. Schema-2 backups require these updated restore tools;
older tools reject the schema. Keep the prior verified native backup until an
actual isolated schema-2 restore has passed.

The backup job invokes explicit, bounded operational retention and storage metric
sampling only after successful publication and only when the running application
supports the lifecycle module. See `docs/storage-rootcause-20260920.md` for exact
ownership, archive lifetimes, rollback and production evidence.
