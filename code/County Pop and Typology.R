# Population and County Typology Data Build

# -----------------------------------------------------------------------------
# remove dependencies
rm(list = ls())

suppressPackageStartupMessages({
  library(data.table)
  library(tidyverse)
  library(tidycensus)
  library(dplyr)
  library(tidyr)
  library(readxl)
  library(ipumsr)
  library(cluster)            # silhouette() for cluster diagnostics
  library(spatstat.univar)   # weighted.median() for weighted ACS quantiles
})

# --- Paths -------------------------------------------------------------------
if (!exists("path_project")) {
  path_project   <- "/Users/jiaxinhe/Documents/projects/Claude Projects/nyt-pop-typology"
  path_data      <- file.path(path_project, "data")
  path_raw       <- file.path(path_data, "raw")
  path_crosswalk <- file.path(path_raw, "crosswalk")
  path_processed <- file.path(path_data, "processed")
  path_output    <- file.path(path_project, "output/tables")
}

######### Data Analysis #########
### Clean Census population data from 2010 to 2025 ###
# 2010 to 2019 intercensual population estimate data
cty_pop_10_19 <- read_xlsx(
  file.path(path_raw, "co-est2020int-pop.xlsx"),
  skip = 3
)

cty_pop_10_19_clean <- cty_pop_10_19 %>%
  rename(geo_name = ...1, pop_census_2010 = ...2, pop_census_2020 = ...13) %>%
  filter(geo_name != "United States", !is.na(pop_census_2010)) %>%
  mutate(geo_name_clean = str_remove(geo_name, "^\\.+")) %>%
  separate(
    geo_name_clean,
    into  = c("county_name", "state_name"),
    sep   = ",\\s*",
    extra = "merge",   # guards against extra commas landing in state_name
    fill  = "right"    # NA rather than error if a row has no comma
  ) %>%
  left_join(fips_codes %>%
              mutate(county_fips = paste0(state_code, county_code),
                     county_name = case_when(
                       county == "Petersburg Census Area" ~"Petersburg Borough",
                       county == "La Salle Parish" ~ "LaSalle Parish",
                       county == "Dona Ana County" ~ "Doña Ana County",
                       TRUE ~ county
                     )) %>%
              select(state_fips = state_code, state_abb = state, state_name, county_fips, county_name),
            by = c("state_name", "county_name")) %>%
  select(county_fips, county_name, state_fips, state_name,
         pop_census_2010, starts_with("20"), pop_census_2020) %>%
  rename_with(
    ~ paste0("pop_estimate_", .x),
    .cols = as.character(2010:2019)
  )

# 2010 to 2019 population migration data
cty_pop_10_19_mig <- read.csv(
  file.path(path_raw, "co-est2020-alldata.csv"),
  fileEncoding = "latin1"
)

cty_pop_10_19_mig_clean <- cty_pop_10_19_mig %>%
  filter(SUMLEV == 50) %>%
  mutate(state_fips = str_pad(STATE, 2, "left", "0"),
         county_fips = paste0(state_fips, str_pad(COUNTY, 3, "left", "0"))) %>%
  select(county_fips, county_name = CTYNAME, state_fips, state_name = STNAME,
         starts_with("POPESTIMATE"),
         starts_with("NATURALINC"),   # Vintage 2020 names this NATURALINC, not NATURALCHG
         starts_with("NETMIG"),
         starts_with("DOMESTICMIG"),
         starts_with("INTERNATIONALMIG")) %>%
  rename_with(~ .x %>%
                # Insert an underscore before 4-digit years and convert to lowercase
                str_replace("(\\d{4})$", "_\\1") %>%
                tolower() %>%
                # Map Census abbreviations to friendly names
                str_replace("^popestimate_", "pop_est_old_") %>%
                str_replace("^naturalinc_", "natural_change_") %>%
                str_replace("^netmig_", "net_migration_") %>%
                str_replace("^internationalmig_", "international_migration_") %>%
                str_replace("^domesticmig_", "domestic_migration_")
  )

# 2020 to 2025 population and migration data
cty_pop_20_25 <- read.csv(
  file.path(path_raw, "co-est2025-alldata.csv"),
  fileEncoding = "latin1"
)

cty_pop_20_25_clean <- cty_pop_20_25 %>%
  filter(SUMLEV == 50) %>%
  mutate(state_fips = str_pad(STATE, 2, "left", "0"),
         county_fips = paste0(state_fips, str_pad(COUNTY, 3, "left", "0"))) %>%
  select(county_fips, county_name = CTYNAME, state_fips, state_name = STNAME,
         starts_with("POPESTIMATE"),
         starts_with("NATURALCHG"),
         starts_with("NETMIG"),
         starts_with("DOMESTICMIG"),
         starts_with("INTERNATIONALMIG")) %>%
  rename_with(~ .x %>%
                # Insert an underscore before 4-digit years and convert to lowercase
                str_replace("(\\d{4})$", "_\\1") %>%
                tolower() %>%
                # Map Census abbreviations to friendly names
                str_replace("^popestimate_", "pop_estimate_") %>%
                str_replace("^naturalchg_", "natural_change_") %>%
                str_replace("^netmig_", "net_migration_") %>%
                str_replace("^internationalmig_", "international_migration_") %>%
                str_replace("^domesticmig_", "domestic_migration_")
  )

### Crosswalk pre-2022 counties to the most recent vintage ###
# Only Connecticut actually changes between the two files: the Vintage 2020 estimates
# already carry the Alaska Valdez-Cordova split (02261 -> 02063 Chugach + 02066 Copper
# River) back to 2010. The Alaska crosswalk is still applied below so the one post-2020
# Alaska boundary change (two blocks moved from 02105 Hoonah-Angoon to 02100 Haines) is
# handled by code rather than by assumption, and so a future change is caught here.

# CT census block crosswalk from here: https://github.com/CT-Data-Collaborative/2022-block-crosswalk/
ct_block_crosswalk <- read.csv(file.path(path_crosswalk, "2022blockcrosswalk.csv"),
                               colClasses = "character")
ak_block_crosswalk_16 <- read.csv(file.path(path_crosswalk, "ak_xwalk.csv"),
                                  colClasses = "character")

# Query census block population via tidyCensus API and generate crosswalk, store in data/processed
# 1) Pull 2020 Census block population (PL 94-171 table P1). Both crosswalks are keyed to
#    2020 tabulation blocks, so these counts supply the apportionment weights. Cache the
#    pull so reruns do not re-hit the API.
path_block_pop <- file.path(path_processed, "block_pop_2020_ct_ak.csv")

