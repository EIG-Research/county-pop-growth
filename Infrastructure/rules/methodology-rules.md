---
load: referenced
---

# Methodology Review Rules

The methodology lens (`methodology-reviewer`, check ids `MR-*`) reviews research design,
inference, specification, survey weights, deflators, sampling error, and multiple testing.
Severity, confidence, evidence, refutation, and lens ownership follow
`Infrastructure/rules/review-contract.md`; this file adds the design signals, the checks with
their "don't flag when", dataset use, and the literature to cite.

## 1. Scope

A methodology concern threatens the identification strategy, could change the sign or size of
an estimate, or rests on an assumption a reader needs disclosed. Report a concern only with the
code that shows it and what you checked. A concern the author may have a valid reason for is
still worth raising; a concern you cannot tie to the code is a Question for the author.

Do not flag: code bugs (the code lens), wording and disclosure in the document (the
consistency lens), speculative threats with no plausible path to the estimate, or choices the
code's comments or the document already justify.

## 2. Design inference

Infer the design from the code, variable names, and comments.

| Signal in code | Inferred design |
|---|---|
| `post`, `treat`, `treated`, `post_treat`, `did`, treatment-by-period interactions | DiD |
| `event_time`, `relative_time`, `cohort`, `first_treated` | Staggered DiD |
| `callaway`, `csdid`, `did_multiplegt`, `sunab`, `staggered` | Staggered DiD with a modern estimator already in use |
| Two-way FE on a treatment indicator (`feols(y ~ treat \| unit + year)`, `felm`, `xtreg y treat, fe`) | Two-way FE: check whether it is a DiD |
| `fe`, `feols`, `felm`, `xtreg` with entity or time FE and no treatment timing | Panel fixed effects |
| `running`, `forcing`, `bandwidth`, `rd_plot`, `rdrobust`, `rddensity` | RD |
| `iv`, `instrument`, `endog`, `first_stage`, `ivreg`, `tsls`, `2sls`, `feiv` | IV |
| `pscore`, `propensity`, `MatchIt`, `teffects`, `psmatch2`, `match` | Matching |
| `conley`, `spatial`, `distclust` | Spatial correlation already addressed (section 5) |

If the design cannot be inferred, say so in the design context and list it under Questions for
the author, because an unknown design is not itself a flaw. Apply every matching section for a
combined design (IV-DiD, RD-DiD), plus sections 4 to 9, which apply to every project.

## 3. Design (MR-DESIGN)

