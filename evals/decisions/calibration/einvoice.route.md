# Calibration: einvoice.route

Model `gemma-4-26b-a4b-it`, prompt `b265c2d1ee5c`, 30 labelled cases, fitted temperature **T = 1.0** (2026-11-24).

| | accuracy | ECE | Brier |
|---|---|---|---|
| raw (T = 1) | 1.000 | 0.000 | 0.000 |
| calibrated, 5-fold cross-validated | 1.000 | 0.000 | 0.000 |

Risk-coverage (calibrated): the share of cases at or above each threshold and their accuracy.

| threshold | coverage | accuracy | n |
|---|---|---|---|
| 0.5 | 1.00 | 1.000 | 30 |
| 0.6 | 1.00 | 1.000 | 30 |
| 0.7 | 1.00 | 1.000 | 30 |
| 0.8 | 1.00 | 1.000 | 30 |
| 0.85 | 1.00 | 1.000 | 30 |
| 0.9 | 1.00 | 1.000 | 30 |
| 0.95 | 1.00 | 1.000 | 30 |
| 0.99 | 1.00 | 1.000 | 30 |

Cases labelled *unclear* (graded by action, not label): 6.

![Reliability diagram](einvoice.route.svg)