if (file.exists(path_block_pop)) {
  message("Reading cached 2020 block population from ", basename(path_block_pop))
  block_pop_2020 <- read.csv(path_block_pop,
                             colClasses = c(block_fips = "character",
                                            block_pop_int = "integer"))
} else {
  message("Querying 2020 Census block population for CT and AK via tidycensus")
  block_pop_2020 <- get_decennial(geography = "block",
                                  variables = "P1_001N",
                                  state     = c("CT", "AK"),
                                  year      = 2020,
                                  sumfile   = "pl",
                                  output    = "wide") |>
    transmute(block_fips = GEOID, block_pop_int = as.integer(P1_001N))

  write.csv(block_pop_2020, path_block_pop, row.names = FALSE)
}

# 2) Map every 2020 block in a changed state to its pre-2022 county and its current county.
#    Connecticut: the 8 legacy counties were retired in favor of 9 councils of government
#    ("planning regions"), which Census adopted as county equivalents with Vintage 2022.
ct_block_map <- ct_block_crosswalk |>
  transmute(block_fips      = block_fips_2020,
            county_fips_old = county_fips_2020,
            county_fips_new = ce_fips_2022)

#    Alaska: the Census block-level geographic reference file carries each block's current
#    county, while the 2020 block FIPS prefix carries the county it was tabulated in.
ak_block_map <- ak_block_crosswalk_16 |>
  transmute(block_fips      = tabblk2020,
            county_fips_old = substr(tabblk2020, 1L, 5L),
            county_fips_new = cty)

# 3) Aggregate block population to old-by-new county pairs and build the weights. Blocks
#    present in a crosswalk but absent from the Census pull are treated as unpopulated.
county_crosswalk <- bind_rows(ct_block_map, ak_block_map) |>
  left_join(block_pop_2020, by = "block_fips") |>
  mutate(block_pop_int = coalesce(block_pop_int, 0L)) |>
  group_by(county_fips_old, county_fips_new) |>
  summarise(pop_2020_int = sum(block_pop_int),
            n_blocks_int = n(),
            .groups = "drop") |>
  group_by(county_fips_old) |>
  mutate(pop_old_county_int = sum(pop_2020_int),
         # Block counts are a fallback only if an old county had no 2020 population.
         weight = if_else(pop_old_county_int > 0L,
                          pop_2020_int / pop_old_county_int,
                          n_blocks_int / sum(n_blocks_int))) |>
  ungroup() |>
  arrange(county_fips_old, county_fips_new)

write.csv(county_crosswalk,
          file.path(path_processed, "county_crosswalk_pre2022_to_current.csv"),
          row.names = FALSE)

message("Crosswalk built: ", n_distinct(county_crosswalk$county_fips_old),
        " pre-2022 counties -> ", n_distinct(county_crosswalk$county_fips_new),
        " current counties across ", nrow(county_crosswalk), " pairs")

# Crosswalk cty_pop_10_19 to most recent county vintage, and link with cty_pop_20_25
# 4) Extend the crosswalk to every county in the 2010-2019 files. A county whose geography
#    did not change maps to itself with weight 1, so the apportionment below is a single
#    operation over all 3,143 counties rather than a special case for CT and AK.
county_crosswalk_all <- cty_pop_10_19_clean |>
  distinct(county_fips) |>
  filter(!county_fips %in% county_crosswalk$county_fips_old) |>
  transmute(county_fips_old = county_fips,
            county_fips_new = county_fips,
            weight          = 1) |>
  bind_rows(county_crosswalk |> select(county_fips_old, county_fips_new, weight))

# 5) Join the two 2010-2019 sources on legacy counties before crosswalking. Both are counts,
#    so a single apportionment pass and a single conservation check cover both output panels.
#    The two population series keep distinct prefixes (pop_estimate_ intercensal,
#    pop_est_old_ postcensal) so nothing collides. Vintage 2020's own 2020 columns are
#    dropped: the Vintage 2025 file supplies 2020 onward. pop_census_2020 survives because it
#    is an April 1 census count, not a postcensal estimate.
cty_10_19_legacy <- cty_pop_10_19_clean |>
  inner_join(cty_pop_10_19_mig_clean |>
               select(-county_name, -state_fips, -state_name, -ends_with("_2020")),
             by = "county_fips")

# 6) Apportion the 2010-2019 series onto current counties. Every measure is a count, so a
#    retired county's value is split across its successors in proportion to their share of
#    the county's 2020 Census population. Those shares are held fixed across 2010-2019,
#    which is the approximation this crosswalk rests on: it is exact only insofar as
#    within-county population and migration were distributed as they were in 2020. County
#    names are taken from the current vintage so both files share join keys exactly.
measure_cols <- setdiff(names(cty_10_19_legacy),
                        c("county_fips", "county_name", "state_fips", "state_name"))

cty_10_19_current <- cty_10_19_legacy |>
  inner_join(county_crosswalk_all, by = c("county_fips" = "county_fips_old")) |>
  group_by(county_fips_new) |>
  summarise(across(all_of(measure_cols), \(x) sum(x * weight)), .groups = "drop") |>
  rename(county_fips = county_fips_new) |>
  left_join(cty_pop_20_25_clean |>
              select(county_fips, county_name, state_fips, state_name),
            by = "county_fips") |>
  relocate(county_fips, county_name, state_fips, state_name)

# 7) Verify the crosswalk before using it: weights must partition each retired county,
#    national totals must be conserved, and the county set must match the current vintage.
weight_check <- county_crosswalk_all |>
  group_by(county_fips_old) |>
  summarise(total_weight = sum(weight), .groups = "drop") |>
  filter(abs(total_weight - 1) > 1e-9)

if (nrow(weight_check) > 0L) {
  stop("Crosswalk weights do not sum to 1 for ", nrow(weight_check),
       " pre-2022 counties, including ", weight_check$county_fips_old[1])
}

national_totals_check <- tibble(
  measure = measure_cols,
  before  = map_dbl(measure_cols, \(v) sum(cty_10_19_legacy[[v]])),
  after   = map_dbl(measure_cols, \(v) sum(cty_10_19_current[[v]]))
) |>
  mutate(abs_diff = abs(after - before))

if (any(national_totals_check$abs_diff > 1e-6)) {
  stop("Crosswalk changed the national total for: ",
       paste(national_totals_check$measure[national_totals_check$abs_diff > 1e-6],
             collapse = ", "))
}

