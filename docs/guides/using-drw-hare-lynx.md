# Using DRW: a worked example with real data

This guide explains what every page and tab in DRW is for. It uses one real project that was built and run in the app: **do the hare and lynx pelt counts from Hudson's Bay (1900–1915) look like a predator–prey cycle?**

Everything described here was done in the running app. Every number comes from an actual run. Where DRW cannot do something yet, the guide says so.

- **Project:** `Hare and lynx cycles, Hudson's Bay 1900-1915` (id `proj-d563ba12705f`)
- **Open it:** `http://localhost:3222/projects/proj-d563ba12705f`
- **Investigation:** `exp-a77c68836f86`
- **Dataset:** `ds-23bdb875201e` (source file: [data/hare_lynx_1900_1915.csv](data/hare_lynx_1900_1915.csv))
- **Where it lives:** `.drw/web-workspace/` in the repo (not committed; `.drw/` is git-ignored)

---

## 1. The five words you need

| Word | Meaning in DRW |
| --- | --- |
| **Project** | A folder-like group of work. It is the thing you pick in the header. |
| **Investigation** | One scientific *question* plus the experiment that addresses it. |
| **Experiment** | One computational execution: a model, a baseline, an intervention, run through the Python engine. |
| **Dataset** | A table of real observations, imported once, immutable, identified by a hash. |
| **Evidence** | Everything that lets someone else trace and reproduce a result: hashes, configuration, environment, files. |

**Important:** DRW does not have a separate "investigation" object in its backend. An investigation *is* a stored experiment, and its question is the experiment's hypothesis. Before you press Run, an investigation is an unsaved **draft** (URL contains `/investigations/draft/`). After Run it gets its permanent id (`exp-…`).

---

## 2. What each page and tab is for

DRW has two navigation levels. The **sidebar** is about the *project*. The **tab bar** appears only once you are *inside an investigation*.

![Project overview](img/01-project-overview.png)

### 2.1 Header (always visible)

| Control | What it does |
| --- | --- |
| **☰ menu button** | Expands or collapses the sidebar rail. |
| **Project ▾** | Switch project, search projects, or create a new one. |
| **SI / Manual** | Two views of the same app. **SI** = ask in plain language. **Manual** = direct control (see 2.4). |
| **Search** (Ctrl K) | Find investigations, models, projects. |
| **Help** | Short definitions of the vocabulary above. |
| **Theme** | Light/dark. |
| **Settings** | Shows the execution environment (Python/numpy/platform versions and a hash). There is no account or login. |

### 2.2 Sidebar (project level): "what exists?"

| Page | Job | Use it when |
| --- | --- | --- |
| **Overview** | Entry point. SI composer, recent investigations, recent activity, counts. | You just opened the project and want to start or continue. |
| **Investigations** | List of questions in this project, with model, status and date. **New investigation** starts a draft from a model. | You want to find an old question or start a new one. |
| **Data** | Import CSV files and see stored datasets. | You have observations to bring in. |
| **Models** | The registered computational models and a **Start investigation** button for each. | You want to know what you can model. |
| **Experiments** | Every stored experiment in the project (runs, isolation, spec hash). | You want the computational history, not the scientific question. |
| **Evidence** | Experiments that have stored evidence; each links to its trace. | You need to audit or reproduce something. |

Note: **Data is shared by the whole workspace**, not scoped to one project. A dataset imported in one project appears in all of them.

### 2.3 Investigation tabs: "what are we trying to establish?"

![Investigation overview](img/12-investigation-overview.png)

| Tab | The one question it answers | What is on it |
| --- | --- | --- |
| **SI** | What should I ask or do next? | Chat-style composer. SI proposes an experiment configuration. It never runs anything. |
| **Overview** | Where are we scientifically? | The question, a checklist of what is done / not done, the conclusion ("Not established"), a short evidence summary. |
| **Data** | What observations do we have? | Import and inspect datasets (same tool as the project Data page). |
| **Model** | What are we modelling? | Sub-tabs: Overview, Parameters, Inputs (initial conditions), Outputs, Execution, Versions. |
| **Experiments** | What did we run? | Three sub-pages: **Runs** (table of runs), **Configuration** (edit, validate, run), **Results** (plots, metrics, sensitivity). |
| **Analysis** | What does the computation tell us? | An index of four analyses. Each opens its own page: Sensitivity, Identifiability, Calibration, Evaluation. |
| **Validation** | Does it hold on *independent* evidence? | Currently an honest "not implemented" page. |
| **Evidence** | Can we trace and reproduce the conclusion? | Chain from question to conclusion, with hashes, configuration, environment, files, export and reproduce. |

