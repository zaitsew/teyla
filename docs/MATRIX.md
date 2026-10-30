# The capture matrix

`teyla ux shots`, `teyla ux diff` and `teyla ux accept` catch UI drift with a fixed matrix instead of a
model's glance (`docs/STUDIO.md`, decisions S6 and S11). The product's own screenshot tour captures a list
of screens in light, dark and the largest accessibility text size, in every shipped language. Teyla runs
the tour three times, checks the accessibility tree, and compares the result with an accepted baseline.

Only iOS (XCUITest on a simulator) is wired. Web uses Playwright `toHaveScreenshot`; Compose follows later.

## Quick start

1. Copy `templates/design/ScreenshotTour.swift` into the product's UI-test target and add a scheme for it.
2. Put the scheme in `teyla.toml` (`[ux.tour]`, below) and write `design/tour.yaml` (below).
3. Make the app honor the five launch arguments and the `tour-ready` identifier (the app contract, below).
4. `teyla ux shots <repo> --check-manifest`, then `teyla ux shots <repo>`, then `teyla ux diff <repo>`.
5. Review the side-by-sides in `design/shots/diff/`. The owner runs `teyla ux accept <repo> --yes`.

## The manifest: `design/tour.yaml`

```yaml
version: 1
fixed_date: 2026-01-15T09:41:00Z    # the clock the app must use
seed: 7                             # seeds the app's fixture data
network_stub: true                  # the app answers from fixtures, never from the network
languages: [en, es]                 # every shipped language, lowercase codes
looks: [light, dark, large]         # light, dark, large (largest accessibility text size)
runs: 3                             # runs of the tour; screens that differ between runs are unstable
device: {name: Example Phone, width_pt: 393, height_pt: 852}   # masks are in points of this screen
masks:                              # named rectangles in points: clocks, maps, anything that moves
  clock: {x: 0, y: 0, w: 393, h: 54}
  map: {x: 0, y: 300, w: 393, h: 260}
defaults:
  threshold: 0.1                    # percent of pixels allowed to differ
  tolerance: 8                      # per-channel difference (0-255) below which a pixel is the same
routes:
  - id: today                       # lowercase letters, digits, dashes
    path: /today                    # handed to the app as -tour-route
    masks: [clock]
    states:
      - loaded
      - empty
      - name: error
        threshold: 1                # this screen may differ by 1 percent
  - id: places
    path: /places
    masks: [clock, map]
    threshold: 0.3                  # a route threshold applies to its states
    states: [loaded, listening]
```

Every key above is the whole schema. An unknown key is an error, so a typo does not pass silently.

| key | meaning |
|---|---|
| `version` | `1`. |
| `fixed_date` | Required. ISO 8601. The app shows this date and time wherever it would show now. |
| `seed` | Required. Integer. The app seeds its fixture data with it. |
| `network_stub` | `true` (default) or `false`. Passed as `-tour-stub-network`. |
| `languages` | Default `[en]`. Lowercase codes such as `es` or `pt-br`. |
| `looks` | Default all three. `light` and `dark` use the default text size. `large` is light with `UICTContentSizeCategoryAccessibilityXXXL`. |
| `runs` | 1 to 5, default 3. `--runs` overrides it for one invocation. |
| `device` | Required. `width_pt` and `height_pt` of the simulator screen; `name` is the simulator to use when `teyla.toml` names none. Masks are scaled from points by the screenshot's width. |
| `masks` | Name to `{x, y, w, h}` in points. Both images get the same rectangles blacked out before the comparison. |
| `defaults` | `threshold` (percent, default 0.1) and `tolerance` (default 8). |
| `routes[].id`, `path` | The route's name and the path the app opens. |
| `routes[].states` | Each one of `empty`, `loaded`, `error`, `listening`, as a name or `{name, threshold, masks}`. |
| `routes[].threshold`, `masks` | Defaults for the route's states. A state's own `masks` are added to the route's. |

A screen is `<route>.<state>`. A capture is a screen in a variant, and a variant is `<language>-<look>`
(`es-dark`). The file is `design/shots/<variant>/<screen>.png`. `teyla ux shots <repo> --check-manifest`
validates the file, prints the screen and capture counts, and stops. The manifest is YAML; Teyla reads the
subset above (maps, lists, inline lists and maps, quoted strings, numbers, booleans, comments) and JSON.

Keep the first matrix small: three flows, not every screen. A capture costs about as much as an app launch,
and the budget is nine minutes for all runs.

## The product's settings: `teyla.toml`

