# SharipovAI five-stage control plane

This document is the implementation contract for the five requested stages.

## 1. PC Agent

Single local supervisor, process recovery, backup freshness checks, update rollback,
status file, logs and one autostart entry.

## 2. Dashboard 2.0

`/api/control-plane/status` exposes node, disk, backup, agent, components and safe
control status. The UI will consume this stable API rather than reading files directly.

## 3. Supervisor

Failures are isolated per component. Repeated failures must move a component into a
cooldown/disabled state while the rest of SharipovAI continues. Arbitrary shell
execution is never part of the supervisor.

## 4. AI Manager

A canonical registry records every active AI/module, its role, category, enabled
state and overlap candidates. Policy: extend existing modules before adding a new
duplicate.

## 5. Safe PC control

Dashboard commands are written to a local queue and are executed only through a
fixed allow-list. No raw command text, arbitrary PowerShell or real-trading enable
command is accepted. Updates require a separately verified artifact.

## Current implementation

- unified `ControlPlane` status snapshot;
- canonical AI registry and overlap report;
- Dashboard status/registry/command endpoints;
- allow-listed command queue and Windows worker;
- tests proving arbitrary shell and real trading remain disabled.

## Next increments

- consume queued commands from the long-running PC Agent;
- add restart budgets, cooldown and quarantine states;
- build Dashboard 2.0 visual cards and event timeline;
- add signed release manifest and verified update promotion;
- install the final tested Agent package on the target Windows PC.