**Difference-in-differences.**
1. Staggered timing is HIGH only when all three hold: treatment turns on at different times,
   effects plausibly vary by cohort or over time, and no heterogeneity-robust estimator is used
   (Callaway & Sant'Anna 2021; de Chaisemartin & D'Haultfœuille 2020; Sun & Abraham 2021;
   Borusyak, Jaravel & Spiess 2024). A Goodman-Bacon (2021) decomposition or a negative-weight
   diagnostic (de Chaisemartin & D'Haultfœuille 2020) clears the HIGH only for the static TWFE
   coefficient, never an event study, and only if it shows negligible weight on comparisons
   that use already-treated units as controls.
2. A two-way fixed-effects event study with leads and lags under staggered timing is checked
   for contamination across periods (Sun & Abraham 2021): MEDIUM when its pre-trend
   coefficients are the parallel-trends evidence or event time is binned or restricted; LOW
   otherwise, because the contamination is usually small in practice. Don't flag when an
   interaction-weighted, imputation, or other robust event study is used (`did_imputation` or
   `didimputation`, `csdid` or `did`, `did_multiplegt_dyn`, `eventstudyinteract`,
   `fixest::sunab`) or when all units are treated at the same time.
3. A passed pre-trend test is not a pass, because pre-tests have low power and conditioning on
   them distorts estimates (Roth 2022). Where parallel trends rest on a pre-test alone, or no
   pre-period evidence is shown, give a MEDIUM pointer to a pre-trend power check (Roth 2022,
   `pretrends`) and HonestDiD sensitivity analysis (Rambachan & Roth 2023; Liu 2025 for
   staggered adoption), or, with few treated units and a good pre-period fit, synthetic control
   (Abadie 2021) or synthetic DiD (Arkhangelsky et al. 2021). Don't flag when a sensitivity
   analysis or one of these designs is already reported.
4. Anticipation: treatment known before it took effect, with the periods just before it
   treated as untreated, is MEDIUM. Don't flag when the treatment date is set at the
   announcement or shifted by a stated anticipation window.
5. Spillovers: treated and control units that plausibly interact (neighbors, supply chains),
   with no discussion, is MEDIUM. Don't flag when exposed untreated units are separated from
   the controls.
6. Without never-treated units, an effect reported at a horizon at or beyond the gap between
   the latest and earliest adoption dates is HIGH: parallel trends do not identify it, and TWFE
   output there is spurious (Borusyak, Jaravel & Spiess 2024).
7. Time-varying covariates or unit-specific trends added to a TWFE DiD regression when effects
   plausibly vary: MEDIUM pointer to fitting them on untreated observations only (imputation) or
   to conditional parallel-trends estimators (Sant'Anna & Zhao 2020; Callaway & Sant'Anna 2021).
   Bad controls stay under §4 item 1.
8. Parallel trends asserted with no stated scale, where levels and logs would give different
   answers: LOW (Roth & Sant'Anna 2023). In DiD the scale is an identification choice, not
   only the estimand choice of §4 item 3.
9. A continuous-dose DiD with no untreated comparison units, or a non-absorbing treatment with
   no stated or tested no-carryover assumption: MEDIUM.
10. A triple-difference coefficient described as a difference in treatment effects between
    groups: MEDIUM; it is the effect on one group under a different identifying assumption.

**Method and data type.** A method that does not fit the data's structure (time-series methods
on a cross-section, individual-level methods on aggregates, or the reverse) is HIGH. Don't flag
when the code or document shows the structure the method needs (a panel or time index, a
disaggregation step).

**Regression discontinuity.**
1. No density or manipulation test (`rddensity`) is HIGH. Don't flag it when the running
   variable is calendar time or otherwise cannot be sorted on; flag a missing covariate-balance
   check (item 4) instead.
2. A hard-coded bandwidth with no sensitivity check is MEDIUM; `rdbwselect` or `rdrobust`
   selection is not flagged.
3. A polynomial of degree 2 or more without justification is MEDIUM (Gelman & Imbens 2019).
4. No covariate balance check at the cutoff is MEDIUM.
5. A running variable measured with error near the cutoff with no donut specification is LOW.
6. Conventional RD confidence intervals at an MSE-optimal bandwidth: a MEDIUM pointer to
   robust bias-corrected inference (Calonico, Cattaneo & Titiunik 2014). A discrete running
   variable (age in years, a score in whole points): a MEDIUM pointer to bias-aware ("honest")
   confidence intervals (Kolesár & Rothe 2018; Armstrong & Kolesár 2018; `rdhonest`). Don't flag
   when `rdrobust` robust bias-corrected results or bias-aware intervals are reported, when the
   bandwidth is deliberately undersmoothed and says so, or, for the discrete case, when the
   running variable takes many distinct values near the cutoff.
7. A fuzzy RD estimate described as a population or cutoff-wide effect rather than an effect
   for compliers at the cutoff: MEDIUM. First stage and reduced form estimated with different
   bandwidths, or no first-stage RD plot: LOW.
8. A covariate that itself jumps at the cutoff used as a control: MEDIUM, because the treatment
   and covariate effects cannot be separated. Predetermined covariates entered without
   interactions are not flagged.
9. A spatial RD that pools the whole border through one signed-distance running variable, with
   no boundary-segment fixed effects or location controls: MEDIUM pointer to Black (1999) and
   Cattaneo, Titiunik & Yu (2025).

**Instrumental variables.**
1. A first-stage F below 10 is not by itself an error, because tF and Anderson-Rubin inference
   stay valid. Over-identified: an effective F below the Montiel Olea–Pflueger critical value,
   with conventional 2SLS inference and a significance claim resting on it, is HIGH (bias
   toward OLS, undercoverage). Just-identified: F < 10 with conventional t inference is a
   MEDIUM pointer to Anderson-Rubin or tF, because conventional t is conservative there in most
   practical cases (Angrist & Kolesár 2024). No first-stage strength reported alongside
   conventional t inference is HIGH. A bootstrap does not repair weak-instrument inference.
   Don't flag when |t| exceeds the tF critical value for the observed F, or Anderson-Rubin
   inference is reported.
2. MEDIUM when |t| is below the tF critical value for the observed F (3.43 at F = 10; 1.96 needs
   F above 104.7; Lee, McCrary, Moreira & Porter 2022). The tF correction is for just-identified
   models. In an over-identified model, judge strength by the Montiel Olea–Pflueger effective F
   and its critical values; tF does not apply (Andrews, Stock & Sun 2019). Angrist & Kolesár
   (2024) supports MEDIUM here, not HIGH. Don't flag when Anderson-Rubin inference is reported.
   With heteroskedastic or clustered errors, judge strength by the robust (Kleibergen–Paap) F
   for one instrument and the effective F for several; a strength claim resting on the
   homoskedastic (Cragg–Donald) F is LOW.
3. No stated argument for the exclusion restriction (in comments or the document) is HIGH. A
   weak first stage magnifies any exclusion violation, so IV can be more biased than OLS; say
   so when both apply.
4. IV estimates described as population-wide effects rather than effects for compliers is
   MEDIUM. LOW pointers: an estimate with non-saturated controls described as a LATE (Blandhol,
   Bonney, Mogstad & Torgovitsky 2026); several instruments described as one LATE with no
   discussion of monotonicity across them (Mogstad, Torgovitsky & Walters 2021). Don't flag
   either for a design-based specification that argues the instrument's assignment directly
   (Borusyak & Hull 2024).
5. Many instruments (for example, dozens of interactions) with 2SLS only: MEDIUM pointer to a
   just-identified comparison, JIVE or UJIVE (Kolesár 2013), or LIML, noting that LIML behaves
   poorly with heterogeneous effects. A few instruments: LOW.
6. Shift-share (Bartik) instruments: MEDIUM pointers to Goldsmith-Pinkham, Sorkin & Swift (2020)
   or Borusyak, Hull & Jaravel (2022) for identification, and Adão, Kolesár & Morales (2019) for
   standard errors. Shares that do not sum to one, with no control for their sum: MEDIUM. A
   constructed ("formula") instrument that combines exogenous shocks with non-random exposure
   (network, distance, eligibility, or simulated instruments), with no recentering on the
   expected instrument or control for expected exposure: MEDIUM pointer to Borusyak & Hull
   (2023).
7. Judge or examiner designs: leniency computed without leaving out the case itself is MEDIUM,
   HIGH with many judges and few cases each (use leave-out leniency, or UJIVE with many
   controls); random assignment only within strata with no strata fixed effects is HIGH;
   monotonicity and exclusion (a judge who shapes other decisions) are Questions pointing to
   the subgroup-ranking and pairwise tests (Dobbie, Goldin & Yang 2018; Frandsen, Lefgren &
   Leslie 2023).
8. More than one endogenous variable with only per-equation first-stage F statistics: MEDIUM
   pointer to a joint weak-instrument test (Sanderson & Windmeijer 2016; Lewis & Mertens 2025),
   because each first stage can look strong while the instruments are jointly weak.

**Matching.**
1. No overlap (common support) check is HIGH; no post-matching balance statistics
   (`bal.tab`, `love.plot`, standardized differences) is HIGH.
2. The estimand depends on the implementation: `MatchIt::matchit()` targets the ATT by default
   and Stata `teffects psmatch` the ATE (`atet` gives the ATT). Flag MEDIUM when the stated
   estimand differs from the one the call estimates.
3. Caliper or neighbor count hard-coded without a sensitivity check is LOW.

## 4. Specification (MR-SPEC)

1. Bad controls: a post-treatment variable or an outcome proxy used as a control is HIGH.
2. Omitted confounders: where a named, plausible confounder is absent, a LOW pointer to a
   sensitivity analysis (Oster 2019; Cinelli & Hazlett 2020) with the variable named. A generic
   "may have omitted variables" is not a finding.
3. Log against level is an estimand choice, not an error; do not flag it. But a log-OLS
   coefficient described as the percent change in the average outcome is LOW: that is the PPML
   estimand, not the log-OLS one (Chen & Roth 2024).
4. The log of an outcome with zeros (`log(y + 1)`, `asinh(y)`) makes the estimate depend on the
   units: a MEDIUM pointer to Chen & Roth (2024) that names the fix fitting the question: Poisson
   pseudo-maximum likelihood (PPML) when the extensive and intensive margins need not be
   separated; a participation regression plus bounds for the intensive margin (Lee 2009) when
   they must be; an explicit value for zero when the document takes a stand. Dropping zero
   outcomes to estimate an intensive-margin effect of a treatment that can change participation
   is MEDIUM (selection). Don't flag an outcome with no zeros in the analysis sample.

## 5. Inference (MR-INFERENCE)

1. Treatment assigned at a group level (state, county, firm) with standard errors not clustered
   at that level or above is HIGH. Individual-level assignment without cluster sampling is not
   flagged (Abadie, Athey, Imbens & Wooldridge 2023).
2. An unknown cluster count is a Question. Fewer than 20 clusters, or very unbalanced clusters (`summclust` leverage), with
   conventional cluster-robust errors and a significance claim resting on them is MEDIUM
   (MacKinnon, Nielsen & Webb 2023); LOW when the document discloses the limitation. Five or
   fewer treated clusters with a significance claim resting on conventional or wild-bootstrap
   inference is HIGH, because the wild bootstrap also fails there (Conley & Taber 2011;
   MacKinnon & Webb 2017; Alvarez, Ferman & Wüthrich 2025). Don't flag when randomization
   inference or Conley-Taber inference is used. The numeric thresholds are this template's
   convention; the literature sets none.
3. Panel data with errors that ignore serial correlation (not clustered by unit) is MEDIUM. A
   short panel (few periods per unit) estimated with unit fixed effects or first differences,
   errors not clustered by unit, and a significance claim resting on them is HIGH (Bertrand,
   Duflo & Mullainathan 2004).
4. Geographic data with no attention to spatial correlation is LOW. Conley (1999) standard
   errors with a distance cutoff so wide that most pairs fall inside it: a LOW pointer to Conley
   & Kelly (2025). Spatial correlation in errors is an inference issue; spatial spillovers bias
   the estimate and belong to §3 (DiD item 5).
5. Homoskedastic errors in a cross-section is LOW.
6. Errors clustered on intersection cells (for example, state by industry) where the argument
   requires two-way clustering (Cameron, Gelbach & Miller 2011): MEDIUM, because cell clustering
   is less conservative than clustering on either dimension. A description such as "clustered
   by state and industry", with code that does not settle which: Question.
7. Shift-share designs need exposure-robust standard errors: see §3, Instrumental variables,
   item 6.

## 6. Survey weights and dataset pitfalls (MR-WEIGHTS, MR-SURVEY)

These apply when the code uses a recognized public dataset, identified with at least two
corroborating signals: file names (`cps_*.dta`, `acs_2022.csv`), characteristic variables
(`wtfinl`, `asecwt`, `perwt`, `PWGTP`), loaders (`ipumsr::read_ipums_micro()`,
`tidycensus::get_acs()`), or comments naming the survey. A lone `data.csv` identifies nothing.

- Read the registry at `Infrastructure/references/datasets/registry.yaml`, and the project
  overlay `data/docs/dataset-registry.yaml` when it exists. `weights: not_applicable` marks an
  administrative or aggregate source with no sampling weights; skip the weight checks for it.
- Entries marked `verification: verified` (signed against their `sources`) are authoritative.
  Treat `unverified` and `parsed` entries as leads: before one drives a HIGH finding, confirm
  the fact in the codebook (fetch the page with `WebFetch`, read only) or cite the entry's
  `sources` URL that states it. Without a fetched or cited source, report at medium confidence.
- If a dataset clearly in use is missing from the registry, note it and recommend the
  `document-data` workflow.

Checks:
1. A population descriptive (a mean, share, or total the document presents as describing the
   population) computed without the survey weight is HIGH. An unweighted regression is MEDIUM, with the fix "state the
   rationale" (Solon, Haider & Wooldridge 2015). Neither is flagged when the registry marks the
   weights `not_applicable`, when the text describes the sample rather than the population, or
   when weighted and unweighted results are shown to agree.
2. The wrong weight for the analysis is HIGH: the person weight for a household statistic or
   the reverse (`PWGTP` against `WGTP` in ACS PUMS; `asecwt` against `asecwth` in the CPS ASEC),
   the basic monthly CPS weight for ASEC income, a final weight where a supplement weight
   applies.
3. A registry pitfall that the code triggers takes the pitfall's severity: SCF implicates used
   singly instead of combined across all five (Rubin 1987), HIGH; HMDA without an action-type
   filter for originations, HIGH; top-coded income as an outcome with no treatment of the top
   code, MEDIUM; only the main weight used when the survey provides replicate weights and
   standard errors matter, LOW.

*American Community Survey.*
4. Dollar levels from raw Census 5-year PUMS computed from income amounts without `ADJINC`
   (or housing-cost amounts without `ADJHSG`) are HIGH; in a 1-year file the omission is
   MEDIUM. IPUMS multi-year extracts are already in final-year dollars (its `ADJUST` is not
   `ADJINC`), so they are not flagged. IPUMS 1-year extracts are not flagged either: IPUMS
   leaves amounts in survey-period dollars and calls the Census adjustment factor imperfect;
   a stated inflation adjustment across years (§7) is what matters.
5. Comparing ACS estimates with no margin of error or significance test is MEDIUM; comparing
   overlapping 5-year periods is MEDIUM. Don't flag a comparison whose MOEs or test are shown.
6. Geography that changed between vintages (2020 census tracts, 2022 PUMAs, Connecticut's
   planning regions in place of counties) or ZIP codes matched to ZCTAs as if equal is MEDIUM.
   Sources: the Census Bureau's 2020-2024 ACS 5-Year PUMS User Guide (ADJINC annualizes and
   inflation-adjusts income in multi-year files) and IPUMS, "Comparing Census Bureau and IPUMS
   USA Inflation Adjustments to American Community Survey Income Variables".