if (!setequal(cty_10_19_current$county_fips, cty_pop_20_25_clean$county_fips)) {
  stop("Crosswalked 2010-2019 county set does not match the 2020-2025 county set")
}

message("Crosswalk verified: ", nrow(cty_10_19_current),
        " counties matching the current vintage, national totals conserved for all ",
        length(measure_cols), " measures")

### Build the two 2010-2025 panels ###
# The two panels deliberately use different population series and must not be mixed.
#
# Panel 1 (population): intercensal 2010-2019 spliced to postcensal 2020-2025. The
# intercensal series is constrained to both the 2010 and the 2020 census counts, so it is
# the right basis for population levels and population change. It is NOT a valid denominator
# for the postcensal migration components, because those were estimated against a different
# population series.
#
# Panel 2 (migration): the postcensal components throughout, paired with the postcensal
# population series that produced them, so that a migration rate's numerator and denominator
# come from the same vintage. This is why pop_estimate_2010-2019 here is Vintage 2020's own
# estimate rather than the intercensal figure.
#
# Both panels break at the 2019/2020 seam. In Panel 2 the break is larger: the Vintage 2020
# series is anchored to the 2010 census, so by 2019 it sits about 0.6 percent below the
# intercensal series nationally (328.33m against 330.23m, the accumulated error of closure),
# while 2020-2025 is anchored to the 2020 census. Rates are internally consistent within
# 2010-2019 and within 2020-2025, not across the seam.
#
# In both panels the flow measures dated 2010 and 2020 cover only April 1 to July 1 of that
# year, not a full 12 months, so neither belongs in a multi-year flow sum.
cty_pop_panel_10_25 <- cty_10_19_current |>
  select(county_fips, county_name, state_fips, state_name,
         pop_census_2010, num_range("pop_estimate_", 2010:2019), pop_census_2020) |>
  full_join(cty_pop_20_25_clean |>
              select(county_fips, county_name, state_fips, state_name,
                     num_range("pop_estimate_", 2020:2025)),
            by = c("county_fips", "county_name", "state_fips", "state_name"))

cty_mig_panel_10_25 <- cty_10_19_current |>
  select(county_fips, county_name, state_fips, state_name,
         num_range("pop_est_old_", 2010:2019),
         num_range("natural_change_", 2010:2019),
         num_range("net_migration_", 2010:2019),
         num_range("domestic_migration_", 2010:2019),
         num_range("international_migration_", 2010:2019)) |>
  rename_with(~ str_replace(.x, "^pop_est_old_", "pop_estimate_")) |>
  full_join(cty_pop_20_25_clean,
            by = c("county_fips", "county_name", "state_fips", "state_name"))

# Confirm each panel came out complete and on the current county vintage.
if (anyNA(cty_pop_panel_10_25) || anyNA(cty_mig_panel_10_25)) {
  stop("Missing values after building the panels; the 2010-2019 and 2020-2025 county sets ",
       "did not align")
}
if (nrow(cty_pop_panel_10_25) != nrow(cty_pop_20_25_clean) ||
    nrow(cty_mig_panel_10_25) != nrow(cty_pop_20_25_clean)) {
  stop("Panel row counts do not match the current county vintage")
}

# Saved as .rds plus .csv rather than the usual .rds/.parquet pair: arrow is not
# installed in this project environment, so .csv carries the interoperable copy.
saveRDS(cty_pop_panel_10_25,
        file.path(path_processed, "county_population_panel_2010_2025.rds"))
write.csv(cty_pop_panel_10_25,
          file.path(path_processed, "county_population_panel_2010_2025.csv"),
          row.names = FALSE)

saveRDS(cty_mig_panel_10_25,
        file.path(path_processed, "county_migration_panel_2010_2025.rds"))
write.csv(cty_mig_panel_10_25,
          file.path(path_processed, "county_migration_panel_2010_2025.csv"),
          row.names = FALSE)

message("Population panel: ", nrow(cty_pop_panel_10_25), " counties x ",
        ncol(cty_pop_panel_10_25), " columns (intercensal 2010-2019, postcensal 2020-2025)")
message("Migration panel:  ", nrow(cty_mig_panel_10_25), " counties x ",
        ncol(cty_mig_panel_10_25), " columns (postcensal throughout, with its own population)")

# Load the most recent EIG county typology
county_typology_2023 <- read.csv(file.path(path_raw, "county_summary_final.csv"),
                                 fileEncoding = "latin1")

county_locale_type <- county_typology_2023 %>%
  mutate(county_fips = str_pad(county_fips, 5, "left", "0"),
         is_metro = ifelse(!is.na(metro_fips), "metro", "non_metro")) %>%
  select(county_fips, locale_type, is_metro)

cty_pop_with_typology <- cty_pop_panel_10_25 %>%
  left_join(county_locale_type, by = "county_fips") %>%
  select(county_fips, county_name, locale_type, is_metro, state_fips, state_name,
         pop_census_2010, starts_with("pop_estimate"), pop_census_2020)

cty_mig_with_typology <- cty_mig_panel_10_25 %>%
  left_join(county_locale_type, by = "county_fips") %>%
  select(county_fips, county_name, locale_type, is_metro, state_fips, state_name,
         starts_with("pop_estimate"),
         starts_with("natural_change"),
         starts_with("net_migration"),
         starts_with("international_migration"),
         starts_with("domestic_migration"))

# The typology is published on the current county vintage, so every county should match.
if (anyNA(cty_pop_with_typology$locale_type) || anyNA(cty_mig_with_typology$locale_type)) {
  stop("Counties without a locale_type after joining the typology: ",
       sum(is.na(cty_pop_with_typology$locale_type)))
}

write.csv(cty_pop_with_typology,
          file.path(path_output, "County Population with Typology 2010-2025.csv"),
          row.names = FALSE)

write.csv(cty_mig_with_typology,
          file.path(path_output, "County Migration with Typology 2010-2025.csv"),
          row.names = FALSE)

