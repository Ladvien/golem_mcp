# Halt report

- written: 2026-09-06T02:49:40.375095+00:00
- class: **harness_critique**
- why: both gates passed and the examiner reported ['material_missing']: the missing check must become a numeric probe in briefs.py/acceptance.py — the loop is not allowed to invent acceptance specs
- brief: `planter_box` (iteration 62)
- prompt identity: `v11:d90e5ee9e59d`
- render directory: `_evaluate/renders/iteration62_planter_box_v11`

## Measured failures


## Examiner verdict

- examiner: `claude-code:sonnet+examiner:60a9920cb938`
- calibration: `9bcc4d728d0d`
- abstained: False
- deviations: ['material_missing']

## The one concrete next action

Turn the deviation the examiner reported into a NUMERIC probe in `briefs.py` + `acceptance.py`, then re-run. The loop may not invent acceptance specs, and tuning the prompt to satisfy an instrument bakes the instrument's blindness in.

