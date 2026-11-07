# Offline input snapshot

`catalog.json` and `variants.json` are the fixed inputs to this experiment.
`client/` contains the public Mafia Reborn client fragments retained to review
item compatibility, effects, weapon generation, and combat formulas. The client
snapshot was supplied with the project and is dated 2026-11-07. These fragments
are reference material, not a complete independently runnable game client.

Source game: [Mafia Reborn](https://mafiareborn.com/).

`class_reference.json` retains the supplied normalized class coefficients. A
reconstruction from the bundled client matches all displayed columns at level
50 with nominal Epic1 weapons and Epic Vigilance on every class. The original
historical execution log is unavailable; this is a reproducible matching model.
The theory check also evaluates level 200 and the no-Vigilance alternatives,
and writes `results/class_mechanics.json`. The CUDA inventory search itself
evaluates level-200 Rogue-versus-Rogue inventories only.

The full reproduction command is offline and does not refresh game data.
`results/run_manifest.json` records SHA-256 hashes of all inputs used by a run.