# Summarize by county typology
# Population tables read the intercensal panel; migration tables read the postcensal panel.
pop_by_typology <- cty_pop_with_typology %>%
  group_by(locale_type) %>%
  summarise(across(starts_with("pop_estimate"), ~sum(.))) %>%
  ungroup() %>%
  rename_with(~c("County Type", 2010:2025)) %>%
  mutate(pop_chng_13_19 = `2019` - `2013`,
         pop_pct_chng_13_19 = pop_chng_13_19/`2013` * 100,
         avg_pop_pct_chng_13_19 = ((1 + pop_pct_chng_13_19/100)^(1/6) - 1) * 100,
         pop_chng_19_25 = `2025` - `2019`,
         pop_pct_chng_19_25 = pop_chng_19_25/`2019` * 100,
         avg_pop_pct_chng_19_25 = ((1 + pop_pct_chng_19_25/100)^(1/6) - 1) * 100,
         pop_pct_chng_diff_6yr = pop_pct_chng_19_25 - pop_pct_chng_13_19,
         avg_annual_pop_pct_chng_diff = avg_pop_pct_chng_19_25 - avg_pop_pct_chng_13_19) %>%
  relocate(`County Type`, pop_chng_13_19, pop_chng_19_25, 
           pop_pct_chng_13_19, pop_pct_chng_19_25, pop_pct_chng_diff_6yr,
           avg_pop_pct_chng_13_19, avg_pop_pct_chng_19_25, avg_annual_pop_pct_chng_diff)

write.csv(pop_by_typology,
          file.path(path_output, "Urban-Rural Population 2010-2025.csv"),
          row.names = FALSE)
write.csv(pop_by_typology %>% select(`County Type`, pop_pct_chng_13_19, pop_pct_chng_19_25),
          file.path(path_output, "Urban-Rural Pop 6-Year Change 2010-2025.csv"),
          row.names = FALSE)

###### Headline figure, same as the NYT article ######
# Index to 2010 = 100
pop_by_typology_idx <- cty_pop_with_typology %>%
  group_by(locale_type) %>%
  summarise(across(starts_with("pop_estimate"), ~sum(.))) %>%
  ungroup() %>%
  rename_with(~c("County Type", 2010:2025)) %>%
  pivot_longer(cols = -`County Type`, names_to = "Year", values_to = "pop") %>%
  pivot_wider(names_from = `County Type`, values_from = "pop") %>%
  mutate(across(-Year, ~./first(.) * 100))

write.csv(pop_by_typology_idx,
          file.path(path_output, "Growth of Urban-Rural Population 2010-2025.csv"),
          row.names = FALSE)

###### Extra data supplied to NYT journalist, did not make the final cut for our piece ######
mig_by_typology <- cty_mig_with_typology %>%
  group_by(locale_type) %>%
  summarise(across(starts_with("net_migration"), ~sum(.))) %>%
  ungroup() %>% 
  rename_with(~c("County Type", 2010:2025)) %>%
  mutate(net_mig_10_14 = `2010` + `2011` + `2012` + `2013` + `2014`,
         net_mig_15_19 = `2015` + `2016` + `2017` + `2018` + `2019`,
         net_mig_21_25 = `2021` + `2022` + `2023` + `2024` + `2025`) %>%
  relocate(`County Type`, net_mig_10_14, net_mig_15_19, net_mig_21_25)

write.csv(mig_by_typology,
          file.path(path_output, "Urban-Rural Net Migration 2010-2025.csv"),
          row.names = FALSE)

int_mig_by_typology <- cty_mig_with_typology %>%
  group_by(locale_type) %>%
  summarise(across(starts_with("pop_estimate"), ~sum(.)),
            across(starts_with("international_migration"), ~sum(.))) %>%
  ungroup()
int_mig_by_typology <- int_mig_by_typology %>%
  bind_cols(
    map_dfc(2010:2025, ~ tibble(
      !!paste0("international_mig_rate_", .x) :=
        100 * int_mig_by_typology[[paste0("international_migration_", .x)]] /
        int_mig_by_typology[[paste0("pop_estimate_", .x)]]
    ))
  ) %>%
  select(locale_type, starts_with("international_mig_rate_")) %>%
  rename_with(~c("County Type", 2010:2025)) %>%
  mutate(avg_int_mig_rate_10_14 = (`2010` + `2011` + `2012` + `2013` + `2014`)/5,
         avg_int_mig_rate_15_19 = (`2015` + `2016` + `2017` + `2018` + `2019`)/5,
         avg_int_mig_rate_21_25 = (`2021` + `2022` + `2023` + `2024` + `2025`)/5) %>%
  relocate(`County Type`, avg_int_mig_rate_10_14, avg_int_mig_rate_15_19, avg_int_mig_rate_21_25)

write.csv(int_mig_by_typology %>% select(`County Type`, `2015`, `2016`, `2017`, `2018`, `2019`,
                                         `2021`, `2022`, `2023`, `2024`, `2025`),
          file.path(path_output, "Urban-Rural INTERNATIONAL Migration Rates 2015-2025.csv"),
          row.names = FALSE)

dom_mig_by_typology <- cty_mig_with_typology %>%
  group_by(locale_type) %>%
  summarise(across(starts_with("domestic_migration"), ~sum(.))) %>%
  ungroup() %>% 
  rename_with(~c("County Type", 2010:2025)) %>%
  mutate(dom_mig_10_14 = `2010` + `2011` + `2012` + `2013` + `2014`,
         dom_mig_15_19 = `2015` + `2016` + `2017` + `2018` + `2019`,
         dom_mig_21_25 = `2021` + `2022` + `2023` + `2024` + `2025`) %>%
  relocate(`County Type`, dom_mig_10_14, dom_mig_15_19, dom_mig_21_25)

write.csv(dom_mig_by_typology,
          file.path(path_output, "Urban-Rural DOMESTIC Migration 2010-2025.csv"),
          row.names = FALSE)

###### Figure 2, rural metro vs non-metro population growth ######
pop_by_rural_metro <- cty_pop_with_typology %>%
  filter(locale_type == "Rural") %>%
  group_by(is_metro) %>%
  summarise(across(starts_with("pop_estimate"), ~sum(.))) %>%
  ungroup() %>%
  rename_with(~c("County Type", 2010:2025)) %>%
  pivot_longer(cols = -`County Type`, names_to = "Year", values_to = "pop") %>%
  pivot_wider(names_from = `County Type`, values_from = "pop") %>%
  left_join(pop_by_typology_idx %>% select(Year, rural_all_idx = Rural), by = "Year") %>%
  mutate(metro_idx = metro/first(metro) * 100,
         non_metro_idx = non_metro/first(non_metro) * 100,
         metro_deriv = metro_idx - lag(metro_idx),
         non_metro_deriv = non_metro_idx - lag(non_metro_idx))

write.csv(pop_by_rural_metro,
          file.path(path_output, "Growth of Rural Population by Metro Status 2010-2025.csv"),
          row.names = FALSE)