*Current Population Survey.*
7. The weight follows the purpose: `wtfinl` for basic monthly data, `asecwt` for the ASEC,
   `earnwt` for outgoing-rotation earnings and hours, and `compwt` only to replicate published
   BLS labor-force figures. Another choice is item 2's wrong weight.
8. Weights pooled across months or years without rescaling are HIGH for population totals; they
   need no finding for means, shares, or pweighted regressions, which are scale-free.
9. ASEC income refers to the calendar year before the survey: labelling it with the survey year
   is MEDIUM. The 2014 ASEC used without its split-sample flag (`HFLAG`) is MEDIUM.
   Sources: IPUMS CPS variable descriptions for `WTFINL`, `COMPWT`, `EARNWT`, `ASECWT`, and
   `HFLAG`.

## 7. Deflators and seasonal adjustment (MR-DEFLATE)

1. Dollar amounts compared across years with no stated deflator (CPI-U, CPI-U-RS, C-CPI-U,
   PCE) is MEDIUM; HIGH when the document claims a real change. Don't flag a series already in
   real or chained dollars, such as BEA chained-dollar GDP.
2. Seasonally adjusted and not seasonally adjusted series mixed in one comparison is MEDIUM.

## 8. Sample construction (MR-SAMPLE)

1. An unbalanced panel with no look at attrition is MEDIUM.
2. The unit of observation does not match the unit of analysis (person-level data with firm
   fixed effects and no firm-level clustering; a key duplicated on one side of a merge without
   deduplication) is MEDIUM.