```toml
[ux.tour]
project = "Example.xcodeproj"   # or: workspace = "Example.xcworkspace"
scheme = "ExampleTour"          # the scheme that runs ScreenshotTour
device = "Example Phone"        # the simulator's name; falls back to device.name in the manifest
only_testing = "ExampleUITests/ScreenshotTour"   # optional -only-testing filter
```

## What `teyla ux shots <repo>` does

1. Asks the machine guard: `teyla load --admit build --cwd <repo>`. A refusal ends the command with exit 2 and
   the guard's own text. Then it waits for a simulator slot with `teyla load --wait --kind sim`, because the
   guard holds the next job back for a few minutes after it lets one in.
2. Starts the clock. The budget (default 9 minutes, `--budget-min`) covers everything from here to the end of the
   last export. An export gets only the time that is left.
3. Reuses a booted simulator with the configured name, or boots exactly one, and sets a fixed status bar.
4. Builds once, into `~/.teyla/shots/<repo>/derived`:

   ```
   xcodebuild build-for-testing -project Example.xcodeproj -scheme ExampleTour \
       -destination 'platform=iOS Simulator,id=<udid>' -derivedDataPath <derived> -quiet
   ```
5. Runs the tour `runs` times with the plan in `TEST_RUNNER_TEYLA_TOUR_PLAN` (the tour sees `TEYLA_TOUR_PLAN`):

   ```
   xcodebuild test-without-building -project Example.xcodeproj -scheme ExampleTour \
       -destination 'platform=iOS Simulator,id=<udid>' -derivedDataPath <derived> \
       -resultBundlePath <tmp>/run-N.xcresult -parallel-testing-enabled NO -quiet
   xcrun xcresulttool export attachments --path <tmp>/run-N.xcresult --output-path <tmp>/attachments-N
   ```

   Exporting attachments needs Xcode 16 or later. `--dry` prints every command and runs none of them.
6. Shuts down the simulator it booted, whatever happened: a failed build, a failed boot, an exception, the budget.
   A simulator that was already booted is left booted.
7. Writes `design/shots/<variant>/<screen>.png` from the first run and `design/shots/run.json`. Variant folders of
   an earlier run are replaced. `baseline/` and `diff/` are never touched by `shots`.
8. Removes its temporary files (below), also when the run failed.

**Temporary files.** The `.xcresult` bundles and the exported attachments of a run live in one directory made by
`mkdtemp`: `teyla-shots-<random>/` inside the system temporary directory (`$TMPDIR`, on a Mac under
`/var/folders/...`), as `run-N.xcresult` and `attachments-N/`. The screenshots are copied into
`design/shots/` first, then the directory is deleted. `--keep-temp` keeps it for debugging; the command then prints its
path, and deleting it is up to you. The build cache, `~/.teyla/shots/<repo>/derived`, is not temporary and stays,
so the next build is incremental.

A run is `complete` only when nothing went wrong:

- no error (an `xcodebuild test` exit code other than 0, a failed export, a failed build step);
- not cut by the budget;
- every screen of the manifest, in every variant, captured in **every** run.

Otherwise the status is `incomplete` (an error, or a screen missing from any run), `budget` (cut) or `failed` (no
usable screenshots). The screenshots of an `incomplete` or `budget` run are still written so you can look at them,
but `accept` refuses the run. If the budget ends the run, the tour process group is killed, the run is reported as
`budget` ("CUT"), and only the runs that finished count; an export that ends after the budget cuts the run too. If no
run produced a screenshot, nothing in `design/shots/` changes.

Exit status: 0 the run completed (layout findings print; with `--strict` they also fail); 1 a screen was
unstable, a screen was not captured in every run, the budget cut the run or the tour reported an error; 2 the
manifest or `teyla.toml` is invalid, or the machine guard refused; 3 the build or the simulator could not start.

### What is checked

- **Stability.** A screen's pixels are hashed in each run. If two runs of one build differ, the screen is
  `unstable`. This is the "works unstably" a person sees and an agent does not.
- **Accessibility audit.** The tour calls `performAccessibilityAudit` on every screen and exports every issue.
- **Element frames.** The tour exports the accessibility tree as points. Teyla reports, per screen, elements that
  `overlap` (partly cover each other; containment is fine), `off-screen` (outside the screen; scroll content
  is exempt), `truncated` (the tour flags a label that ends in an ellipsis) and `small-target` (an interactive
  element under 44 x 44 pt). These are heuristics that read frames. A hit is a pointer to look, not proof,
  and a miss is not proof of a good screen.

### `design/shots/run.json`