###### Figure 3, rural metro vs non-metro population growth by age band ######
# 1) Population by broad age band, 2010 to 2025
agesex_bands_under25 <- c("AGE04", "AGE59", "AGE1014", "AGE1519", "AGE2024")
agesex_bands_25_54   <- c("AGE2529", "AGE3034", "AGE3539", "AGE4044", "AGE4549", "AGE5054")
agesex_bands_55plus  <- c("AGE5559", "AGE6064", "AGE6569", "AGE7074", "AGE7579",
                          "AGE8084", "AGE85PLUS")
agesex_columns <- paste0(c(agesex_bands_under25, agesex_bands_25_54, agesex_bands_55plus), "_TOT")

county_agesex_2020 <- fread(
  file.path(path_raw, "cc-est2020int-agesex-all.csv"),
  select = c("SUMLEV", "STATE", "COUNTY", "YEAR", agesex_columns),
  showProgress = FALSE
) %>%
  as_tibble() %>%
  filter(SUMLEV == 50L, YEAR %in% 2:11) %>%
  mutate(county_fips = paste0(str_pad(STATE, 2, "left", "0"),
                              str_pad(COUNTY, 3, "left", "0")),
         estimate_year = 2008 + YEAR) %>%
  select(county_fips, estimate_year, all_of(agesex_columns))

county_agesex_2025 <- fread(
  file.path(path_raw, "cc-est2025-agesex-all.csv"),
  select = c("SUMLEV", "STATE", "COUNTY", "YEAR", agesex_columns),
  showProgress = FALSE
) %>%
  as_tibble() %>%
  filter(SUMLEV == 50L, YEAR %in% 2:7) %>%
  mutate(county_fips = paste0(str_pad(STATE, 2, "left", "0"),
                              str_pad(COUNTY, 3, "left", "0")),
         estimate_year = 2018 + YEAR) %>%
  select(county_fips, estimate_year, all_of(agesex_columns))

# 2) Crosswalk the 2010-2019 age detail onto the current county vintage, using the same
#    apportionment applied earlier to total population and migration: a retired county's
#    counts are split across its successors in proportion to their share of its 2020 Census
#    population. Only Connecticut actually moves - its eight legacy counties become nine
#    planning regions - but the step is run over every county so nothing is special-cased.
county_agesex_2020_current <- county_agesex_2020 %>%
  # many-to-many is expected and correct here: the left side has one row per county-year and
  # the crosswalk has one row per old-to-new county pair, so a split CT county fans out across
  # its successor planning regions in every year.
  inner_join(county_crosswalk_all, by = c("county_fips" = "county_fips_old"),
             relationship = "many-to-many") %>%
  group_by(county_fips = county_fips_new, estimate_year) %>%
  summarise(across(all_of(agesex_columns), \(x) sum(x * weight)), .groups = "drop")

# Conservation check: apportionment redistributes counts between counties but must not
# create or destroy any, so every national age-column total has to survive unchanged.
agesex_crosswalk_check <- tibble(
  age_column = agesex_columns,
  before = map_dbl(agesex_columns, \(v) sum(county_agesex_2020[[v]])),
  after  = map_dbl(agesex_columns, \(v) sum(county_agesex_2020_current[[v]]))
) %>%
  mutate(abs_diff = abs(after - before))

if (any(agesex_crosswalk_check$abs_diff > 1e-6)) {
  stop("Age-detail crosswalk changed the national total for: ",
       paste(agesex_crosswalk_check$age_column[agesex_crosswalk_check$abs_diff > 1e-6],
             collapse = ", "))
}
if (!setequal(county_agesex_2020_current$county_fips, county_agesex_2025$county_fips)) {
  stop("Crosswalked 2010-2019 age detail does not share a county set with the 2020-2025 file")
}

message("Age detail crosswalked: ", n_distinct(county_agesex_2020_current$county_fips),
        " counties, all ", length(agesex_columns), " age columns conserved nationally")

# 3) Stitch the two vintages into one 2010-2025 series. There is no overlap to resolve: the
#    intercensal file supplies July 1 estimates for 2010-2019 and the Vintage 2025 file
#    supplies 2020-2025. Both are anchored to the 2020 Census - the intercensal series is
#    constrained to it at its end point and the postcensal series is built forward from it -
#    so the 2019/2020 seam is far smoother than the Vintage 2020 postcensal series used
#    earlier in this script. It is still a seam between two estimate vintages, and the
#    2019-2025 comparison below crosses it while the 2013-2019 comparison does not.
county_agesex_10_25 <- bind_rows(county_agesex_2020_current, county_agesex_2025) %>%
  arrange(county_fips, estimate_year)

if (nrow(county_agesex_10_25) !=
    n_distinct(county_agesex_10_25$county_fips) * 16L) {
  stop("Expected 16 years for every county after stitching; got ",
       nrow(county_agesex_10_25), " rows for ",
       n_distinct(county_agesex_10_25$county_fips), " counties")
}

# 4) Collapse the eighteen five-year groups into the three analysis bands. Bands are summed
#    from counts, so they partition the population exactly.
county_agesex_bands_10_25 <- county_agesex_10_25 %>%
  transmute(county_fips, estimate_year,
            pop_under_25 = rowSums(across(all_of(paste0(agesex_bands_under25, "_TOT")))),
            pop_25_54    = rowSums(across(all_of(paste0(agesex_bands_25_54, "_TOT")))),
            pop_55_plus  = rowSums(across(all_of(paste0(agesex_bands_55plus, "_TOT")))),
            pop_all_ages = pop_under_25 + pop_25_54 + pop_55_plus)

agesex_seam_check <- county_agesex_bands_10_25 %>%
  filter(estimate_year %in% 2018:2021) %>%
  group_by(estimate_year) %>%
  summarise(pop_all_ages = sum(pop_all_ages), .groups = "drop") %>%
  mutate(yoy_pct = (pop_all_ages / lag(pop_all_ages) - 1) * 100)

message("National totals across the 2019/2020 seam: ",
        paste(sprintf("%d %.2fm", agesex_seam_check$estimate_year,
                      agesex_seam_check$pop_all_ages / 1e6), collapse = ", "),
        " (year-on-year change at the seam ",
        sprintf("%+.2f%%", agesex_seam_check$yoy_pct[
          agesex_seam_check$estimate_year == 2020]), ")")

