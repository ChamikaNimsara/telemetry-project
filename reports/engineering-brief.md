# Engineer's Brief — 2024 Abu Dhabi Qualifying

**Objective:** Compare the fastest accurate qualifying laps of
Lando Norris (NOR) and
Oscar Piastri (PIA) using
distance-aligned FastF1 telemetry.

**Headline:** Lando Norris recorded
**82.595 s**,
**0.209 s** faster than Oscar Piastri
(82.804 s).

**Primary gain:** T6 contributed
**+0.293 s** to the reference delta,
associated with 15 m later brake application and 2.6 km/h lower minimum speed for Lando Norris.

**Primary loss:** T7 contributed
**-0.137 s** to the reference delta,
associated with 15 m later brake application and 16.0 km/h lower minimum speed for Lando Norris.

**Linked-complex caution:** T6 and T7 are only 60.6 m apart and share a window
boundary. Review them together; their combined contribution is
**+0.156 s** to Norris, not the isolated T6 value alone.

**Evidence:** [lap-delta trace](figures/08-qualifying-lap-delta.png),
[telemetry traces](figures/09-qualifying-telemetry-comparison.png), and
[corner table](tables/qualifying-corner-comparison.csv).

**Recommended investigation:** Overlay onboard and steering traces at
T6 and T7; check track position, tyre preparation,
wind/tow, and repeated-lap consistency before discussing braking approach,
balance, setup, or deployment changes.

**Decision caution:** This is an observational two-lap comparison. Public
telemetry shows associations and cannot identify setup state or causality.
