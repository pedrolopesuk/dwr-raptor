# Carbon Design System adoption

The DRW researcher UI is built on the **official IBM Carbon Design System React
library**. This records the packages, integration, conventions and the small
number of justified exceptions.

## Packages

| Package | Version | Role |
| --- | --- | --- |
| `@carbon/react` | 1.117.0 | Components, UI Shell, themes; its `index.scss` forwards `@carbon/styles` |
| `@carbon/styles` | 1.116.0 | Design tokens, grid, typography, reset (transitive via `@carbon/react`) |
| `@carbon/icons-react` | 11.89.0 | Icons (`Moon`, `Sun`, `Add`, `TrashCan`) |
| `sass` | 1.105.1 | Dart Sass compiler (devDependency; Next.js compiles `globals.scss`) |
| `@axe-core/playwright` | 4.13.0 | Automated accessibility checks in the browser suite (devDependency) |

Compatibility was checked against the project's actual stack before choosing:
React 19.3 + Next 15.5 are supported by Carbon 1.117. No duplicate style system
remains - the previous hand-written `globals.css` was removed.

## Style integration

* One global stylesheet: `src/app/globals.scss`
  ```scss
  @use "@carbon/react";
  @use "@carbon/react/scss/spacing" as spacing;
  ```
  Carbon's full component CSS is emitted once; only layout helpers (`drw-*`) are
  added on top, and they use Carbon tokens.
* `next.config.mjs` adds `sassOptions.includePaths = [<cwd>/node_modules]` so
  `@use "@carbon/react"` resolves under pnpm's symlinked layout.
* pnpm blocks dependency build scripts by default. `pnpm-workspace.yaml`
  explicitly sets `allowBuilds: false` for the Carbon/IBM font packages (they ship
  prebuilt CSS/fonts) and `true` only for `esbuild`. Installs exit 0.

## Theme

* The app is wrapped in Carbon's `<Theme>`; the choice is **`g10` (light) by
  default**, with a header action toggling to **`g100` (dark)**.
* The choice persists in `localStorage` under `drw-theme` and is restored after
  mount (avoids a hydration mismatch).
* Both themes were checked with axe-core: no serious/critical violations.

## Component conventions

| Area | Carbon component(s) |
| --- | --- |
| Application shell | `Header`, `HeaderName`, `HeaderGlobalBar`, `HeaderGlobalAction`; Carbon skip link (`cds--skip-to-content`) to `#main-content` |
| Buttons | `Button` (primary / tertiary / ghost / danger) with Carbon icon `renderIcon`; icon-only buttons use `hasIconOnly` + `iconDescription` |
| Inputs | `TextInput`, `TextArea`, `Select` + `SelectItem`, `FormGroup` for field sets |
| Status | `Tag` (with `--cds-text-*` error text), `InlineLoading`, `ProgressBar` |
| Feedback | `InlineNotification` (error / warning / info) for diagnostics |
| Data | `Table`/`TableContainer`/`TableHead`/`TableRow`/`TableHeader`/`TableBody`/`TableCell` for parameters, outputs, runs, comparisons, metrics, sensitivity, environment, evidence |
| Results | `Tabs`/`TabList`/`Tab`/`TabPanels`/`TabPanel` |
| Lists | `UnorderedList`/`ListItem` |

## Tokens

Layout helpers and the few custom surfaces use Carbon **CSS custom properties**
rather than hex values:

* text: `--cds-text-primary`, `--cds-text-secondary`, `--cds-text-error`
* surfaces/borders: `--cds-layer-01`, `--cds-layer-02`, `--cds-border-subtle-01`
* status/chart: `--cds-support-info` (reference series), `--cds-support-success`
  (variant series), `--cds-text-primary` (delta series, dashed)
* typography: Carbon type styles inherited from `@carbon/react`; monospace via
  `--cds-font-family-mono`
* spacing: Carbon's `spacing` Sass module (`spacing.$spacing-*`) in `globals.scss`

No hard-coded hex values were introduced in the migrated components.

## Accessibility expectations

* Semantic sections with `aria-labelledby`; skip link to the main region.
* Every control has a visible Carbon label; inputs carry helper text.
* Live status via `aria-live="polite"`; the run `ProgressBar` is determinate and
  labelled "k of n runs completed".
* Charts are `role="img"` with a descriptive `aria-label`; series are
  distinguished by **colour and dash pattern**, never colour alone.
* Automated axe checks (light + dark, start + loaded screens) assert **no
  serious/critical violations**; a keyboard test covers the skip link, sample
  action, project select, baseline field and Run/Validate buttons.
* Verified: resolved contrast/borders/focus come from Carbon tokens in both themes.

## Justified exceptions (custom components)

1. **`LineChart`** (`src/components/LineChart.tsx`) - a dependency-free SVG plot.
   Carbon has no charting component; the data is already aligned by Python. It is
   token-styled, keyboard-inert (informational) and labelled.
2. **`<pre>` spec/evidence previews** - Carbon's `CodeSnippet` renders a scrollable
   `<pre>` that is **not keyboard focusable**, which axe flags as *serious*
   (`scrollable-region-focusable`). The previews are therefore plain `<pre>`
   elements with `tabIndex={0}` so they can be scrolled by keyboard.

## Not used

`CodeSnippet` (see exception 2), `DataTable` (its render-prop API adds no value
over the `Table` primitives here), Modal/OverflowMenu/Breadcrumb (no such flow in
a single-page workspace).