### Actual data for Figure 3 datawrapper ###
#    Growth by age band for rural counties, split by metro status. 2013-2019 sits wholly
#    inside the intercensal series; 2019-2025 crosses the vintage seam described above.
rural_agesex_growth <- county_agesex_bands_10_25 %>%
  inner_join(county_locale_type, by = "county_fips") %>%
  filter(locale_type == "Rural", estimate_year %in% c(2013L, 2019L, 2025L)) %>%
  group_by(is_metro, estimate_year) %>%
  summarise(across(starts_with("pop_"), sum), .groups = "drop") %>%
  pivot_longer(starts_with("pop_"), names_to = "age_band", values_to = "population") %>%
  pivot_wider(names_from = estimate_year, values_from = population, names_prefix = "pop_") %>%
  mutate(age_band = factor(age_band,
                           levels = c("pop_under_25", "pop_25_54", "pop_55_plus", "pop_all_ages"),
                           labels = c("Under 25", "25 to 54", "55 and over", "All ages")),
         change_13_19     = pop_2019 - pop_2013,
         change_19_25     = pop_2025 - pop_2019,
         pct_change_13_19 = (pop_2019 / pop_2013 - 1) * 100,
         pct_change_19_25 = (pop_2025 / pop_2019 - 1) * 100) %>%
  arrange(is_metro, age_band)

write.csv(rural_agesex_growth %>%
            select(is_metro, age_band, pct_change_13_19, pct_change_19_25),
          file.path(path_output, "Rural Population Growth by Age Band and Metro Status.csv"),
          row.names = FALSE)

### Check rural metro/non-metro against other locale types ###
locale_agesex_growth <- county_agesex_bands_10_25 %>%
  inner_join(county_locale_type, by = "county_fips") %>%
  filter(estimate_year %in% c(2013L, 2019L, 2025L)) %>%
  group_by(locale_type, is_metro, estimate_year) %>%
  summarise(across(starts_with("pop_"), sum), .groups = "drop") %>%
  pivot_longer(starts_with("pop_"), names_to = "age_band", values_to = "population") %>%
  pivot_wider(names_from = estimate_year, values_from = population, names_prefix = "pop_") %>%
  mutate(pct_change_13_19 = (pop_2019 / pop_2013 - 1) * 100,
         pct_change_19_25 = (pop_2025 / pop_2019 - 1) * 100)

locale_agesex_growth %>%
  group_by(age_band) %>%
  summarise(pop_2019 = sum(pop_2019),
            pop_2025 = sum(pop_2025)) %>%
  ungroup() %>%
  mutate(pct_change_19_25 = (pop_2025 / pop_2019 - 1) * 100)

write.csv(locale_agesex_growth,
          file.path(path_output, "Population Growth by Age Band, Locale Type and Metro Status.csv"),
          row.names = FALSE)

message("Rural population growth by age band written for metro and non-metro rural counties (",
        sum(county_locale_type$locale_type == "Rural" &
              county_locale_type$is_metro == "metro"), " metro rural, ",
        sum(county_locale_type$locale_type == "Rural" &
              county_locale_type$is_metro == "non_metro"), " non-metro rural)")

###### Rural metro vs non-metro migration ######
net_mig_rural_metro <- cty_mig_with_typology %>%
  filter(locale_type == "Rural") %>%
  group_by(is_metro) %>%
  summarise(across(starts_with("net_migration"), ~sum(.))) %>%
  ungroup() %>% 
  rename_with(~c("is_metro", 2010:2025)) %>%
  mutate(net_mig_10_14 = `2010` + `2011` + `2012` + `2013` + `2014`,
         net_mig_15_19 = `2015` + `2016` + `2017` + `2018` + `2019`,
         net_mig_21_25 = `2021` + `2022` + `2023` + `2024` + `2025`) %>%
  relocate(`is_metro`, net_mig_10_14, net_mig_15_19, net_mig_21_25)

dom_mig_rural_metro <- cty_mig_with_typology %>%
  filter(locale_type == "Rural") %>%
  group_by(is_metro) %>%
  summarise(across(starts_with("domestic_migration"), ~sum(.))) %>%
  ungroup() %>% 
  rename_with(~c("is_metro", 2010:2025)) %>%
  mutate(dom_mig_10_14 = `2010` + `2011` + `2012` + `2013` + `2014`,
         dom_mig_15_19 = `2015` + `2016` + `2017` + `2018` + `2019`,
         dom_mig_21_25 = `2021` + `2022` + `2023` + `2024` + `2025`) %>%
  relocate(`is_metro`, dom_mig_10_14, dom_mig_15_19, dom_mig_21_25)

int_mig_rural_metro <- cty_mig_with_typology %>%
  filter(locale_type == "Rural") %>%
  group_by(is_metro) %>%
  summarise(across(starts_with("pop_estimate"), ~sum(.)),
            across(starts_with("international_migration"), ~sum(.))) %>%
  ungroup() %>%
  mutate(int_mig_10_14 = `international_migration_2010` + `international_migration_2011` + `international_migration_2012` + `international_migration_2013` + `international_migration_2014`,
         int_mig_15_19 = `international_migration_2015` + `international_migration_2016` + `international_migration_2017` + `international_migration_2018` + `international_migration_2019`,
         int_mig_21_25 = `international_migration_2021` + `international_migration_2022` + `international_migration_2023` + `international_migration_2024` + `international_migration_2025`) %>%
  relocate(`is_metro`, int_mig_10_14, int_mig_15_19, int_mig_21_25)

net_mig_rural_metro %>% select(1:4)
int_mig_rural_metro %>% select(1:4)

int_mig_rural_metro <- int_mig_rural_metro %>%
  bind_cols(
    map_dfc(2010:2025, ~ tibble(
      !!paste0("international_mig_rate_", .x) :=
        100 * int_mig_rural_metro[[paste0("international_migration_", .x)]] /
        int_mig_rural_metro[[paste0("pop_estimate_", .x)]]
    ))
  ) %>%
  select(is_metro, starts_with("international_mig_rate_")) %>%
  rename_with(~c("is_metro", 2010:2025)) %>%
  pivot_longer(cols = -is_metro, names_to = "year", values_to = "international_mig_rate") %>%
  pivot_wider(names_from = is_metro, values_from = international_mig_rate) %>%
  filter(year != 2020)

write.csv(int_mig_rural_metro,
          file.path(path_output, "Rural metro vs non-metro international migration rate.csv"),
          row.names = FALSE)

