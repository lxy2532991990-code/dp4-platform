# DP4 Platform

Standalone ORCA/Gaussian DP4-style workflow for candidate isomer ranking from NMR shielding calculations.

## Scope

- Independent project inside the current workspace
- No imports from `ecd_platform`
- ORCA and Gaussian output parsing for energy, vibrational frequencies, and NMR shieldings
- Manual experimental assignment CSV
- Candidate-isomer ranking with per-nucleus and combined probabilities
- CLI and minimal PyQt GUI

## Experimental CSV

Required columns:

- `candidate_atom_id`
- `nucleus`
- `exp_shift_ppm`

Optional columns:

- `label`
- `exchange_group` — tag two rows with the same label (e.g. `a`, `b`) to mark a
  diastereotopic pair (CH2 protons, isopropyl methyls, ...). The scorer
  re-pairs the calculated values within each group against the experimental
  shift order before computing errors. Each non-empty label must appear on
  exactly two rows of the same nucleus.

Example:

```csv
candidate_atom_id,nucleus,exp_shift_ppm,label,exchange_group
1,13C,11.2,C-1,
2,1H,2.45,H-2a,a
3,1H,2.10,H-2b,a
```

## Candidate Layout

```text
candidates/
  isomer_A/
    conf-1.out
    conf-2.out
  isomer_B/
    conf-1.out
    conf-2.out
```

## Examples

Example data is available in the `examples/` directory. To run DP4 analysis on the first test case:

```bash
cd examples/test1
dp4-platform --candidates-root . --exp-nmr-file experimental_assignments.csv
```

Results will be saved to `dp4_results/` directory.
