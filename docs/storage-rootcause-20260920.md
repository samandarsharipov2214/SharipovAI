# Storage incident, 20 September 2026

Owner: General Controller operations; canonical records remain in ProjectDatabase.

## Evidence reused and new measurements

Production runtime resolved through `ProjectDatabase` inside `sharipovai`:
SQLite `/var/lib/sharipovai/sharipovai_saas.sqlite3`, image e4ec31c2e2c0.
Initial measurement: DB 14,547,791,872 bytes; WAL 709,187,992 bytes;
3,551,765 pages of 4096 bytes, only 424 free pages, auto_vacuum=0.
Host available 30,899,724,288 bytes. This is allocated data, not free-page bloat.

Loose index seeks enumerated namespaces without scanning table payloads. Counts
were taken using covering namespace indexes, with 4-second deadlines. A seeded
uniform sample of 1500 rowids per table estimated payload sizes (not exact totals).

| Producer | Rows observed | Sample mean JSON bytes | Classification |
| --- | ---: | ---: | --- |
| council_news_assessments | 423,604 | 11,818 | A: preserve exact decision provenance |
| council_market_evidence | 423,610 | 753 | A |
| risk_assessments | 423,597 | 1,220 | A |
| portfolio_snapshots | 423,605 | 179 | A |
| cost_snapshots | 423,601 | 138 | A |
| trading_candidates KV | 375,012 | 3,113 | A |
| paper_v2_decisions | 271,643 | 2,228 | A |
| PAPER events, both scopes | 1,037,579 | 238–246 | A |
| PAPER trades, both scopes | 2,186 | not sampled | A |
| PAPER settlements | 1,093 | not sampled | A |
| decision_quality events | 421,489 | 2,119 | A |
| economic opportunity events | 421,953 | 3,468 | A |
| trading_candidates events | 375,006 | 3,173 | A |
| market/quote events | 738,513 | 282 | C: operational quotes |
| news_fetch_observations/source_fetch | count exceeded deadline | 456 | C: fetch telemetry |
| news_events | 309,860 | 348 | preserve; no demonstrated deletion policy |

Targeted index-only dbstat probes (12-second deadlines) measured 314,789,888
bytes for the KV primary index, 268,554,240 for the event lookup index, and
155,193,344 for the event primary index: 738,537,472 bytes combined. Index
overhead is secondary to payload growth; no whole-database dbstat scan was run.

Sample timestamps span roughly August–September 2026. Earlier 6.3 GB snapshot
and the owner's later 13.302 GB measurement demonstrate substantial historical
growth; their precise timestamp basis is unavailable, so no daily rate is invented.
New periodic persisted samples measure the actual rate.

`CanonicalCouncilProvider.proposal` writes market, news, portfolio, cost and risk
snapshots for every proposal, including proposals that never execute. The council
news namespace alone has an estimated 5.0 GB of raw JSON. Repeated opinion lineage
is the largest identified payload producer; some sampled rows exceeded 107 KB.
The denominator snapshot normalization already on main reduces new duplication
but does not rewrite historical evidence. No trading/news investigation was rerun.

`SharedVerifiedMarketStream._persist_operational_quote` already explicitly calls
raw quotes operational samples and persists exact decision evidence separately.
`NewsIntelligenceHub._record_fetch_observation` stores fetch status separately
from immutable `news_article_evidence`; council lineage uses article evidence,
not these fetch event IDs. Both operational datasets lacked scheduled expiration.
Unknown namespaces, all messages, Learning, audit and PAPER history stay untouched.

## Change boundaries and recovery

Public ProjectDatabase get/put JSON and list_json_items retain their return shapes.
Only `council_news_assessments.value_json` gains a versioned, SHA-256 checked,
lossless zlib/base64 encoding. Existing plain JSON is still readable. The sample
compressed to about 25% of its original bytes. Explicit bounded conversion keeps
IDs, versions and timestamps, and verifies byte-for-byte expansion before writing.
`--expand` reverses it with writers stopped before rollback to an image without the codec.

No destructive import/startup migration exists. Operational retention defaults to
7 days (configuration bounded 7–30), selects at most 5000 rows per invocation,
uses existing indexed entity/timestamp seeks, and deletes at most 100 rows per
transaction by default. A self-describing gzip cohort is fsynced and fully readback
verified first. Changed rows cannot be deleted by the archived predicate. Archives
of these explicitly disposable cohorts expire after 30 days; canonical records
have no automatic expiry. A pinned WAL backlog halts maintenance.

Backup keeps the 20 GiB floor and 512 MiB reserve. If raw staging cannot fit, it
streams SQLite's logical dump from a pinned read-only transaction into bounded
compressed staging, checks source quick_check and compressed stream readback,
then publishes the hashed tar archive atomically. Manifest schema 2 declares each
logical database, statement count, source logical size and stream hash; schema 1
native archives remain supported. Embedded NUL text, blobs, Unicode and FTS are
covered by restoration tests. Restore happens only in isolated staging, checks
all hashes/bounds and runs quick_check before atomic installation. Restoring a
large DB consumes recovery workspace, with an explicit 1.5x source-size admission
budget and an additional 2 GiB runtime reserve. It does not lower the exporter floor.

Production conversion requires a fresh archive hash plus actual successful restore
evidence. Before compaction, calculate remaining logical bytes and scratch budget.
Stop writers, checkpoint through SQLite, VACUUM INTO an isolated file, quick_check,
compare preserved data, retain original for rollback, and atomically install only
while stopped. Never truncate/delete a live WAL. Retain the exact old OCI image.

## Verification and operations

Focused gates: storage lifecycle/codec/concurrent logical restore tests, exporter
budget/runtime/offline restore tests, existing health/metrics tests and mandated
news/dashboard/architecture tests. Broad checks run on GitHub, not the VPS.

The existing backup job invokes bounded maintenance after successful publication
when the running image implements this contract. It writes a small periodic
storage-metrics.json snapshot; existing health and authenticated Prometheus routes
read that snapshot without expensive health-cycle queries. Metrics include DB/WAL,
namespace counts (unknown if deadline exceeded), growth, free bytes, retention,
backup age/size and alerts for abnormal growth, WAL, backlog, stale backup and disk.

Acceptance results are recorded in the ProjectChangeLedger and PR evidence.
