# County Population Growth
Repository for the Agglomerations post ["If demography is destiny, can communities change their fate?"]() by Jason He, Kenan Fikri, and Benjamin Glasner published on September XX, 2026. This is a follow-up to our contribution to the New York Times article ["Want to Entice New Residents? Offer Cash, for a Start"](https://www.nytimes.com/2026/09/12/business/economy/rural-america-moving-incentives.html) by Lydia DePillis.

## What the analysis finds

- Rural counties grew 2.1 percent from 2019 to 2025, after shrinking 0.2 percent over the six years before. Large urban counties moved the other way, from 5.0 percent growth to 2.0 percent.
- Rural growth is concentrated in the rural fringes of metropolitan areas. Metro rural counties grew 5.5 percent from 2019 to 2025; non-metro rural counties grew 0.9 percent.
- Residents over 55 drive rural growth in both. What changed after 2019 is that metro rural counties stopped losing younger people: their under-25 population rose 3.2 percent and their 25-to-54 population rose 4.3 percent, against losses of 1.9 and 3.0 percent in the prior six years.
- Household interstate migration peaked at 2.46 percent in 2022 and fell to 2.08 percent by 2024, close to the 1.91 percent series low set in 2010.

Every figure above is reproduced by the tables in `output/tables/`.

## Repository map

| Path | Contents |
|---|---|
| `code/County Pop and Typology.R` | The analysis. Loads and cleans the Census files, builds the crosswalk and the two panels, and writes every table. |
| `code/ARCHIVED.R` | Exploratory work that did not enter the piece. Not part of the pipeline. |
| `data/raw/` | Inputs as received. Not committed; see the table below to obtain them. |
| `data/processed/` | Checkpoints: the county crosswalk, the cached 2020 block population, and both panels. |
| `output/tables/` | Analysis tables. These are the data behind the Datawrapper charts in the piece. |
| `drafts/` | The draft piece. |
| `Infrastructure/` | Research workflow, review agents, and EIG style assets. See `Infrastructure/TEMPLATE_README.md`. |

## Data sources

| Source | File | Coverage | Supplies |
|---|---|---|---|
| Census Bureau, [intercensal county population estimates](https://www2.census.gov/programs-surveys/popest/tables/2010-2020/intercensal/county/co-est2020int-pop.xlsx) | `co-est2020int-pop.xlsx` | 2010–2020 | Population levels, 2010–2019 |
| Census Bureau, [Vintage 2020 county estimates](https://www2.census.gov/programs-surveys/popest/datasets/2010-2020/counties/totals/co-est2020-alldata.csv) | `co-est2020-alldata.csv` | 2010–2020 | Natural change and net, domestic, and international migration, 2010–2019, with the population series that produced them |
| Census Bureau, [Vintage 2025 county estimates](https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/totals/co-est2025-alldata.csv) | `co-est2025-alldata.csv` | 2020–2025 | Population and the same migration components, 2020–2025 |
| Census Bureau, [intercensal county characteristics](https://www2.census.gov/programs-surveys/popest/datasets/2010-2020/intercensal/county/asrh/cc-est2020int-agesex-all.csv) | `cc-est2020int-agesex-all.csv` | 2010–2019 | Population by five-year age group |
| Census Bureau, [Vintage 2025 county characteristics](https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/asrh/cc-est2025-agesex-all.csv) | `cc-est2025-agesex-all.csv` | 2020–2025 | Population by five-year age group; documentation in `CC-EST2025-AGESEX.pdf` |
| Census Bureau, 2020 Census PL 94-171 table P1, pulled through `tidycensus` | cached to `data/processed/block_pop_2020_ct_ak.csv` | 2020 | Block population used to weight the county crosswalk |
| CT Data Collaborative, [2022 block crosswalk](https://github.com/CT-Data-Collaborative/2022-block-crosswalk) | `crosswalk/2022blockcrosswalk.csv` | 2020 blocks | Connecticut legacy counties to planning regions |
| Block-level geographic reference file for Alaska | `crosswalk/ak_xwalk.csv` | 2020 blocks | Each Alaska block's current county assignment |
| [IPUMS USA](https://usa.ipums.org), ACS 1-year samples | `usa_00105.dat.zip`, `usa_00105.xml` | 2005–2024, no 2020 | Householder interstate migration rate |
| EIG county typology | `county_summary_final.csv` | 2023 delineation | `locale_type` and metropolitan status for every county |

Raw data are excluded from version control. The Census files download directly from the links above. The IPUMS extract must be rebuilt from an IPUMS account, and the EIG typology file is internal. The Alaska block reference file came with the project rather than from a recorded download; its provenance should be filled in before this repository is published.

## How the build works

1. **Clean.** Three Census county files are read and given consistent FIPS codes and variable names. Vintage 2020 names natural change `NATURALINC` while Vintage 2025 names it `NATURALCHG`; both are read explicitly.
2. **Crosswalk.** Counties changed between the two vintages: Connecticut retired its eight counties for nine planning regions, and two Alaska blocks moved between boroughs. The 2020 Census block population apportions each retired county's counts across its successors, producing 50 old-to-new county pairs across the Connecticut and Alaska blocks the two crosswalks cover. Every unchanged county maps to itself with weight 1, so one apportionment pass covers all 3,143 counties and yields 3,144 on the current vintage.
3. **Verify.** The build stops unless the weights partition each retired county, national totals survive the apportionment unchanged, and the resulting county set matches the current vintage exactly.
4. **Build two panels.** They are deliberately different and must not be mixed:
   - *Population panel* — intercensal 2010–2019 spliced to postcensal 2020–2025. The intercensal series is constrained to both the 2010 and the 2020 census counts, which makes it the right basis for levels and for population change.
   - *Migration panel* — the postcensal components throughout, paired with the postcensal population that produced them, so that a migration rate's numerator and denominator share a vintage.
5. **Classify and summarize.** The EIG typology joins on county FIPS. Population tables read the population panel; migration tables read the migration panel. Age detail is crosswalked the same way and collapsed into three bands: under 25, 25 to 54, and 55 and over.
6. **Build the rural growth typology.** Rural counties are split first by level — positive population growth and above-average net migration against everything else — and the high-migration group is then split into quartiles by the share of its growth that came from residents over 55.

## Outputs

All tables are written to `output/tables/`.

| Table | Contents |
|---|---|
| `County Population with Typology 2010-2025.csv` | County panel, population levels, with locale type |
| `County Migration with Typology 2010-2025.csv` | County panel, migration components, with locale type |
| `Urban-Rural Population 2010-2025.csv`, `Urban-Rural Pop 6-Year Change 2010-2025.csv` | Population and six-year change by locale type |
| `Growth of Urban-Rural Population 2010-2025.csv` | The headline chart: population indexed to 2010 = 100 |
| `Urban-Rural Net Migration 2010-2025.csv`, `Urban-Rural DOMESTIC Migration 2010-2025.csv`, `Urban-Rural INTERNATIONAL Migration Rates 2015-2025.csv` | Migration by locale type |
| `Growth of Rural Population by Metro Status 2010-2025.csv` | Rural growth, metro against non-metro |
| `Rural Population Growth by Age Band and Metro Status.csv`, `Population Growth by Age Band, Locale Type and Metro Status.csv` | Growth by age band, 2013–2019 against 2019–2025 |
| `Rural metro vs non-metro international migration rate.csv` | International migration rate within rural counties |
| `Rural Growth Typology by County.csv` | All 2,143 rural counties with their growth type |
| `Household Interstate Migration Rate 2005-2024.csv` | Annual interstate migration rate for householders |

## Reproducing the analysis

Built and run under R 4.6.0 with `data.table`, `tidyverse`, `tidycensus`, `readxl`, `ipumsr`, `cluster`, and `spatstat.univar`.

1. Place the raw files in `data/raw/`, keeping the crosswalks in `data/raw/crosswalk/`.
2. Set a Census API key for `tidycensus` (`tidycensus::census_api_key()`). This is needed only on the first run: the block population pull is cached to `data/processed/`.
3. Set `path_project` at the top of the script to your copy of the repository.
4. Run the script:

```bash
Rscript "code/County Pop and Typology.R"
```

Reading the IPUMS extract is the slow step. The script reports progress and stops with a named error if any verification fails.