### 2.4 SI versus Manual

- **SI** is for *asking*. You type a question; the rule-based planner proposes an experiment. At the moment SI **only proposes experiment configurations**. It cannot calibrate, import data, or run analyses by itself.
- **Manual** is for *controlling*. You see every parameter, bound, mapping, objective, optimizer, budget and seed.
- **Review in Manual** (on an SI proposal) loads the proposal into the Configuration page so you can inspect and edit it. Nothing runs until you validate and press Run yourself.

---

## 3. The worked example

### Step 0. Create the project

Header → **Project ▾** → **New project** → type a name → **Create**.

![New project](img/00-new-project.png)

### Step 1. The data

**Source.** The 16 rows are the widely reproduced Hudson's Bay Company hare and lynx pelt tallies for 1900–1915 (the classic Odum/Elton series, reported in thousands). **These values were entered from memory of the standard table, not downloaded from a primary source. Check them against the original before citing them.**

**Scaling.** The built-in `predator-prey` model has authoritative bounds (for example `beta >= 0.05`). Raw numbers in thousands would need `beta ≈ 0.03`, which is outside those bounds. So the data was divided by 10:

- 1 **count** in this project = **10,000 pelts**
- `year_index` = years since 1900. DRW's model time unit is "s", so 1 model-second is treated as 1 year.

These are modelling conventions, not facts. Pelts are not populations, and the model is an idealisation.

**Import.** The CSV was placed in the workspace folder `dataset-sources/`. Then: **Data → pick the file → Inspect**, and declare everything explicitly (DRW infers nothing scientific):

| Column | Role | Unit | Depends on |
| --- | --- | --- | --- |
| `year_index` | coordinate | `s` | — |
| `hare` | measurement | `count` | `year_index` |
| `lynx` | measurement | `count` | `year_index` |

![Inspecting the CSV](img/02-data-inspect.png)

**Validate** does a dry run (writes nothing). **Import** stores the dataset immutably.

![Imported dataset](img/04-dataset-detail.png)

The detail view shows the variables, the content hash and a read-only **Verify** check. The data is identified by its hash, so it cannot silently change.

### Step 2. Choose a model

**Models** lists three registered models: `predator-prey`, `oscillator`, `lorenz`. Models that cannot be configured are disabled with a reason. We use `predator-prey` (Lotka–Volterra):

```
hare'  = alpha·hare − beta·hare·lynx
lynx'  = delta·hare·lynx − gamma·lynx
```

![Models](img/05-models.png)

**Start investigation** creates the draft and opens its Overview. The first screen is a *demonstration* configuration (+10% on the first input). It is a starting point, not a justified experiment.

![Draft overview](img/06-draft-overview.png)

### Step 3. Configure the experiment

**Experiments → Configuration.** The question (hypothesis) was written as:

> A Lotka-Volterra predator-prey system explains the 9-10 year hare and lynx cycles in the Hudson's Bay pelt record (1900-1915); raising the hare growth rate by 20% shifts the hare peak.

| Baseline parameter | Value |
| --- | --- |
| `alpha` (prey growth) | 0.55 |
| `beta` (predation) | 0.28 |
| `delta` (predator gain) | 0.24 |
| `gamma` (predator death) | 0.8 |
| `prey0` (initial hare) | 3.0 |
| `predator0` (initial lynx) | 0.4 |

The baseline values are my recollection of commonly quoted Lotka–Volterra fits of this data set (not looked up in this session), rescaled by 10 for the unit convention above. They are a hand-chosen starting point, not an authoritative fit. **Intervention:** `alpha = 0.66` (+20%).

![Configuration](img/07-configuration.png)

- **Validate configuration** asks the Python engine to check bounds and units, and estimates the number of runs. Result: **valid, 2 runs**.
- **Run experiment** stays disabled until validation passes. The "ExperimentSpec" box shows the exact payload that will be sent.