3. An undocumented filter as such is the consistency lens's undisclosed choice
   (CC-UNDISCLOSED). Report MR-SAMPLE only for a restriction's design consequence, at most one
   finding per script, listing its restrictions.
4. Raw and analysis sample sizes that differ substantially with no accounting of the drops is
   HIGH.

**Descriptive checks.** Report a missing step only when it could hide an error in a reported
result, and name that result:
- a proportion or rate whose mean falls outside [0, 1], or N varying across variables without
  explanation, MEDIUM;
- missingness undocumented for a key variable from a source known to be incomplete, several
  restrictions with no count of what each drops, or several merges with no match rates, MEDIUM;
- a hard-coded outlier threshold with no comment, MEDIUM; spikes at round values or values
  outside a variable's valid range, MEDIUM;
- no pre-treatment comparison table in a study with a defined treatment group, MEDIUM;
- no distribution summary for a skewed outcome, no trend plot in panel data, or no external
  benchmark for a novel administrative source, LOW.

## 9. Multiple testing (MR-MULTIPLE)

1. Many outcomes tested within one claim family (one hypothesis stated in the document) with no
   correction (Romano-Wolf, Benjamini-Hochberg, `p.adjust()`, `wyoung`) is MEDIUM. Outcomes in
   different claim families, and descriptive outcomes, are not counted together.
