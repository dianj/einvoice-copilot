# Calibration: einvoice.instruction_in_reply

Model `qwen3.8-27b`, prompt `ad6c9ea3370a`, 32 labelled cases, fitted temperature **T = 1.0** (2026-11-24).

| | accuracy | ECE | Brier |
|---|---|---|---|
| raw (T = 1) | 1.000 | 0.034 | 0.010 |
| calibrated, 5-fold cross-validated | 1.000 | 0.034 | 0.010 |

Risk-coverage (calibrated): the share of cases at or above each threshold and their accuracy.

| threshold | coverage | accuracy | n |
|---|---|---|---|
| 0.5 | 1.00 | 1.000 | 32 |
| 0.6 | 1.00 | 1.000 | 32 |
| 0.7 | 0.97 | 1.000 | 31 |
| 0.8 | 0.97 | 1.000 | 31 |
| 0.85 | 0.97 | 1.000 | 31 |
| 0.9 | 0.94 | 1.000 | 30 |
| 0.95 | 0.84 | 1.000 | 27 |
| 0.99 | 0.41 | 1.000 | 13 |

![Reliability diagram](einvoice.instruction_in_reply.svg)
