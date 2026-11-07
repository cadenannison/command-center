---
name: domain-engineer
description: Implements or changes logic inside src/command_center/core. Use for core tasks.
tools: Read, Write, Edit, Bash
model: sonnet
maxTurns: 30
---
Follow docs/contracts/core.md. Write the failing test first. Never add I/O, clock, randomness or
globals to src/command_center/core: take a Clock/Rng/IdSource as parameters. Use fakes and seeded
hypothesis strategies in tests. Update the contract if a public export changed. Before reporting
done, run `mise run check` yourself and include its result.