![Validated](img/08-configuration-validated.png)

Press **Run**. The URL changes to `…/investigations/exp-a77c68836f86/experiments`. The investigation is now stored.

### Step 4. Runs and results

**Runs** lists the baseline run and the intervention run, with status and duration.

![Runs](img/09-runs.png)

**Results → Plots** shows baseline (purple), intervention (blue) and their difference (dashed). Raising `alpha` makes the hare peak higher and the cycle faster.

![Plots](img/10-results-plots.png)

**Results → Metrics** (hare = `prey`, baseline vs intervention): RMSE 1.72, maximum absolute difference 4.61, correlation 0.81, 301 valid points, 0 non-finite. DRW prints the comparison method next to every number.

![Metrics](img/11-results-metrics.png)

### Step 5. Compare with the real data (Evaluation)

**Analysis → Evaluation** asks: *how well does the stored baseline reproduce the observations?* You choose the dataset and an explicit **mapping** (hare → `prey`, lynx → `predator`, matched on `year_index`).

![Evaluation config](img/17-evaluation-config.png)

Result for the hand-chosen baseline (units: count, 1 count = 10,000 pelts):

| Pair | Points used | MAE | RMSE | Max abs error | Mean residual |
| --- | --- | --- | --- | --- | --- |
| hare ↔ prey | 16 | 0.647 | **0.863** | 2.037 | −0.027 |
| lynx ↔ predator | 16 | 0.554 | **0.664** | 1.268 | −0.171 |

![Evaluation result](img/18-evaluation-result.png)

Reading it: the typical hare error is about 8,600 pelts and the typical lynx error about 6,600. That is not a bad match for a four-parameter hand-picked model. It says nothing about whether the model is *right*.

### Step 6. Sensitivity: what matters?

**Analysis → Sensitivity** runs Sobol global sensitivity: how much of the output's variation is caused by each parameter?

![Sobol setup](img/14-sensitivity-config.png)

DRW shows the cost before you run: **256 model evaluations** (N = 32 × (6 + 2)). It took roughly **7 minutes** here.

![Sobol results](img/15-sensitivity-results.png)

**Do not trust this result.** With N = 32 the first-order indices exceed 1 (for example `alpha` S1 = 2.84) and the 95% intervals are enormous (`alpha` ST 23.3, interval 0.01–88). DRW reports this honestly instead of hiding it. The lesson: the default sample size is too small for this model, and a larger N would take much longer. Treat the table as "not converged".

### Step 7. Identifiability: can the parameters be told apart?

**Analysis → Identifiability** is a quick local test (13 evaluations).

![Identifiability](img/16-identifiability.png)

| Quantity | Value |
| --- | --- |
| Parameters / rank | 6 / 6 |
| Condition number | 1111.94 ("well conditioned") |
| Strongest correlations | `gamma · prey0` = 0.927, `delta · prey0` = 0.901 |

All six parameters are locally distinguishable at this baseline, but `prey0` is strongly entangled with `gamma` and `delta`. If you calibrate all of them, expect trade-offs between those parameters. This test is local and linearised; it does not prove global or practical identifiability from noisy data.

### Step 8. Calibration: what parameters fit best?

**Analysis → Calibration** fits chosen parameters to a dataset.

