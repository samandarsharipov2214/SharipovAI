# Post-merge stabilization notes

This branch selectively ports only low-risk, still-useful changes from the superseded deep-audit branch onto the current `main`.

Current batch:

- add `count_json_items()` so count-only reads do not materialize every JSON payload;
- expose the counter through the canonical storage package;
- add a read-only `canonical_surface_state` projection for Web/Telegram/mobile presentation layers;
- add regression coverage for both behaviors.

This batch intentionally does **not** restore the old PR wholesale. Authentication, dashboard middleware, trading, risk, portfolio, and execution paths are left unchanged until each unique change is independently reviewed against current `main`.