```json
{"version": 1, "status": "complete", "started": "...", "finished": "...", "duration_s": 212.4, "budget_s": 540,
 "runs_requested": 3, "runs_completed": 3, "device": "Example Phone", "commit": "abc123def456",
 "manifest_sha256": "...", "variants": ["en-light", "..."],
 "screens": {"en-light/today.loaded": {
     "variant": "en-light", "screen": "today.loaded", "route": "today", "state": "loaded",
     "hashes": ["px:...", "px:...", "px:..."], "captured": 3, "stable": true,
     "audit": {"ran": true, "issue_count": 0, "issues": [], "error": null},
     "findings": [{"kind": "small-target", "elements": ["button 'Close'"], "detail": "30 x 30 pt, under 44 x 44"}]}},
 "unstable": [], "uncaptured": [],
 "counts": {"screens": 30, "unstable": 0, "uncaptured": 0, "findings": 1, "audit_issues": 0},
 "errors": []}
```

`status` is `complete`, `incomplete`, `budget` or `failed`. `stable` is `true`, `false`, or `null` when fewer than
two runs captured the screen. `captured` counts the runs that have the screen; below `runs_completed` the screen is in
`uncaptured` and `missing_runs` says how many runs lacked it. Hashes are of pixels when Pillow is installed (`px:`), of the file otherwise (`file:`).

## `teyla ux diff <repo>`

Compares every `design/shots/<variant>/<screen>.png` with `design/shots/baseline/<variant>/<screen>.png`. It needs
Pillow (`uv tool install --force --python 3.12 --with pillow git+https://github.com/zaitsew/teyla`); without it,
it prints that one line and exits 2.

- A pixel counts as changed when any channel differs by more than `tolerance`. A screen is **changed** when the
  share of changed pixels, after the masks are blacked out of both images, is above its threshold. A different
  image size is a change.
- It walks the manifest's screens times its variants, plus any other PNG in either folder. **new**: in the run, not
  in the baseline. **missing**: not in the run: in the baseline only, or in neither (a screen the manifest lists
  that was never captured; a cut run causes this too). **unstable**: listed in `run.json`.
- For each changed screen it writes `design/shots/diff/<variant>/<screen>.png`: baseline, current, and the changed
  pixels in red. The folder is rebuilt on every diff.
- Exit 1 when anything is changed, new, missing or unstable; 0 otherwise.

It ends with the line for the PR body. A clean diff reads "no diff on the manifest's screens (N screens x M variants)",
printed only when every one of those captures was compared. Zero screenshots is exit 1, never a clean diff.
It never says "no drift": a screen the manifest does not list was not checked.

## `teyla ux accept <repo> --yes`

Replaces `design/shots/baseline/` with the run and writes `baseline/ACCEPTED.json`:

```json
{"accepted_by": "Name from git config", "accepted_at": "2026-01-15T10:02:11Z", "run_started": "...",
 "run_commit": "...", "manifest_sha256": "...", "variants": ["en-dark", "en-light"], "screens": 30,
 "unstable_accepted": []}
```

Without `--yes` it changes nothing and exits 2. It refuses a run that is not `complete`, a run whose `run.json` lists
an error or an uncaptured screen, and a run with fewer completed runs than requested. No flag overrides these.
A run with unstable screens is refused unless `--allow-unstable` is given (they are then recorded in
`unstable_accepted`); that flag covers unstable screens only. The owner runs it:
an agent never accepts its own baseline. Commit the baseline with the change that caused it.

Suggested `.gitignore` lines for a product: `design/shots/*` and `!design/shots/baseline/`.

## The app contract

The tour launches the app once per screen. The app reads these launch arguments (see them with
`ProcessInfo.processInfo.arguments`):

| argument | meaning |
|---|---|
| `-tour-route <path>` | Open this route, e.g. `/today`. |
| `-tour-state <state>` | Show `empty`, `loaded`, `error` or `listening` data for it. |
| `-tour-date <iso8601>` | Use this instant wherever the app shows the current date or time. |
| `-tour-seed <n>` | Seed all fixture data and any randomness. |
| `-tour-stub-network <0\|1>` | `1`: answer every request from fixtures. |

The app also turns animations off in tour mode and sets the accessibility identifier `tour-ready` on a visible
element once the route and state are on screen. The tour waits for it. Language, appearance and text size come
from the standard system launch arguments (`-AppleLanguages`, `-AppleInterfaceStyle`,
`-UIPreferredContentSizeCategoryName`); the app needs no code for them.

## Limits

- The simulator path of this tooling has run only against fakes. Its first real run is the test of the xcresult
  export format and of the template, which Teyla's own checks do not compile.
- One device size. A second device class is a second manifest, not a flag.
- The audit and the frame checks see the accessibility tree, not the pixels. A drawn label with no accessibility
  element is invisible to them; the pixel diff still sees it.
- Teyla never builds or boots anything the machine guard refuses. On a busy Mac the command exits 2 and says how to wait.