###### International migration counterfactual: what if immigration stayed at 2021-2024 levels in 2025 ######
int_mig_counterfactual <- cty_mig_with_typology %>%
  mutate(pop_chng_24_25 = pop_estimate_2025 - pop_estimate_2024,
         avg_int_mig_22_24 = round((international_migration_2022 + international_migration_2023 + international_migration_2024)/3, 0),
         int_mig_rate_2024 = international_migration_2024/pop_estimate_2024,
         int_mig_rate_2025 = international_migration_2025/pop_estimate_2025) %>%
  filter(pop_chng_24_25 < 0) %>%
  select(1:5, pop_chng_24_25, avg_int_mig_22_24,
         pop_estimate_2024, international_migration_2024, int_mig_rate_2024,
         pop_estimate_2025, international_migration_2025, int_mig_rate_2025) %>%
  mutate(pop_counter_2025 = pop_estimate_2025 + avg_int_mig_22_24 - international_migration_2025,
         cty_wouldve_grown = pop_counter_2025 > pop_estimate_2024)

cty_mig_with_typology %>%
  mutate(pop_chng_24_25 = pop_estimate_2025 - pop_estimate_2024,
         pop_decline_24_25 = pop_chng_24_25 < 0) %>%
  group_by(pop_decline_24_25) %>%
  summarise(count = n(),
            pop_estimate_2024 = sum(pop_estimate_2024),
            pop_estimate_2025 = sum(pop_estimate_2025),
            pop_chng_24_25 = sum(pop_chng_24_25)) %>%
  ungroup() %>%
  mutate(pop_pct_chng_24_25 = pop_chng_24_25/pop_estimate_2024,
         pop_share_24 = pop_estimate_2024/sum(pop_estimate_2024))

int_mig_counter_sum <- int_mig_counterfactual %>%
  group_by(locale_type) %>%
  summarise(count = n(),
            count_wouldve_grown = sum(cty_wouldve_grown),
            pop_estimate_2024 = sum(pop_estimate_2024),
            pop_estimate_2025 = sum(pop_estimate_2025),
            actual_pop_chng = pop_estimate_2025/pop_estimate_2024 - 1,
            pop_counter_2025 = sum(pop_counter_2025),
            counterfactual_pop_chng = pop_counter_2025/pop_estimate_2024 - 1) %>%
  ungroup()

###### County migration map broken down by age ######
county_agesex_19_25 <- county_agesex_bands_10_25 %>%
  filter(estimate_year %in% c(2019, 2025)) %>%
  pivot_longer(cols = -c(county_fips, estimate_year), names_to = "age_band", values_to = "population") %>%
  pivot_wider(names_from = estimate_year, values_from = population, names_prefix = "pop_") %>%
  filter(age_band != "pop_all_ages") %>%
  mutate(age_band = ifelse(age_band %in% c("pop_under_25", "pop_25_54"),
                           "under_55", "over_55")) %>%
  group_by(county_fips, age_band) %>%
  summarise(pop_2019 = sum(pop_2019),
            pop_2025 = sum(pop_2025)) %>%
  ungroup() %>%
  pivot_wider(names_from = age_band, values_from = c(pop_2019, pop_2025),
              names_glue  = "{.value}_{age_band}") %>%
  mutate(lvl_chng_19_25_under55 = pop_2025_under_55 - pop_2019_under_55,
         lvl_chng_19_25_over55 = pop_2025_over_55 - pop_2019_over_55,
         lvl_chng_19_25_all = lvl_chng_19_25_under55 + lvl_chng_19_25_over55,
         over55_chng_ratio = lvl_chng_19_25_over55/lvl_chng_19_25_all)

# 3) Migration level over the same window, from the panel already built in this script.
county_migration_level <- cty_mig_with_typology %>%
  filter(locale_type == "Rural") %>%
  select(county_fips, starts_with("net_migration")) %>%
  left_join(cty_pop_with_typology %>% select(county_fips, pop_estimate_2019, pop_estimate_2025), by = "county_fips") %>% # Use intercensal as basis
  transmute(county_fips, pop_estimate_2019, pop_estimate_2025,
            pop_pct_chng_19_25 = (pop_estimate_2025/pop_estimate_2019 - 1) * 100,
            net_migration_19_25 = net_migration_2019 + net_migration_2021 + net_migration_2022 + # Skip 2020
              net_migration_2023 + net_migration_2024 + net_migration_2025,
            net_migration_rate_19_25 = net_migration_19_25 / pop_estimate_2019 * 100)

nat_rural_mig_rate <- sum(county_migration_level$net_migration_19_25)/sum(county_migration_level$pop_estimate_2019) * 100

rural_growth_inputs <- county_agesex_19_25 %>%
  left_join(county_migration_level, by = "county_fips") %>%
  filter(!is.na(pop_estimate_2019))

if (anyNA(rural_growth_inputs)) {
  stop("Missing values in rural_growth_inputs for ",
       sum(!complete.cases(rural_growth_inputs)), " counties")
}
message("Rural counties entering the typology: ", nrow(rural_growth_inputs))

### Tier 1: identify rural counties with positive population gain and above-average net migration ###
rural_growth_inputs <- rural_growth_inputs %>%
  mutate(level_group = case_when(
    pop_pct_chng_19_25 > 0 & net_migration_rate_19_25 > nat_rural_mig_rate ~ 2,
    TRUE ~ 1
  ))

message("Tier 1 split: ", sum(rural_growth_inputs$level_group == 1L),
        " low-migration and ", sum(rural_growth_inputs$level_group == 2L), " high-migration counties")

### Tier 2: split high-migration into quartiles by over 55 to under 55 ratio ###
rural_high_migration <- rural_growth_inputs %>%
  filter(level_group == 2) %>%
  mutate(migration_quart = ntile(over55_chng_ratio, 4),
         migration_group = case_when(
           migration_quart == 1  ~ "Highly working-age-skewed",
           migration_quart == 2  ~ "Slightly working-age-skewed",
           migration_quart == 3  ~ "Slightly elderly-skewed",
           migration_quart == 4  ~ "Highly elderly-skewed")) %>%
  select(-migration_quart)

rural_growth_typology <- bind_rows(
  rural_growth_inputs %>% filter(level_group == 1) %>% mutate(migration_group = "Low migration"),
  rural_high_migration) %>%
  arrange(county_fips) %>%
  left_join(cty_pop_with_typology %>% select(c(1:2,4:6)), by = "county_fips") %>%
  left_join(fips_codes %>% distinct(state_name, state) %>% rename(state_abb = state), by = "state_name") %>%
  mutate(county_name_full = paste(str_trim(str_remove_all(county_name, "County|Parish|Census Area|Municipality|Borough|City and Borough")), state_abb)) %>%
  relocate(county_fips, county_name, county_name_full, state_fips, state_abb, state_name, migration_group, is_metro)

