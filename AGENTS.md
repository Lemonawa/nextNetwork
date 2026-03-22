# Repository Guidelines

## Project Structure & Module Organization
This repository is a small Bash-based Debian tuning toolkit.

- `main.sh`: primary installer and sysctl profile using `bbr` + `fq`.
- `testing.sh`: alternate profile using `bbr` + `cake`.
- `tests/xanmod_package_selection_test.sh`: shell test script for shared helper behavior.
- `README.md`: usage, package mapping, and operator notes.

Keep shared logic aligned between `main.sh` and `testing.sh`. If behavior must diverge, limit it to the intended profile differences such as queue discipline.

## Build, Test, and Development Commands
There is no build step. Use Bash checks and the included test script.

- `bash -n main.sh testing.sh tests/xanmod_package_selection_test.sh`: syntax check all scripts.
- `bash tests/xanmod_package_selection_test.sh`: run the repository’s shell-based regression test.
- `sudo bash main.sh`: run the default installer locally on a Debian host.
- `sudo bash testing.sh`: run the testing profile locally on a Debian host.

Run tests before every commit that changes package selection, repo setup, or sysctl output.

## Coding Style & Naming Conventions
Use Bash with `#!/bin/bash` and keep `set -euo pipefail` enabled. Follow the existing style:

- 4-space indentation inside functions and conditionals.
- Function names in `snake_case` such as `select_xanmod_package`.
- Prefer small helpers over duplicating install logic.
- Use uppercase placeholders only for template markers like `__XANMOD_CODENAME__`.

If available, run `shellcheck` in addition to `bash -n`.

## Testing Guidelines
Tests are plain Bash scripts and should live under `tests/` with names ending in `_test.sh`. Favor focused assertions around stable helpers and generated config content. When fixing a bug, add or extend a test first so the regression is captured in both `main.sh` and `testing.sh`.

## Commit & Pull Request Guidelines
Recent history favors short, imperative subjects, sometimes with prefixes such as `fix:` or `optimize:`. Examples:

- `fix: handle XanMod psABI probe exit codes`
- `optimize relay tuning defaults`

Pull requests should include a short summary, the affected script (`main.sh`, `testing.sh`, or both), and the exact verification commands you ran. For behavior changes, mention expected Debian version assumptions and any reboot or kernel-install side effects.
