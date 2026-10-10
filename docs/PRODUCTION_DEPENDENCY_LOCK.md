# Production Dependency Reproducibility

TrendForge keeps two dependency contracts.

- `requirements.txt` defines supported compatibility ranges and is exercised
  by the Python 3.11/3.12 test matrix.
- `requirements-production.lock` is the exact dependency graph installed by
  Render on the Python 3.12 production runtime.

## Why this split exists

Broad ranges are useful in CI because they expose compatibility problems when
upstream packages move. They are not suitable for production deployment
because the same Git commit can otherwise resolve to different package
versions on different deploys.

The production lock was captured from a clean Python 3.12.15 Ubuntu runner
after installing `requirements.txt` and passing `pip check`. All runtime
packages, including transitive dependencies, are pinned with exact versions.

## CI contract

The normal test matrix still installs `requirements.txt` on Python 3.11 and
3.12 and runs the full test suite.

A separate `production-dependency-audit` job installs
`requirements-production.lock` on Python 3.12, runs `pip check`, verifies
every installed locked distribution has the expected version, and uploads the
resolved freeze as an audit artifact.

## Render contract

`render.yaml` installs `requirements-production.lock`. Production therefore
does not resolve broad dependency ranges during deployment.

`GET /production/health` reports a `dependencies` block containing:

- `status`: `runtime_verified` only when every locked package is installed
  at the exact locked version;
- `locked_packages`: number of exact packages in the lock;
- `file_sha256`: SHA-256 of the deployed lock file;
- `missing`: locked distributions not installed;
- `mismatched`: distributions whose installed version differs from the lock.

## Refresh procedure

Dependency refreshes are deliberate release work. Regenerate the candidate
graph from `requirements.txt` on Python 3.12, run `pip check`, run the full
test matrix, inspect important direct/transitive version changes, replace the
production lock, and deploy only after CI is green.

Do not edit individual transitive versions merely to force CI green. If the
resolver produces an incompatible graph, adjust the supported direct
dependency ranges with an explicit reason and tests.