rural_mig_grp_sum <- rural_growth_typology %>%
  group_by(migration_group) %>%
  summarise(count = n(),
            pop_2019_under_55 = sum(pop_2019_under_55),
            pop_2019_over_55 = sum(pop_2019_over_55),
            pop_estimate_2019 = sum(pop_estimate_2019),
            
            pop_2025_under_55 = sum(pop_2025_under_55),
            pop_2025_over_55 = sum(pop_2025_over_55),
            pop_estimate_2025 = sum(pop_estimate_2025),
            
            net_migration_19_25 = sum(net_migration_19_25)) %>%
  ungroup() %>%
  mutate(lvl_chng_19_25_under55 = pop_2025_under_55 - pop_2019_under_55,
         lvl_chng_19_25_over55 = pop_2025_over_55 - pop_2019_over_55,
         lvl_chng_19_25_all = lvl_chng_19_25_under55 + lvl_chng_19_25_over55,
         over55_chng_ratio = lvl_chng_19_25_over55/lvl_chng_19_25_all,
         
         pop_growth_19_25_under55 = lvl_chng_19_25_under55/pop_2019_under_55 * 100,
         pop_growth_19_25_all = (pop_estimate_2025/pop_estimate_2019 - 1) * 100,
         net_migration_rate_19_25 = net_migration_19_25/pop_estimate_2019 * 100) %>%
  arrange(over55_chng_ratio)

write.csv(rural_growth_typology,
          file.path(path_output, "Rural Growth Typology by County.csv"),
          row.names = FALSE)

rural_metro_typo_sum <- rural_growth_typology %>%
  group_by(is_metro) %>%
  summarise(count = n(),
            pop_2019_under_55 = sum(pop_2019_under_55),
            pop_2019_over_55 = sum(pop_2019_over_55),
            pop_estimate_2019 = sum(pop_estimate_2019),
            
            pop_2025_under_55 = sum(pop_2025_under_55),
            pop_2025_over_55 = sum(pop_2025_over_55),
            pop_estimate_2025 = sum(pop_estimate_2025),
            
            net_migration_19_25 = sum(net_migration_19_25)) %>%
  ungroup() %>%
  mutate(lvl_chng_19_25_under55 = pop_2025_under_55 - pop_2019_under_55,
         lvl_chng_19_25_over55 = pop_2025_over_55 - pop_2019_over_55,
         lvl_chng_19_25_all = lvl_chng_19_25_under55 + lvl_chng_19_25_over55,
         over55_chng_ratio = lvl_chng_19_25_over55/lvl_chng_19_25_all,
         
         pop_growth_19_25_under55 = lvl_chng_19_25_under55/pop_2019_under_55 * 100,
         pop_growth_19_25_all = (pop_estimate_2025/pop_estimate_2019 - 1) * 100,
         net_migration_rate_19_25 = net_migration_19_25/pop_estimate_2019 * 100)

###### State-to-state migration flows based on ACS ######
acs_ddi <- read_ipums_ddi(file.path(path_raw, "usa_00105.xml"))

acs_micro <- read_ipums_micro(
  acs_ddi,
  vars = c("YEAR", "HHWT", "STATEFIP", "PUMA", "AGE", "EDUC", "EDUCD", "SCHOOL", "EMPSTAT",
           "OCCSOC", "INDNAICS", "INCWAGE", "MIGRATE1", "MIGRATE1D"),
  verbose = FALSE
) |>
  mutate(across(c(YEAR, STATEFIP, PUMA, AGE, EDUC, EDUCD, SCHOOL, EMPSTAT, INCWAGE,
                  MIGRATE1, MIGRATE1D), as.integer),
         # OCCSOC is "0" for householders with no occupation on record, mostly those out of
         # the labour force; the leading two digits are the SOC major group otherwise.
         occ_soc_major = if_else(OCCSOC == "0", NA_character_, substr(OCCSOC, 1, 2)),
         ind_naics_major = ifelse(INDNAICS == "0", NA_character_, substr(INDNAICS, 1, 2))) |>
  select(-c(OCCSOC, INDNAICS))

message("ACS microdata loaded: ", format(nrow(acs_micro), big.mark = ","),
        " householder records across ", n_distinct(acs_micro$YEAR), " samples (",
        min(acs_micro$YEAR), "-", max(acs_micro$YEAR), ", no 2020)")

# 1) Household interstate migration rate. Numerator is householders who moved between
#    states in the past year; denominator is all householders with a valid migration
#    status, which includes those living abroad a year ago since they are householders now
#    but are not interstate movers.
acs_hh_interstate_rate <- acs_micro |>
  filter(MIGRATE1 %in% 1:4) |>
  group_by(year = YEAR) |>
  summarise(households        = sum(HHWT),
            interstate_movers = sum(HHWT[MIGRATE1 == 3]),
            within_state_movers = sum(HHWT[MIGRATE1 == 2]),
            from_abroad       = sum(HHWT[MIGRATE1 == 4]),
            n_records         = n(),
            .groups = "drop") |>
  mutate(interstate_rate   = interstate_movers / households * 100,
         within_state_rate = within_state_movers / households * 100)

# 2) Verify the weights and the universe before using the rate.
acs_weight_check <- acs_micro |>
  group_by(year = YEAR) |>
  summarise(households = sum(HHWT), .groups = "drop")

if (any(acs_weight_check$households < 100e6 | acs_weight_check$households > 145e6)) {
  stop("Weighted household counts fall outside the plausible 100-145 million range; ",
       "check that the implied decimals on HHWT were applied")
}
if (nrow(acs_hh_interstate_rate) != 19L) {
  stop("Expected 19 ACS samples, got ", nrow(acs_hh_interstate_rate))
}

message("Household interstate migration rate: ",
        sprintf("%.2f%%", acs_hh_interstate_rate$interstate_rate[1]), " in 2005, ",
        sprintf("%.2f%%", acs_hh_interstate_rate$interstate_rate[
          acs_hh_interstate_rate$year == 2010]), " in 2010, ",
        sprintf("%.2f%%", acs_hh_interstate_rate$interstate_rate[
          acs_hh_interstate_rate$year == 2022]), " in 2022, ",
        sprintf("%.2f%%", tail(acs_hh_interstate_rate$interstate_rate, 1)), " in 2024")

write.csv(acs_hh_interstate_rate,
          file.path(path_output, "Household Interstate Migration Rate 2005-2024.csv"),
          row.names = FALSE)
