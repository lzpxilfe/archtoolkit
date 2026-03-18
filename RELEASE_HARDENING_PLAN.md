# ArchToolkit Release Hardening Plan

Date: 2026-03-06
Status: Active; Steps 1-2 completed, Step 3 in progress

## Goal

Publish `ArchToolkit` to the QGIS Plugin Repository with a stable, reviewable, and maintainable codebase.

This plan is intentionally incremental. We will not do a big-bang rewrite. Each step must keep the plugin runnable and leave a clear verification trail.

## External References To Fold In

- QGIS Plugin Repository publishing guidance:
  - minimal documentation
  - valid `homepage`, `repository`, `tracker`, `license` metadata
  - short English description
  - no binaries
  - package size under 25 MB
  - cross-platform behavior expected
  - package ZIP should match the public repository source
  - avoid hidden/generated files in the upload package
- QGIS Plugin Repository approval guidance:
  - metadata quality is checked
  - plugins may be randomly tested for install/run/crash behavior
- QGIS Plugin Repository security scanning:
  - uploaded ZIPs are scanned with `Bandit`, `detect-secrets`, and `Flake8`
- Reference plugin:
  - [KIGAM-for-Archaeology](https://github.com/lzpxilfe/KIGAM-for-Archaeology)
  - useful patterns to reuse:
    - `plugin_config.json` for hardcoded defaults
    - `create_package.py` for clean ZIP packaging
    - tighter `metadata.txt`

## Current Snapshot

- Repository raw size is about 13.7 MB, so package size is currently below the QGIS 25 MB limit.
- `metadata.txt` baseline cleanup is done:
  - repository/tracker/homepage links normalized
  - concise English description/about text added for plugin-repository review
  - plugin currently marked `experimental=true` until hardening is further along
- Large modules are carrying both UI logic and heavy processing logic:
  - `tools/viewshed_dialog.py`
  - `tools/cost_surface_dialog.py`
  - `tools/terrain_profile_dialog.py`
  - `tools/cost_network_dialog.py`
  - `tools/spatial_network_dialog.py`
- No automated regression test harness exists yet.
- A dedicated packaging script now exists: `create_package.py`
- Several runtime risks already identified in review:
  - KIGAM ZIP extraction path reuse can invalidate already loaded layers
  - AI AOI summary cache can reuse stale project state
  - task completion callbacks can outlive closed dialogs
  - coordinate tolerance handling in viewshed polygon picking is fragile across CRS changes
- Product improvements already requested:
  - AI AOI report should stop defaulting to old Gemini 1.5 models and support official current-model refresh or validation
  - AHP workflow needs a guided, more explanatory UX instead of exposing raw pairwise-comparison concepts too early

## Release Gates

These are the minimum conditions before upload:

- `metadata.txt` is clean, readable, and accurate.
- packaging produces a clean ZIP without `.git`, `.ruff_cache`, `__pycache__`, `.vscode`, or local-only files.
- no obvious hardcoded secrets, personal paths, or publish-only mismatches.
- `python -m compileall -q .` passes.
- `ruff check .` passes or remaining ignores are explicitly justified.
- `bandit -r .` and `detect-secrets scan` are reviewed before release.
- core dialogs open/close without crashing QGIS.
- critical workflows have smoke coverage:
  - DEM
  - contour
  - viewshed / LOS
  - cost surface / LCP
  - least-cost network
  - spatial network
  - terrain profile
  - KIGAM ZIP
  - GeoChem
  - AI AOI report
- plugin behavior is documented enough that a reviewer can understand how to use it.

## Strategy

We will work in this order:

1. Release baseline first.
2. Centralize hardcoded configuration.
3. Stabilize KIGAM and shared file/config patterns.
4. Fix correctness and lifecycle bugs found in review.
5. Break large modules into service-oriented units without changing behavior.
6. Add repeatable smoke checks and release packaging.
7. Do final metadata/docs/release cleanup.

## Workstreams

### 1. Release Baseline

Scope:

- clean up `metadata.txt`
- normalize repository links, versioning, category/type, changelog wording
- add a packaging script modeled after `KIGAM-for-Archaeology/create_package.py`
- define a package exclusion list
- make release output deterministic

Target files:

- `metadata.txt`
- new packaging script, likely `create_package.py`
- `.gitignore`
- possibly `README.md`

Definition of done:

- metadata links are valid and public
- generated ZIP excludes caches and local-only directories
- package contents are reviewable and consistent with repository contents

Status:

- completed on 2026-03-06

### 2. Shared Configuration Extraction

Scope:

- introduce a central config file, likely `tools/plugin_config.json`
- move UI defaults, encoding candidates, field candidates, raster defaults, and reusable numeric limits out of code
- add a small config loader helper with safe fallback behavior

Target files:

- new `tools/plugin_config.json`
- new helper such as `tools/config.py`
- selected dialog modules consuming config values

Definition of done:

- no user-facing defaults are scattered across many files without reason
- config load failures degrade safely
- future tuning can be done without editing processing logic

Status:

- completed on 2026-03-06

### 3. KIGAM / Geology Refactor

Scope:

- refactor `tools/geology_zip_dialog.py` first, using the reference plugin as the main structural guide
- isolate ZIP processing, styling, labeling, rasterization, and layer organization
- replace shared extraction directory naming with unique run-scoped or content-scoped paths
- centralize encoding and field heuristics in config

Target files:

- `tools/geology_zip_dialog.py`
- shared config files/helpers
- optional split into:
  - `tools/geology_zip_processor.py`
  - `tools/geology_zip_style.py`
  - `tools/geology_rasterize.py`

Definition of done:

- repeated ZIP loads do not invalidate previously loaded layers
- styling/rasterization behavior is configurable
- KIGAM logic is readable without scanning one large dialog file

### 4. Correctness Fixes From Review

Scope:

- fix AI AOI stale cache behavior
- fix explicit layer selection truncation behavior in AI summaries
- modernize Gemini model handling for AI AOI reporting
  - remove old default model assumptions
  - add a safe way to refresh or validate supported model names from official Gemini endpoints or docs
- harden viewshed polygon picking across CRS differences
- harden task cancellation and dialog lifecycle for long-running tools

Target files:

- `tools/ai_report_dialog.py`
- `tools/ai_aoi_summary.py`
- `tools/viewshed_dialog.py`
- `tools/cost_surface_dialog.py`
- `tools/cost_network_dialog.py`
- possibly `arch_toolkit.py`

Definition of done:

- repeated runs reflect current project state
- closed dialogs do not receive unsafe late callbacks
- coordinate-based picking works consistently in mixed-CRS projects

### 5. Large-Module Decomposition

Scope:

- split UI orchestration from computational services
- reduce risk by moving pure logic first, not by rewriting everything at once

Priority order:

1. `tools/viewshed_dialog.py`
2. `tools/cost_surface_dialog.py`
3. `tools/terrain_profile_dialog.py`
4. `tools/cost_network_dialog.py`
5. `tools/spatial_network_dialog.py`

Proposed extraction pattern:

- dialog/UI file
- service/algorithm file
- layer-output/styling file
- validation/input helpers

Definition of done:

- each major tool has a smaller dialog controller
- pure calculations can be tested without opening QGIS dialogs
- side effects are isolated

### 6. Logging, Errors, and Runtime Safety

Scope:

- standardize user-facing error messages
- remove silent broad exceptions where they hide state corruption
- keep best-effort logging, but surface failures that affect outputs
- unify temp file tracking and cleanup conventions

Target files:

- `tools/utils.py`
- task-based tools
- file-producing workflows

Definition of done:

- failures are diagnosable
- temp outputs are either cleaned or intentionally persisted
- user sees actionable messages when a run fails

### 7. Smoke Tests and Release Checks

Scope:

- add a lightweight smoke framework and test data strategy
- codify the existing manual checks in `SMOKE_TEST.md`
- document per-tool minimum validation steps

Possible outputs:

- `tests/` directory for pure logic tests where feasible
- `scripts/` or `tools/dev/` helpers for packaging and validation
- improved `SMOKE_TEST.md`
- release checklist document

Definition of done:

- each release candidate can be validated with the same checklist
- at least pure helper logic is exercised automatically
- manual QGIS-only checks are explicit and short

### 8. Docs and Publication Cleanup

Scope:

- rewrite metadata/about text for publication readability
- reduce encoding issues in docs
- align README, metadata, and release notes
- verify license and third-party resource provenance

Definition of done:

- docs are readable in both repository and plugin manager contexts
- reviewer can find usage, requirements, and limitations quickly

### 9. Guided UX Improvements

Scope:

- redesign AHP so non-specialist users can complete it without already understanding pairwise-comparison workflows
- add explanation-first UI patterns:
  - presets
  - guided weighting
  - consistency feedback with plain-language suggestions
  - clearer raster preparation and normalization help
- improve AI AOI report usability:
  - clearer provider and model status
  - model refresh button or supported-model picker
  - more explicit privacy guidance before remote calls

Definition of done:

- AHP can be used productively by a first-time user
- AI AOI reporting no longer feels like a hidden expert feature

## Step-By-Step Backlog

This is the execution order we should follow.

- [x] Step 1. Release baseline and package hygiene
- [ ] Step 2. Shared `plugin_config.json` scaffold
- [ ] Step 3. KIGAM ZIP processor refactor
- [ ] Step 4. Metadata and docs cleanup round 1
- [ ] Step 5. AI AOI correctness fixes
- [ ] Step 6. Task lifecycle hardening for cost/network tools
- [ ] Step 7. Viewshed CRS/picking fixes
- [ ] Step 8. AHP guided UX redesign
- [ ] Step 9. AI AOI provider/model UX refresh
- [ ] Step 10. Viewshed module split
- [ ] Step 11. Cost surface module split
- [ ] Step 12. Terrain profile module split
- [ ] Step 13. Spatial / least-cost network cleanup
- [ ] Step 14. Smoke test harness and release checklist
- [ ] Step 15. Security/local validation pass
- [ ] Step 16. Final package build and upload prep

## First Task To Start With

Start with Step 1: release baseline and package hygiene.

Reason:

- it is low-risk compared to algorithm rewrites
- it directly supports QGIS repository submission
- it gives us the packaging/config skeleton needed for later refactors
- it lets us fix obvious metadata and repository hygiene issues before deeper work

## Rules For Each Iteration

- make one bounded change at a time
- keep the plugin runnable after each step
- verify locally before moving on
- prefer extraction over rewrite
- prefer config over hardcoded literals when the value is not algorithmically essential
- do not introduce new external Python dependencies unless strictly necessary
- preserve QGIS-native APIs such as `QgsNetworkAccessManager` and QGIS widgets

## Per-Step Verification Template

For every completed step, record:

- changed files
- behavior changed
- risks
- verification commands run
- manual QGIS checks performed
- follow-up items discovered

## Notes For Future Commits

- avoid mixing refactor and behavior changes in one commit when possible
- keep packaging, metadata, and docs changes separate from algorithm changes
- when a large file is split, keep one compatibility-focused step before cleanup/styling changes