2. Results reported only for the subsample that is significant, with the full-sample result
   run but absent, is HIGH.
3. Commented-out specifications that were run and not reported is a Question, not a finding.
   Observational policy work is not expected to be pre-registered; do not ask for it.

## 10. War-room export

If a war-room ledger exists for a reviewed script (located under WR-I5 in
`Infrastructure/rules/code-war-room-rules.md`, confirmed by its `project.id` and
`script.path`), read its `assumption_export` before inferring the design. Prefer a stated
assumption to an inferred one, but a stated intent the code does not implement is still a
finding. A block marked `needs-change` is an acknowledged defect: note it and cite the block id
instead of raising it again. An `unresolved` block is an open question, at least MEDIUM. Most
projects have no war room, and a missing export is never a finding.

## 11. Literature to cite

Use these in each finding's explanation of why it is a concern. Each DOI was resolved through
Crossref on 2026-09-29 or 2026-09-30; cite the print year shown. Working papers are given by
arXiv id or URL, checked on 2026-09-30.

| Topic | References (DOI) |
|---|---|
| Parallel trends and pre-tests | Roth (2022) 10.1257/aeri.20210236; Rambachan & Roth (2023) 10.1093/restud/rdad018; Roth, Sant'Anna, Bilinski & Poe (2023) 10.1016/j.jeconom.2023.03.008; Roth & Sant'Anna (2023) 10.3982/ECTA19402; Liu, Ziyi (2025) arXiv:2509.01829 |
| DiD with covariates | Sant'Anna & Zhao (2020) 10.1016/j.jeconom.2020.06.003 |
| Staggered DiD | Goodman-Bacon (2021) 10.1016/j.jeconom.2021.03.014; Callaway & Sant'Anna (2021) 10.1016/j.jeconom.2020.12.001; de Chaisemartin & D'Haultfœuille (2020) 10.1257/aer.20181169; Sun & Abraham (2021) 10.1016/j.jeconom.2020.09.006; Borusyak, Jaravel & Spiess (2024) 10.1093/restud/rdae007 |
| Synthetic control and synthetic DiD | Abadie (2021) 10.1257/jel.20191450; Arkhangelsky et al. (2021) 10.1257/aer.20190159 |
| RD | Lee & Lemieux (2010) 10.1257/jel.48.2.281; Calonico, Cattaneo & Titiunik (2014) 10.3982/ECTA11757; Kolesár & Rothe (2018) 10.1257/aer.20160945; Gelman & Imbens (2019) 10.1080/07350015.2017.1366909; Armstrong & Kolesár (2018) 10.3982/ECTA14434; Black (1999) 10.1162/003355399556070; Cattaneo, Titiunik & Yu (2025) arXiv:2510.26051 (distance-based) and arXiv:2505.05670 (location-based) |
| Weak instruments | Lee, McCrary, Moreira & Porter (2022) 10.1257/aer.20211063; Andrews, Stock & Sun (2019) 10.1146/annurev-economics-080218-025643; Montiel Olea & Pflueger (2013) 10.1080/00401706.2013.806694; Angrist & Kolesár (2024) 10.1016/j.jeconom.2022.12.012; Sanderson & Windmeijer (2016) 10.1016/j.jeconom.2015.06.004; Lewis & Mertens (2025) 10.1093/restud/rdaf103; Kolesár (2013), working paper, princeton.edu/~mkolesar/papers/late_estimation.pdf |
| IV with heterogeneous effects | Mogstad, Torgovitsky & Walters (2021) 10.1257/aer.20190221; Blandhol, Bonney, Mogstad & Torgovitsky (2026) 10.1093/restud/rdag029; Borusyak & Hull (2024) 10.1257/pandp.20241046 |
| Judge designs | Dobbie, Goldin & Yang (2018) 10.1257/aer.20161503; Frandsen, Lefgren & Leslie (2023) 10.1257/aer.20201860 |
| Shift-share and formula instruments | Goldsmith-Pinkham, Sorkin & Swift (2020) 10.1257/aer.20181047; Borusyak, Hull & Jaravel (2022) 10.1093/restud/rdab030; Adão, Kolesár & Morales (2019) 10.1093/qje/qjz025; Borusyak & Hull (2023) 10.3982/ECTA19367 |
| Clustering | Abadie, Athey, Imbens & Wooldridge (2023) 10.1093/qje/qjac038; MacKinnon, Nielsen & Webb (2023) 10.1016/j.jeconom.2022.04.001; Conley & Taber (2011) 10.1162/REST_a_00049; MacKinnon & Webb (2017) 10.1002/jae.2508; Alvarez, Ferman & Wüthrich (2025) arXiv:2504.19841; Bertrand, Duflo & Mullainathan (2004) 10.1162/003355304772839588; Cameron, Gelbach & Miller (2008) 10.1162/rest.90.3.414; Cameron, Gelbach & Miller (2011) 10.1198/jbes.2010.07136 |
| Spatial correlation | Conley (1999) 10.1016/S0304-4076(98)00084-0; Conley & Kelly (2025) 10.1016/j.jinteco.2024.104027 |
| Bad controls | Angrist & Pischke (2009), *Mostly Harmless Econometrics* 10.1515/9781400829828 |
| Omitted-variable sensitivity | Oster (2019) 10.1080/07350015.2016.1227711; Cinelli & Hazlett (2020) 10.1111/rssb.12348 |
| Logs with zeros | Chen & Roth (2024) 10.1093/qje/qjad054; Lee (2009) 10.1111/j.1467-937X.2009.00536.x |
| Multiple testing | Romano & Wolf (2005) 10.1111/j.1468-0262.2005.00615.x; Benjamini & Hochberg (1995) 10.1111/j.2517-6161.1995.tb02031.x |
| Matching | Imbens (2015), *Journal of Human Resources* 10.3368/jhr.50.2.373 |
| Survey weights | Solon, Haider & Wooldridge (2015) 10.3368/jhr.50.2.301; Lumley (2010), *Complex Surveys* 10.1002/9780470580066; Deaton (1997), *The Analysis of Household Surveys* 10.1596/0-8018-5254-4 |
| Missing data and multiple imputation (SCF) | Little & Rubin (2002) 10.1002/9781119013563; Rubin (1987) 10.1002/9780470316696 |

## 12. Findings

Findings follow `Infrastructure/rules/review-contract.md` and the findings schema (lens `MR`);
the renderer owns IDs, order, counts, risk, and the HTML. In each finding, `explanation` gives
the econometric intuition with a reference from section 11, and `fix` names the concrete checks
or changes. Give each finding a severity (impact if true) and a confidence (how likely it is
true), and try to refute each HIGH finding before reporting it.

Package defaults cited above, checked 2026-09-29: `formals(MatchIt::matchit)$estimand` is
`"ATT"` (local run); Stata [CAUSAL] teffects psmatch lists `ate` as "the default" and `atet` for
the treated.