| Setting | Value |
| --- | --- |
| Dataset | `hare_lynx_1900_1915` |
| Free parameters | `alpha`, `beta`, `delta`, `gamma` |
| Starting values | 1.0, 0.5, 0.1, 0.5 (the model's own defaults, *not* my baseline) |
| Bounds | alpha 0.1–3, beta 0.05–2, delta 0.01–1, gamma 0.05–2 |
| Mapping | hare → `prey` on `year_index` |
| Objective / optimizer | RMSE / Powell (local) |
| Budget / seed | 200 evaluations / 0 |

![Calibration config](img/19-calibration-config.png)

Result: **best RMSE 0.528** at `alpha = 0.780`, `beta = 0.801`, `delta = 0.164`, `gamma = 0.545`. Status `budget_exhausted` (199 of 200 evaluations used, 1 invalid), `converged: false`, about 150 s.

![Calibration result](img/20-calibration-result.png)

Compare: the hand-chosen baseline had hare RMSE 0.863, so calibration reduced the hare error by about 39%. DRW's own note applies: this is a **point estimate** within the bounds, seed, objective and budget. It is not parameter uncertainty and not validation. The fit used only the hare series, so the lynx fit was not checked.

### Step 9. Validation

**Validation** says plainly: **not implemented in this version**, and shows the planned flow (calibration data → calibrated model → independent observations → validation → generalisation). Nothing is fabricated. Until it exists, a good calibration fit on one dataset is *fit*, not *generalisation*.

![Validation](img/13b-validation.png)

### Step 10. Evidence

**Evidence** is the chain **Question → Model → Dataset → Experiment → Evaluation → Calibration → Validation → Conclusion**. Each row expands.

![Evidence chain](img/21-evidence.png)

Open **Experiment** to see: the specification hash, isolation mode, start/finish times, the exact configuration JSON, the execution environment, artifact files with SHA-256 hashes, the manifest, and **Export evidence bundle**.

**Reproduce** re-runs the saved specification and compares with the stored result. With relative tolerance 1e-9 and absolute 1e-12 the verdict was **identical**.

![Reproduce](img/22-evidence-reproduce.png)

Some steps read "Not recorded": Evaluation and Calibration are computed on demand and **not stored** by DRW, and the chain does not link the dataset to the experiment. That is a real limitation, shown rather than hidden.

### Step 11. Ask SI

On the investigation's **SI** page, the question *"What happens to the hare and lynx peaks if the lynx death rate gamma is 20% lower?"* returned a proposal: vary `gamma` from 0.4 to 0.32, observe `prey` and `predator`, analyse `delta` and `relative_delta`, source "Rule-based planner" (no LLM provider is configured), validation passes.

![SI plan](img/24-si-plan.png)

Two things to know: the proposal was built from the **model's nominal values, not from this investigation's configuration**, and **nothing ran**. **Review in Manual** would load it into Configuration as a new draft.

---

## 4. A cheat sheet: which page for which job?

| I want to… | Go to |
| --- | --- |
| Start a new question | Investigations → New investigation (or ask SI on Overview) |
| Bring in measurements | Data |
| See what models exist | Models |
| Change a parameter and run | Investigation → Experiments → Configuration |
| See what a run produced | Investigation → Experiments → Results |
| Find out what matters | Investigation → Analysis → Sensitivity |
| Find out if parameters can be told apart | Investigation → Analysis → Identifiability |
| Compare model and observations | Investigation → Analysis → Evaluation |
| Fit parameters | Investigation → Analysis → Calibration |
| Check generalisation | Validation (not available yet) |
| Prove and reproduce a result | Investigation → Evidence |
| Find an old experiment | Experiments (project) or Search (Ctrl K) |

---

## 5. What I found while doing this (honest limits)

1. **Fixed:** the header's **New project** button closed the popover as soon as you clicked it, so you could not type a name. The button stays mounted now.
2. **Fixed (wording):** the Data pages said datasets belonged to the project. They are workspace-wide.
3. **Not fixed, backend:** a calibration whose mapping has *two* observation↔output pairs fails with a generic "502 bridge_error". The real cause is that the objective must select one pair; the error message could not be serialised. The UI also has no control to pick a pair, so **calibration is limited to one observed variable at a time** (here: hare only).
4. **Not available:** applying calibrated parameters back into the configuration; validation; linking a dataset to an investigation; storing evaluation/calibration/identifiability results.
5. **Sobol default N = 32** is too small for a six-parameter model and slow (about 7 minutes for 256 evaluations).
6. **SI planner** ignores the investigation's own configuration and uses model defaults.
7. **Stale note:** the "demonstration configuration (+10%)" banner stays visible after you have edited the values.

## 6. Reproduce this yourself

1. Copy [data/hare_lynx_1900_1915.csv](data/hare_lynx_1900_1915.csv) into `<workspace>/dataset-sources/` (default workspace: `.drw/web-workspace/`).
2. Start the app: `pnpm --filter @drw/web dev`, then open `/`.
3. Follow Steps 0–10 above with the same values. Results should match to the digits shown, because the runs are deterministic with seed 0.
