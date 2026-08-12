# Alpha Evidence Ledger — Candidate v1

This ledger distinguishes source-controlled readiness from real market evidence.
It must not be used to imply profitability before an immutable OOS result exists.

## DONE — source-controlled protocol

- Non-benchmark candidate identity: `regime_filtered_breakout_v1`.
- Economic hypothesis is explicit and immutable in preregistration.
- Falsification rule is derived from frozen acceptance criteria and immutable in preregistration.
- Strategy parameters, exact clean code SHA, dataset-manifest SHA, cost model, risk model, timing, ranges and benchmarks are bound before final OOS.
- Both preregistration and final-OOS CLIs reject a dirty Git worktree, preventing uncommitted strategy/code drift under a valid commit SHA.
- Canonical historical-data gate requires final-OOS-eligible provenance.
- Every declared symbol must cover the complete manifest start/end range; partial leading/trailing symbol history is blocked from final OOS.
- Close-derived bar datasets require exact interval cadence; both missing and irregular short/offset intervals block final OOS.
- Close-derived bars use canonical next-event execution semantics.
- Synthetic finalization is excluded from organic closed-trade sample and expectancy.
- Organic-trade expectancy includes a deterministic 95% circular block-bootstrap uncertainty interval.
- Default acceptance requires the lower 95% block-bootstrap expectancy bound to be positive once the preregistered minimum organic sample is reached; a positive point estimate alone cannot ACCEPT.
- Final report exposes readable dataset identity plus content-addressed manifest SHA.
- Final OOS is one-shot by **dataset-manifest SHA + exact holdout range** through an atomic dataset-side `.alpha_consumed` receipt. Changing experiment ID/fingerprint, parameters, artifact path or report filename cannot reopen the same dataset holdout.
- A crash after final-OOS claim leaves that dataset holdout consumed and fails closed rather than allowing a second look.
- Preregistration artifacts and result artifacts use exclusive creation and cannot be silently overwritten in a race.
- Public Bybit Spot importer validates returned market category and symbol identity in addition to request parameters.
- Final result vocabulary is `ACCEPT_FOR_LONGER_PAPER`, `REJECT_HYPOTHESIS`, or `INSUFFICIENT_SAMPLE`.
- No verdict automatically starts Paper or enables Testnet/Mainnet.

## ACTIVE — real evidence

- Build a real canonical Bybit Spot historical dataset outside Git using the public read-only importer.
- Persist its manifest, SHA-256, per-symbol coverage, gap/duplicate/cadence/timestamp-semantics validation evidence.
- Freeze chronological Train / sequential Validation / untouched Final OOS ranges.
- Create the immutable experiment artifact on the exact clean candidate code SHA.
- Run the final OOS once; preserve the immutable result artifact, SHA-256 and completed one-shot consumption receipt.
- Compare cost-adjusted Candidate v1 against all canonical benchmarks on identical assumptions.
- Use the actual result only: `ACCEPT_FOR_LONGER_PAPER`, `REJECT_HYPOTHESIS`, or `INSUFFICIENT_SAMPLE`.

## CURRENT PROFITABILITY VERDICT

`INSUFFICIENT EVIDENCE`

Reason: source-controlled research machinery is not a substitute for a real final-OOS-eligible dataset and an executed immutable holdout experiment.
