

# Annual interstate migration rates, 2005-2024, from the Census Bureau state-to-state
# migration flow tables (ACS 1-year). Source files in data/raw/state migration flow.
#
# 2020 is absent by design: the Census Bureau did not release 2020 ACS 1-year estimates
# because pandemic disruption pushed response rates below publication standards. The series
# is therefore 2005-2019 plus 2021-2024, 19 years.
#
# Universe: the 50 states plus the District of Columbia. Puerto Rico is excluded. It is a
# state-equivalent column in the 2005-2009 tables but is classified under "Abroad 1 year
# ago" from 2010 on, so keeping it would break comparability across the series.
path_state_flows <- file.path(path_raw, "state migration flow")
state_geo_51 <- c(state.name, "District of Columbia")

state_flow_files <- tibble(file_name = list.files(path_state_flows, pattern = "[.]xlsx?$")) |>
  mutate(year = as.integer(str_extract(file_name, "(19|20)[0-9]{2}"))) |>
  arrange(year)

# 1) The 2005-2023 files are wide matrices in four slightly different shapes: row 7 carries
#    the geography, row 8 carries Estimate/MOE, and column 1 carries current residence. The
#    2010-2022 files interleave a repeated row-label column every 11th column while 2023
#    does not, and the 2005-2009 files have no marginal columns at all. Rather than write a
#    parser per shape, every sheet is melted to (year, row, column, cell) and stacked, so the
#    header logic below is expressed once. Identifying data columns by row 8 == "Estimate"
#    absorbs the label-column difference, because label columns are blank in row 8.
state_flow_cells <- state_flow_files |>
  filter(year < 2024) |>
  transmute(year, path = file.path(path_state_flows, file_name)) |>
  pmap(\(year, path) suppressMessages(
    read_excel(path, sheet = 1, col_names = FALSE, col_types = "text",
               .name_repair = \(nm) as.character(seq_along(nm)))) |>
      mutate(row_id = row_number()) |>
      pivot_longer(-row_id, names_to = "col_id", values_to = "cell") |>
      mutate(col_id = as.integer(col_id), year = year)) |>
  list_rbind()

# 2) Column dictionary. Geography comes from row 7 and the header group from row 6 (row 5 in
#    the 2023 file), both carried rightward because Excel leaves merged headers blank.
#    str_squish also normalises the line breaks embedded in the 2023 header labels.
state_flow_col_dict <- state_flow_cells |>
  filter(row_id %in% 5:8) |>
  pivot_wider(names_from = row_id, values_from = cell, names_prefix = "r") |>
  mutate(geo_label   = str_squish(r7),
         group_label = str_squish(coalesce(r6, r5))) |>
  arrange(year, col_id) |>
  group_by(year) |>
  fill(geo_label, group_label, .direction = "down") |>
  ungroup() |>
  filter(r8 == "Estimate") |>
  select(year, col_id, geo_label, group_label)

# 3) Attach the column dictionary and the current-residence row label to every data cell.
#    Restricting row labels to the 51 geographies drops the "United States" total row, the
#    Puerto Rico row, and the footnote rows in one step.
state_flow_labeled <- state_flow_cells |>
  inner_join(state_flow_col_dict, by = c("year", "col_id")) |>
  inner_join(state_flow_cells |>
               filter(col_id == 1, str_squish(cell) %in% state_geo_51) |>
               transmute(year, row_id, state_to = str_squish(cell)),
             by = c("year", "row_id")) |>
  mutate(value = suppressWarnings(as.numeric(cell)))

# The state-by-state flow block: a state geography in row 7, excluding the Abroad columns.
state_flows_wide <- state_flow_labeled |>
  filter(geo_label %in% state_geo_51, !str_starts(group_label, "Abroad")) |>
  transmute(year, state_from = geo_label, state_to, movers = value)

# Marginals published in the 2010-2023 files: the migration universe and the unsuppressed
# in-migration total. Both are absent from the 2005-2009 files.
state_flow_file_pop <- state_flow_labeled |>
  filter(str_starts(group_label, "Population 1 year")) |>
  transmute(year, state = state_to, file_pop_1yr_plus = value)

state_flow_published_in <- state_flow_labeled |>
  filter(geo_label == "Total", str_starts(group_label, "Different state")) |>
  transmute(year, state = state_to, in_published = value)

# 4) The 2024 file is already long, and its two supplemental sheets publish the unsuppressed
#    in- and out-migration totals plus the migration universe. Codes X (diagonal) and N
#    (insufficient sample cases) become NA on numeric coercion.
path_flows_2024 <- file.path(path_state_flows,
                             state_flow_files$file_name[state_flow_files$year == 2024])

state_flows_2024 <- suppressMessages(
  read_excel(path_flows_2024, sheet = "Table", col_names = FALSE, col_types = "text",
             skip = 8, .name_repair = \(nm) as.character(seq_along(nm)))) |>
  transmute(year       = 2024L,
            state_to   = str_squish(`1`),
            state_from = str_squish(`2`),
            movers     = suppressWarnings(as.numeric(`3`))) |>
  filter(state_to %in% state_geo_51, state_from %in% state_geo_51)

state_flow_2024_current_res <- suppressMessages(
  read_excel(path_flows_2024, sheet = "Supplemental - Current Res", col_names = FALSE,
             col_types = "text", .name_repair = \(nm) as.character(seq_along(nm)))) |>
  transmute(year              = 2024L,
            state             = str_squish(`1`),
            file_pop_1yr_plus = suppressWarnings(as.numeric(`2`)),
            in_published      = suppressWarnings(as.numeric(`8`))) |>
  filter(state %in% state_geo_51)

state_flow_2024_res_1yr_ago <- suppressMessages(
  read_excel(path_flows_2024, sheet = "Supplemental - Res 1 Year Ago", col_names = FALSE,
             col_types = "text", .name_repair = \(nm) as.character(seq_along(nm)))) |>
  transmute(year          = 2024L,
            state         = str_squish(`1`),
            out_published = suppressWarnings(as.numeric(`8`))) |>
  filter(state %in% state_geo_51)

# 5) One long flow table for all 19 years, off-diagonal only. In the 2005-2009 tables the
#    diagonal holds within-state movers rather than a blank, so dropping it is what makes
#    those years interstate-only and comparable with the rest.
state_flows <- bind_rows(state_flows_wide, state_flows_2024) |>
  filter(state_from != state_to) |>
  arrange(year, state_from, state_to)

write.csv(state_flows,
          file.path(path_processed, "state_to_state_flows_2005_2024.csv"),
          row.names = FALSE)

# 6) Denominator: ACS 1-year population 1 year and over, which is the published universe of
#    these tables. One source is used for every year because the 2005-2009 files carry no
#    denominator; step 8 confirms it reproduces the file-provided figure exactly wherever the
#    file supplies one. Cache the pull so reruns do not re-hit the API.
path_state_pop <- file.path(path_processed, "acs_pop_1yr_plus_state_2005_2024.csv")

if (file.exists(path_state_pop)) {
  message("Reading cached ACS population 1 year and over from ", basename(path_state_pop))
  state_pop_1yr_plus <- read.csv(path_state_pop)
} else {
  message("Querying ACS 1-year population 1 year and over for ",
          n_distinct(state_flows$year), " years via tidycensus")
  state_pop_1yr_plus <- sort(unique(state_flows$year)) |>
    map(\(y) suppressMessages(
      get_acs(geography = "state", variables = "B07001_001",
              year = y, survey = "acs1")) |>
        transmute(year = y, state = NAME, pop_1yr_plus = estimate)) |>
    list_rbind() |>
    filter(state %in% state_geo_51)
  
  write.csv(state_pop_1yr_plus, path_state_pop, row.names = FALSE)
}

# 7) State-year rates. In- and out-migrants come from the published marginals wherever those
#    exist and from matrix row and column sums otherwise. This matters only for 2024, the one
#    year with suppressed cells (255 of 2,550): its row sums fall 0.4 percent short
#    nationally and up to 5 percent short for small states such as New Hampshire, which would
#    read as a spurious dip. The 2005-2023 matrices have no suppressed cells, and step 8
#    confirms the two routes agree exactly wherever both are available.
#
# All four rates use current-residence population as the denominator. For the out-migration
# rate the population at risk is strictly the origin state's population a year earlier; that
# figure is published only in the 2024 supplemental sheet, so current residence is used
# throughout for comparability. The two differ by well under a percent of the denominator.
state_migration_rates <- state_pop_1yr_plus |>
  left_join(state_flows |>
              group_by(year, state = state_to) |>
              summarise(in_matrix = sum(movers, na.rm = TRUE), .groups = "drop"),
            by = c("year", "state")) |>
  left_join(state_flows |>
              group_by(year, state = state_from) |>
              summarise(out_matrix = sum(movers, na.rm = TRUE), .groups = "drop"),
            by = c("year", "state")) |>
  left_join(bind_rows(state_flow_published_in,
                      state_flow_2024_current_res |> select(year, state, in_published)),
            by = c("year", "state")) |>
  left_join(state_flow_2024_res_1yr_ago, by = c("year", "state")) |>
  mutate(in_migrants  = coalesce(in_published, in_matrix),
         out_migrants = coalesce(out_published, out_matrix),
         net_migrants   = in_migrants - out_migrants,
         gross_migrants = in_migrants + out_migrants,
         in_rate    = in_migrants / pop_1yr_plus * 100,
         out_rate   = out_migrants / pop_1yr_plus * 100,
         net_rate   = net_migrants / pop_1yr_plus * 100,
         gross_rate = gross_migrants / pop_1yr_plus * 100,
         # Reliability diagnostic, not an adjustment. In-migration is a published total
         # estimated within the destination state's own sample; out-migration is a sum of
         # 50 small cells scattered across the other states' samples, so it is far noisier
         # for small states. A ratio far from 1 sustained over years, in a state whose
         # population is flat, indicates the out-migration figure cannot be trusted.
         out_in_ratio = out_migrants / in_migrants) |>
  select(year, state, pop_1yr_plus,
         in_migrants, out_migrants, net_migrants, gross_migrants,
         in_rate, out_rate, net_rate, gross_rate, out_in_ratio) |>
  arrange(year, state)

# 8) Verify the flow table and the rates before reporting them.
if (nrow(state_migration_rates) != n_distinct(state_flows$year) * length(state_geo_51)) {
  stop("Expected ", n_distinct(state_flows$year) * length(state_geo_51),
       " state-year rows, got ", nrow(state_migration_rates))
}
if (anyNA(state_migration_rates)) {
  stop("Missing values in state_migration_rates; check the flow parse and the ACS join")
}

state_flow_pop_check <- state_pop_1yr_plus |>
  inner_join(bind_rows(state_flow_file_pop,
                       state_flow_2024_current_res |> select(year, state, file_pop_1yr_plus)),
             by = c("year", "state")) |>
  filter(pop_1yr_plus != file_pop_1yr_plus)

if (nrow(state_flow_pop_check) > 0L) {
  stop("ACS population 1 year and over disagrees with the published table value for ",
       nrow(state_flow_pop_check), " state-years")
}

# Interstate moves are a closed system across the 51 geographies, so every year's inflows
# and outflows must total the same number of movers.
state_flow_identity_check <- state_migration_rates |>
  group_by(year) |>
  summarise(total_in = sum(in_migrants), total_out = sum(out_migrants), .groups = "drop") |>
  filter(abs(total_in - total_out) > 1e-6)

if (nrow(state_flow_identity_check) > 0L) {
  stop("Interstate inflows and outflows do not balance in ",
       nrow(state_flow_identity_check), " years, including ",
       state_flow_identity_check$year[1])
}

# Where a year publishes an in-migration total, the matrix row sum must reproduce it.
state_flow_route_check <- state_pop_1yr_plus |>
  inner_join(state_flow_published_in, by = c("year", "state")) |>
  inner_join(state_flows |>
               group_by(year, state = state_to) |>
               summarise(in_matrix = sum(movers, na.rm = TRUE), .groups = "drop"),
             by = c("year", "state")) |>
  filter(in_matrix != in_published)

message("State flows parsed: ", nrow(state_flows), " off-diagonal pairs across ",
        n_distinct(state_flows$year), " years (", sum(is.na(state_flows$movers)),
        " suppressed cells, all in 2024)")
message("Rates verified: ", nrow(state_migration_rates),
        " state-years, inflows balance outflows every year, ACS denominator matches the ",
        "published universe for all ", nrow(state_flow_file_pop) +
          nrow(state_flow_2024_current_res), " state-years that publish one")
message("Published-vs-matrix in-migration totals disagree in ",
        nrow(state_flow_route_check), " of ",
        nrow(state_flow_published_in), " unsuppressed state-years")

# Known data problem, reported rather than corrected: Alaska's out-migration in the
# 2005-2014 tables is not credible. It averages 92,000 a year over 2010-2014 against
# 35,000 in-migrants, implying a net loss near 7 to 9 percent of the state's population
# every year while Alaska's measured population was flat (725,193 in 2013, 725,206 in
# 2014). It falls to 41,000 from 2015 on with no corresponding real-world event, and the
# pre-2015 destination mix is implausible: Florida, New York and Michigan lead 2013 while
# Washington, the usual leading destination, does not appear in the top eight, whereas
# 2016 onward puts Washington first. The parse is faithful to the files -- N/A sits on the
# matrix diagonal in 51 of 51 rows in every year, and column sums reproduce each file's
# own United States row exactly -- so this originates upstream in the published tables.
# Alaska's in-migration, the national totals and every other state are unaffected: the
# national rate moves smoothly across the 2014/2015 break (2.33 to 2.37 percent).
# Treat Alaska's out-migration, net migration and gross migration before 2015 as unusable.
#
# Large out/in ratios elsewhere in the series are real events, not errors, and are left
# alone: Louisiana in 2005-2006 (Hurricane Katrina), New York in 2005 (sustained net
# domestic out-migration), Maine in 2021 (pandemic in-migration).
state_flow_ratio_check <- state_migration_rates |>
  filter(out_in_ratio < 0.5 | out_in_ratio > 2) |>
  arrange(desc(out_in_ratio))

write.csv(state_flow_ratio_check,
          file.path(path_output, "State Interstate Migration Rate Diagnostics.csv"),
          row.names = FALSE)

message("Out/in ratio outside [0.5, 2] in ", nrow(state_flow_ratio_check),
        " of ", nrow(state_migration_rates), " state-years, covering ",
        paste(sort(unique(state_flow_ratio_check$state)), collapse = ", "),
        " -- see the diagnostics table")

# 9) National annual rate. This is the weighted total (all interstate movers over the whole
#    population 1 year and over), not the mean of the state rates. The unweighted mean of
#    state in-rates is carried alongside for reference and runs roughly 0.6 to 0.9 points
#    higher, because small states turn over a larger share of their population.
national_migration_rate <- state_migration_rates |>
  group_by(year) |>
  summarise(interstate_movers = sum(in_migrants),
            pop_1yr_plus      = sum(pop_1yr_plus),
            unweighted_mean_state_in_rate = mean(in_rate),
            mean_abs_net_rate = mean(abs(net_rate)),
            .groups = "drop") |>
  mutate(national_rate = interstate_movers / pop_1yr_plus * 100) |>
  relocate(year, interstate_movers, pop_1yr_plus, national_rate)

saveRDS(state_migration_rates,
        file.path(path_processed, "state_interstate_migration_rates_2005_2024.rds"))
write.csv(state_migration_rates,
          file.path(path_processed, "state_interstate_migration_rates_2005_2024.csv"),
          row.names = FALSE)

write.csv(state_migration_rates,
          file.path(path_output, "State Interstate Migration Rates 2005-2024.csv"),
          row.names = FALSE)
write.csv(national_migration_rate,
          file.path(path_output, "National Interstate Migration Rate 2005-2024.csv"),
          row.names = FALSE)

message("National interstate migration rate: ",
        sprintf("%.2f%%", national_migration_rate$national_rate[1]), " in ",
        national_migration_rate$year[1], " to ",
        sprintf("%.2f%%", tail(national_migration_rate$national_rate, 1)), " in ",
        tail(national_migration_rate$year, 1))

### K-mean clustering based decomposition of county migration by age ###
# Classify rural counties by the kind of growth they had between 2021 and 2025, using county
# population change by age (cc-est2025-agesex-all.csv, YEAR 3 = 7/1/2021 to YEAR 7 =
# 7/1/2025) for the age profile and the net migration series already built in
# cty_mig_with_typology for the level. Method follows the geodemographic classification
# lineage (Vickers & Rees 2007; Gale et al. 2016); see
# Infrastructure/plans/2026-09-11_rural-migration-kmeans-typology.md.
#
# THE CENTRAL PROBLEM: raw age-specific population change is NOT migration. Over a four-year
# window a cohort ages into the next band regardless of whether anyone moves. Nationally
# between 2021 and 2025 the 75-79 population grew 26.4% and the 55-59 population FELL 6.5%,
# purely because the large 1946-50 birth cohort was passing through. Taken raw, the
# fastest-growing age band is 75-plus in 82% of all US counties - that would classify four
# counties in five as "over-55 growth" while measuring nothing but the boomer wave.
#
# The fix is to measure each county's growth in each band against the NATIONAL growth of that
# same band. The common cohort-aging component cancels, and what remains is the county's own
# deviation, which is dominated by migration. That this works is checkable rather than
# assumed: excess growth correlates 0.76 (under 35), 0.64 (35-54) and 0.68 (55-plus) with the
# independently estimated net migration rate over the same window.
set.seed(42)


# ACS rural migration by county age growth pattern
acp_data <- read_xlsx(file.path(path_raw, "American communities project dataset.xlsx")) %>%
  rename(county_fips = Fips, acp_typology = `2023 Typology`) %>%
  mutate(county_fips = str_pad(county_fips, 5, "left", "0"))

rural_growth_typology_ers <- rural_growth_typology %>%
  mutate(High_Recreation_2025 = ifelse(High_Recreation_2025 == 1, 1, 0),
         Retirement_Destination_2025 = ifelse(Retirement_Destination_2025 == 1, 1, 0),
         Persistent_Poverty_1721 = ifelse(Persistent_Poverty_1721 == 1, 1, 0)) %>%
  group_by(migration_group) %>%
  summarise(count = n(),
            metro_count = sum(Metro2023),
            High_Recreation_2025 = sum(High_Recreation_2025),
            Retirement_Destination_2025 = sum(Retirement_Destination_2025),
            Persistent_Poverty_1721 = sum(Persistent_Poverty_1721))

########################################## Scrapyard below ##########################################

# 6) Diagnostics for the shape tier, reported rather than used to pick k silently.
growth_cluster_diagnostics <- map(2:6, \(k) {
  km <- kmeans(growth_shape[high_migration_rows, ], centers = k, nstart = 500, iter.max = 300)
  tibble(k = k,
         within_pct = km$tot.withinss / km$totss * 100,
         silhouette = mean(silhouette(km$cluster,
                                      dist(growth_shape[high_migration_rows, ]))[, 3]),
         smallest_cluster = min(km$size))
}) |>
  list_rbind()

write.csv(growth_cluster_diagnostics,
          file.path(path_output, "Rural Growth Cluster Diagnostics.csv"), row.names = FALSE)
cohort_contamination_r2 <- summary(lm(excess_pop_55_plus ~ ageing_in_ratio,
                                      data = rural_growth_inputs))$r.squared
migration_explained_r2 <- summary(lm(excess_pop_55_plus ~ net_migration_rate_21_25,
                                     data = rural_growth_inputs))$r.squared
message("Cohort-ageing contamination of the 55-plus band: baseline age structure explains ",
        sprintf("%.1f%%", cohort_contamination_r2 * 100),
        " of excess-growth variance against ",
        sprintf("%.1f%%", migration_explained_r2 * 100),
        " for the net migration rate. Migration dominates, but the 55-plus category is not ",
        "pure migration. A 2020-2025 window would be cohort-exact; tested, it moves excess ",
        "growth by almost nothing (correlation 0.95-0.97 across the three bands) because the ",
        "three analysis bands are broad.")

# 7) Tier 2 - shape, within the high-migration branch (Vickers & Rees recursive k-means).
shape_fit <- kmeans(growth_shape[high_migration_rows, ], centers = 3,
                    nstart = 2000, iter.max = 500)

# Labels are assigned geometrically, not by a threshold. In row-centred space a profile with
# no dominant band sits near the ORIGIN, so the flattest cluster is the one with the smallest
# centroid norm - not the smallest spread. The remaining three are named by which band peaks.
shape_centroid_labels <- as_tibble(shape_fit$centers) |>
  mutate(shape_group = row_number(),
         centroid_norm = sqrt(rowSums(across(all_of(excess_columns))^2))) |>
  mutate(shape_label = c("under 35", "35 to 54", "55 plus")[apply(across(all_of(excess_columns)), 1, which.max)])

rural_growth_inputs$shape_group <- NA_integer_
rural_growth_inputs$shape_group[high_migration_rows] <- shape_fit$cluster

rural_growth_typology <- rural_growth_inputs |>
  left_join(shape_centroid_labels |> select(shape_group, shape_label), by = "shape_group") |>
  mutate(growth_category = case_when(
    level_group == 1L                     ~ "1 Low migration",
    shape_label == "under 35"             ~ "2 High migration, primarily under-35 growth",
    shape_label == "35 to 54"             ~ "3 High migration, primarily 35-54 growth",
    shape_label == "55 plus"              ~ "4 High migration, primarily over-55 growth"))

if (anyNA(rural_growth_typology$growth_category)) {
  stop("Unclassified counties: ", sum(is.na(rural_growth_typology$growth_category)))
}

# 8) Stability of the shape tier across fresh seeds (Hennig 2007 motivation).
growth_shape_stability <- map_dbl(1:10, \(i) {
  a <- kmeans(growth_shape[high_migration_rows, ], centers = 3, nstart = 2000,
              iter.max = 500)$cluster
  b <- kmeans(growth_shape[high_migration_rows, ], centers = 3, nstart = 2000,
              iter.max = 500)$cluster
  tab <- table(a, b)
  pair_sum <- sum(choose(tab, 2)); row_sum <- sum(choose(rowSums(tab), 2))
  col_sum  <- sum(choose(colSums(tab), 2)); total <- choose(length(a), 2)
  (pair_sum - row_sum * col_sum / total) /
    ((row_sum + col_sum) / 2 - row_sum * col_sum / total)
})

category_sizes <- count(rural_growth_typology, growth_category)
size_floor <- nrow(rural_growth_typology) / nrow(category_sizes) * 0.5
message("Shape-tier stability: median adjusted Rand ",
        sprintf("%.3f", median(growth_shape_stability)),
        " | category sizes ", paste(category_sizes$n, collapse = ", "),
        " | Vickers-Rees 50%-of-average floor ", round(size_floor),
        ", categories below it: ", sum(category_sizes$n < size_floor))

# 9) Profiles, external validation against the USDA retirement flag reconstructed earlier in
#    this script, and outputs.
rural_growth_profiles <- rural_growth_typology |>
  group_by(growth_category) |>
  summarise(counties = n(),
            mean_net_migration_rate = mean(net_migration_rate_21_25),
            across(all_of(excess_columns), \(x) mean(x)),
            .groups = "drop") |>
  mutate(share_of_rural = counties / sum(counties) * 100)

rural_growth_validation <- rural_growth_typology |>
  inner_join(readRDS(file.path(path_processed, "retirement_destination_criteria.rds")) |>
               select(county_fips = fips, retirement_destination_alt_flag, share_65plus_2020,
                      share_65plus_change_pp),
             by = "county_fips") |>
  group_by(growth_category) |>
  summarise(counties = n(),
            pct_ers_retirement = mean(retirement_destination_alt_flag == 1) * 100,
            median_65plus_share = median(share_65plus_2020),
            median_65plus_change_pp = median(share_65plus_change_pp),
            .groups = "drop")

write.csv(rural_growth_profiles,
          file.path(path_output, "Rural Growth Typology Profiles.csv"), row.names = FALSE)
write.csv(rural_growth_validation,
          file.path(path_output, "Rural Growth Typology Validation.csv"), row.names = FALSE)

message("Rural growth typology written for ", nrow(rural_growth_typology),
        " counties across ", nrow(category_sizes), " categories")



###### ACS 1-year microdata migration flows ######
# IPUMS USA extract usa_00105: ACS 1-year samples for 2005-2019 and 2021-2024. 2020 is
# absent because the Census Bureau released no 2020 ACS 1-year estimates.
#
# The extract is already restricted to householders in non-group-quarters households
# (every record has RELATE = 01, PERNUM = 1, GQTYPE = 0), so the universe throughout this
# section is householders and every characteristic below is a householder characteristic.
#
# HHWT is used rather than PERWT. The two differ for householders (correlation 0.987), and
# HHWT is the household weight, which matches the household-level "share of householders"
# construction. Weights carry two implied decimals; ipumsr applies them from the DDI.
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

saveRDS(acs_hh_interstate_rate,
        file.path(path_processed, "acs_household_interstate_rate_2005_2024.rds"))
arrow::write_parquet(acs_hh_interstate_rate,
                     file.path(path_processed, "acs_household_interstate_rate_2005_2024.parquet"),
                     compression = "snappy")
write.csv(acs_hh_interstate_rate,
          file.path(path_output, "Household Interstate Migration Rate 2005-2024.csv"),
          row.names = FALSE)

# 3) PUMA rural share. PUMAs do not nest inside counties, so rurality is fractional: a
#    PUMA's rural share is the share of its population living in counties the EIG typology
#    calls Rural. Geocorr allocation factors sum to 1 within every PUMA. PUMA vintages
#    break exactly where the crosswalk files do: 2012 PUMAs cover ACS 2012-2021 and 2022
#    PUMAs cover 2022-2024, which is all this comparison needs. The 2000-vintage file is
#    the only one still on legacy county codes, so the county crosswalk built earlier in
#    this script is not required here.
county_rural_flag <- county_locale_type |>
  transmute(county = county_fips, rural_flag = locale_type == "Rural")

geocorr_names_12 <- names(read_csv(file.path(path_crosswalk, "puma12_cty_cbsa_st.csv"),
                                   n_max = 0, show_col_types = FALSE))
geocorr_names_20 <- names(read_csv(file.path(path_crosswalk, "puma20_cty_cbsa_st.csv"),
                                   n_max = 0, show_col_types = FALSE))

# Geocorr writes a second descriptive header row, so real data starts after row 2.
puma_county_2012 <- read_csv(file.path(path_crosswalk, "puma12_cty_cbsa_st.csv"),
                             skip = 2, col_names = geocorr_names_12,
                             col_types = cols(.default = "c")) |>
  transmute(puma_vintage = "2012",
            state  = str_pad(state, 2, "left", "0"),
            puma   = str_pad(puma12, 5, "left", "0"),
            county = str_pad(county, 5, "left", "0"),
            afact  = as.numeric(afact))

puma_county_2022 <- read_csv(file.path(path_crosswalk, "puma20_cty_cbsa_st.csv"),
                             skip = 2, col_names = geocorr_names_20,
                             col_types = cols(.default = "c")) |>
  transmute(puma_vintage = "2022",
            state  = str_pad(state, 2, "left", "0"),
            puma   = str_pad(puma22, 5, "left", "0"),
            county = str_pad(county, 5, "left", "0"),
            afact  = as.numeric(afact))

puma_rural_share <- bind_rows(puma_county_2012, puma_county_2022) |>
  left_join(county_rural_flag, by = "county") |>
  group_by(puma_vintage, state, puma) |>
  summarise(rural_share = sum(afact[rural_flag]),
            afact_total = sum(afact),
            .groups = "drop")

if (any(is.na(puma_rural_share$rural_share))) {
  stop("Some PUMAs have no rural share; a crosswalk county is missing from ",
       "county_locale_type")
}
if (any(abs(puma_rural_share$afact_total - 1) > 0.01)) {
  stop("Geocorr allocation factors do not sum to 1 for ",
       sum(abs(puma_rural_share$afact_total - 1) > 0.01), " PUMAs")
}

write.csv(puma_rural_share, file.path(path_processed, "puma_rural_share.csv"),
          row.names = FALSE)

message("PUMA rural share built for ", nrow(puma_rural_share), " PUMAs across two vintages (",
        sum(puma_rural_share$rural_share > 0.999), " fully rural, ",
        sum(puma_rural_share$rural_share < 0.001), " with no rural population)")

# 5) Rural in-migrants, 2016-2019 against 2021-2024. A non-local move is MIGRATE1D 24, 31
#    or 32: between PUMAs within a state, or between states. The ACS codes migration detail
#    at PUMA level, not county level (codes 21 and 22 never appear), so a county-to-county
#    move inside a single PUMA cannot be separated from a local move and is excluded.
#    Each householder contributes HHWT * rural_share to the rural totals, which allocates by
#    population share rather than assigning whole households to rural or non-rural.
pcepi <- read.csv(file.path(path_raw, "PCEPI.csv"))
pce_adj <- pcepi %>%
  mutate(year = as.numeric(substr(observation_date, 1, 4))) %>%
  filter(year %in% c(2016:2019, 2021:2024)) %>%
  mutate(adj_factor = DPCERG3A086NBEA/last(DPCERG3A086NBEA)) %>%
  select(year, adj_factor)

acs_rural_periods <- acs_micro |>
  filter(YEAR %in% c(2016:2019, 2021:2024)) |>
  mutate(puma_vintage = if_else(YEAR >= 2022, "2022", "2012"),
         period = if_else(YEAR >= 2021, "2021-2024", "2016-2019"),
         state  = str_pad(STATEFIP, 2, "left", "0"),
         puma   = str_pad(PUMA, 5, "left", "0")) |>
  inner_join(puma_rural_share |> select(puma_vintage, state, puma, rural_share),
             by = c("puma_vintage", "state", "puma")) |>
  left_join(pce_adj, by = join_by("YEAR" == "year")) %>%
  mutate(rural_weight  = HHWT * rural_share,
         in_migrant_flag = MIGRATE1D %in% c(24L, 31L, 32L),
         age_band = case_when(AGE < 25 ~ "Under 25",
                              AGE < 35 ~ "25 to 34",
                              AGE < 45 ~ "35 to 44",
                              AGE < 55 ~ "45 to 54",
                              AGE < 65 ~ "55 to 64",
                              TRUE ~ "65 and over"),
         education = case_when(EDUCD < 101 ~ "less than BA",
                               EDUCD == 101 ~ "bachelors",
                               EDUCD == 114 ~ "masters",
                               EDUCD == 115 ~ "professional",
                               EDUCD == 116 ~ "doctorate"),
         bachelors_plus_flag = EDUCD >= 101,
         graduate_flag       = EDUCD >= 114,
         employed_flag       = EMPSTAT == 1L,
         # INCWAGE uses 999999 for not applicable; 0 is a genuine absence of wage income.
         wage_nominal = if_else(INCWAGE >= 999999L, NA_integer_, INCWAGE),
         wage_real = wage_nominal/adj_factor) %>%
  select(-adj_factor)

if (nrow(acs_rural_periods) != sum(acs_micro$YEAR %in% c(2016:2019, 2021:2024))) {
  stop("Some householder records did not match a PUMA in the crosswalk; ",
       "check the PUMA vintage assignment")
}

# The same-period rural population that did not move supplies the benchmark for reading
# "more educated" and "higher paid" against who already lives in rural counties.
acs_rural_groups <- acs_rural_periods |>
  filter(rural_weight > 0) |>
  mutate(group = if_else(in_migrant_flag, "Rural in-migrants", "Rural non-movers"))

# 6) Occupation mix of employed rural in-migrants, by SOC major group.
rural_occupation_mix <- acs_rural_groups |>
  filter(employed_flag, !is.na(occ_soc_major)) |>
  group_by(period, group, occ_soc_major) |>
  summarise(households = sum(rural_weight), .groups = "drop_last") |>
  mutate(share = households / sum(households) * 100) |>
  ungroup() |>
  mutate(occupation = case_when(
    occ_soc_major == "11" ~ "Management",
    occ_soc_major == "13" ~ "Business and financial",
    occ_soc_major == "15" ~ "Computer and mathematical",
    occ_soc_major == "17" ~ "Architecture and engineering",
    occ_soc_major == "19" ~ "Life, physical and social science",
    occ_soc_major == "21" ~ "Community and social service",
    occ_soc_major == "23" ~ "Legal",
    occ_soc_major == "25" ~ "Education, training and library",
    occ_soc_major == "27" ~ "Arts, design, entertainment and media",
    occ_soc_major == "29" ~ "Healthcare practitioners",
    occ_soc_major == "31" ~ "Healthcare support",
    occ_soc_major == "33" ~ "Protective service",
    occ_soc_major == "35" ~ "Food preparation and serving",
    occ_soc_major == "37" ~ "Building and grounds maintenance",
    occ_soc_major == "39" ~ "Personal care and service",
    occ_soc_major == "41" ~ "Sales",
    occ_soc_major == "43" ~ "Office and administrative support",
    occ_soc_major == "45" ~ "Farming, fishing and forestry",
    occ_soc_major == "47" ~ "Construction and extraction",
    occ_soc_major == "49" ~ "Installation, maintenance and repair",
    occ_soc_major == "51" ~ "Production",
    occ_soc_major == "53" ~ "Transportation and material moving",
    occ_soc_major == "55" ~ "Military",
    TRUE ~ paste("SOC", occ_soc_major))) |>
  arrange(group, occupation, period)

write.csv(rural_occupation_mix,
          file.path(path_output, "Rural In-Migrant Occupation Mix 2016-2019 vs 2021-2024.csv"),
          row.names = FALSE)

message("Rural in-migrant households per year: ",
        sprintf("%.0f", rural_demographics$households[
          rural_demographics$period == "2016-2019" &
            rural_demographics$group == "Rural in-migrants"] / 4), " in 2016-2019 and ",
        sprintf("%.0f", rural_demographics$households[
          rural_demographics$period == "2021-2024" &
            rural_demographics$group == "Rural in-migrants"] / 4), " in 2021-2024")


rural_demographics <- acs_rural_groups |>
  group_by(period, group) |>
  summarise(households      = sum(rural_weight),
            n_records       = n(),
            mean_age        = sum(AGE * rural_weight) / sum(rural_weight),
            share_under_25  = sum(rural_weight[age_band == "Under 25"]) / sum(rural_weight) * 100,
            share_25_34     = sum(rural_weight[age_band == "25 to 34"]) / sum(rural_weight) * 100,
            share_35_44     = sum(rural_weight[age_band == "35 to 44"]) / sum(rural_weight) * 100,
            share_45_54     = sum(rural_weight[age_band == "45 to 54"]) / sum(rural_weight) * 100,
            share_55_64     = sum(rural_weight[age_band == "55 to 64"]) / sum(rural_weight) * 100,
            share_65_plus   = sum(rural_weight[age_band == "65 and over"]) / sum(rural_weight) * 100,
            share_bachelors_plus = sum(rural_weight[bachelors_plus_flag]) / sum(rural_weight) * 100,
            share_graduate  = sum(rural_weight[graduate_flag]) / sum(rural_weight) * 100,
            share_employed  = sum(rural_weight[employed_flag]) / sum(rural_weight) * 100,
            share_no_wage   = sum(rural_weight[!is.na(wage_nominal) & wage_nominal == 0]) /
              sum(rural_weight[!is.na(wage_nominal)]) * 100,
            .groups = "drop")

rural_age_wage <- acs_rural_groups %>%
  filter(period == "2021-2024", employed_flag == 1, wage_real > 0) %>%
  group_by(AGE) %>%
  summarise(households      = sum(rural_weight),
            n_records       = n(),
            real_mean_pay_age_adj   = weighted.mean(wage_real, rural_weight),
            real_median_pay_age_adj = weighted.median(wage_real, rural_weight)) %>%
  ungroup()

rural_migrant_wkr <- acs_rural_groups %>%
  filter(employed_flag == 1, wage_real > 0) %>%
  group_by(period, group) %>%
  summarise(households      = sum(rural_weight),
            n_records       = n(),
            mean_age        = weighted.mean(AGE, rural_weight),
            median_age      = weighted.median(AGE, rural_weight),
            share_bachelors_plus = sum(rural_weight[bachelors_plus_flag]) / sum(rural_weight) * 100,
            share_graduate  = sum(rural_weight[graduate_flag]) / sum(rural_weight) * 100,
            real_mean_pay   = weighted.mean(wage_real, rural_weight, na.rm = TRUE),
            real_median_pay = weighted.median(wage_real, rural_weight, na.rm = TRUE)) %>%
  ungroup() %>%
  
  group_by(group) %>%
  mutate(real_mean_pay_growth         = (real_mean_pay / real_mean_pay[period == "2016-2019"] - 1) * 100,
         real_median_pay_growth       = (real_median_pay / real_median_pay[period == "2016-2019"] - 1) * 100) %>%
  ungroup() %>%
  
  left_join(rural_age_wage %>% select(AGE, real_mean_pay_age_adj, real_median_pay_age_adj),
            by = join_by("median_age" == "AGE")) %>%
  group_by(period) %>%
  mutate(real_mean_pay_age_adj        = real_mean_pay_age_adj / real_mean_pay_age_adj[group == "Rural non-movers"],
         real_median_pay_age_adj      = real_median_pay_age_adj / real_median_pay_age_adj[group == "Rural non-movers"],
         age_adjusted_real_mean_pay   = real_mean_pay / real_mean_pay_age_adj,
         age_adjusted_real_median_pay = real_median_pay / real_median_pay_age_adj) %>%
  ungroup()

rural_demo_export_datawrapper <- rural_demographics %>%
  select(period, group, share_bachelors_plus, share_employed) %>%
  group_by(group) %>%
  mutate(ba_share_growth = share_bachelors_plus - share_bachelors_plus[period == "2016-2019"],
         epop_growth = share_employed - share_employed[period == "2016-2019"]) %>%
  ungroup() %>%
  left_join(rural_migrant_wkr %>% select(period, group, median_worker_age = median_age,
                                         real_median_pay, real_median_pay_growth),
            by = c("period", "group"))

write.csv(rural_demo_export_datawrapper,
          file.path(path_output, "Rural migrant edu emp wage profile.csv"),
          row.names = FALSE)


state_division_xwalk <- read_xls(file.path(path_raw, "state-geocodes-v2016.xls"), skip = 5)
pop_by_rural_metro_region <- cty_pop_with_typology %>%
  left_join(state_division_xwalk %>% select(state_fips = `State (FIPS)`, Region),
            by = "state_fips") %>%
  mutate(census_region = case_when(Region == 1 ~ "Northeast",
                                   Region == 2 ~ "Midwest",
                                   Region == 3 ~ "South",
                                   Region == 4 ~ "West"),
         is_metro = ifelse(is_metro == 1, "Metro", "Non-Metro"),
         region_metro = paste(census_region, is_metro)) %>%
  filter(locale_type == "Rural") %>%
  group_by(region_metro) %>%
  summarise(across(starts_with("pop_estimate"), ~sum(.))) %>%
  ungroup() %>%
  rename_with(~c("region_metro", 2010:2025)) %>%
  pivot_longer(cols = -region_metro, names_to = "Year", values_to = "pop") %>%
  pivot_wider(names_from = region_metro, values_from = "pop") %>%
  mutate(across(-Year, ~./first(.) * 100))

pop_by_rural_metro_division <- cty_pop_with_typology %>%
  left_join(state_division_xwalk %>% select(state_fips = `State (FIPS)`, Region, Division),
            by = "state_fips") %>%
  filter(locale_type == "Rural", Region == 3) %>%
  mutate(census_division = case_when(Division == 5 ~ "South Atlantic",
                                     Division == 6 ~ "East South Central",
                                     Division == 7 ~ "West South Central"),
         is_metro = ifelse(is_metro == 1, "Metro", "Non-Metro"),
         division_metro = paste(census_division, is_metro)) %>%
  group_by(division_metro) %>%
  summarise(across(starts_with("pop_estimate"), ~sum(.))) %>%
  ungroup() %>%
  rename_with(~c("division_metro", 2010:2025)) %>%
  pivot_longer(cols = -division_metro, names_to = "Year", values_to = "pop") %>%
  pivot_wider(names_from = division_metro, values_from = "pop") %>%
  mutate(across(-Year, ~./first(.) * 100))




# Merge in USDA ERS County Typology
ers_cty_typology <- read_xlsx(file.path(path_raw, "erscountytypology2025edition.xlsx"),
                              sheet = "2025 ERS County Typology Codes")
ers_cty_typo_old <- read_xls(file.path(path_raw, "erscountytypology2015edition.xls"),
                             sheet = "Typology 2015 Update",
                             skip = 3)
rural_mig_types <- cty_pop_with_typology %>%
  select(1:5, pop_estimate_2010, pop_estimate_2013, pop_estimate_2019, pop_estimate_2025) %>%
  mutate(pop_pct_chng_13_19 = pop_estimate_2019/pop_estimate_2013 - 1,
         pop_pct_chng_19_25 = pop_estimate_2025/pop_estimate_2019 - 1,
         pop_grew_category = case_when(
           pop_pct_chng_13_19 <= 0 & pop_pct_chng_19_25 <= 0 ~ "Persistent population decline",
           pop_pct_chng_13_19 <= 0 & pop_pct_chng_19_25 > 0 ~ "Population declined, but grew after 2019",
           pop_pct_chng_13_19 > 0 & pop_pct_chng_19_25 > 0 ~ "Persistent population growth",
           pop_pct_chng_13_19 > 0 & pop_pct_chng_19_25 <= 0 ~ "Population grew, but declined after 2019"
         )) %>%
  left_join(ers_cty_typology %>% select(FIPStxt, 4:17), by = join_by("county_fips" == "FIPStxt")) %>%
  left_join(ers_cty_typo_old %>% select(FIPStxt, Persistent_Poverty_2013), by = join_by("county_fips" == "FIPStxt")) %>%
  filter(locale_type == "Rural")

rural_mig_type_exports <- bind_rows(
  rural_mig_types %>%
    group_by(High_Recreation_2025) %>%
    summarise(count = n(),
              pop_estimate_2013 = sum(pop_estimate_2013),
              pop_estimate_2019 = sum(pop_estimate_2019),
              pop_estimate_2025 = sum(pop_estimate_2025)) %>%
    ungroup() %>%
    mutate(High_Recreation_2025 = ifelse(High_Recreation_2025 == 1, "High Recreation", "Low Recreation"),
           pop_pct_chng_13_19 = pop_estimate_2019/pop_estimate_2013 - 1,
           pop_pct_chng_19_25 = pop_estimate_2025/pop_estimate_2019 - 1) %>%
    rename(rural_county_type = High_Recreation_2025),
  
  rural_mig_types %>%
    group_by(High_Manufacturing_2025) %>%
    summarise(count = n(),
              pop_estimate_2013 = sum(pop_estimate_2013),
              pop_estimate_2019 = sum(pop_estimate_2019),
              pop_estimate_2025 = sum(pop_estimate_2025)) %>%
    ungroup() %>%
    mutate(High_Manufacturing_2025 = ifelse(High_Manufacturing_2025 == 1, "High Manufacturing", "Low Manufacturing"),
           pop_pct_chng_13_19 = pop_estimate_2019/pop_estimate_2013 - 1,
           pop_pct_chng_19_25 = pop_estimate_2025/pop_estimate_2019 - 1) %>%
    rename(rural_county_type = High_Manufacturing_2025),
  
  rural_mig_types %>%
    group_by(Retirement_Destination_2025) %>%
    summarise(count = n(),
              pop_estimate_2013 = sum(pop_estimate_2013),
              pop_estimate_2019 = sum(pop_estimate_2019),
              pop_estimate_2025 = sum(pop_estimate_2025)) %>%
    ungroup() %>%
    mutate(Retirement_Destination_2025 = ifelse(Retirement_Destination_2025 == 1, "Retirement Destination", "Not Retirement Destination"),
           pop_pct_chng_13_19 = pop_estimate_2019/pop_estimate_2013 - 1,
           pop_pct_chng_19_25 = pop_estimate_2025/pop_estimate_2019 - 1) %>%
    rename(rural_county_type = Retirement_Destination_2025),
  
  rural_mig_types %>%
    mutate(Persistent_Poverty_2013 = case_when(Persistent_Poverty_2013 == 1 |
                                                 (is.na(Persistent_Poverty_2013) & Persistent_Poverty_1721 == 1) ~ 1,
                                               TRUE ~ 0)) %>%
    group_by(Persistent_Poverty_2013) %>%
    summarise(count = n(),
              pop_estimate_2013 = sum(pop_estimate_2013),
              pop_estimate_2019 = sum(pop_estimate_2019),
              pop_estimate_2025 = sum(pop_estimate_2025)) %>%
    ungroup() %>%
    mutate(Persistent_Poverty_2013 = ifelse(Persistent_Poverty_2013 == 1, "Persistent Poverty", "Not Persistent Poverty"),
           pop_pct_chng_13_19 = pop_estimate_2019/pop_estimate_2013 - 1,
           pop_pct_chng_19_25 = pop_estimate_2025/pop_estimate_2019 - 1) %>%
    rename(rural_county_type = Persistent_Poverty_2013)
)

persist_pov_datawrapper <- rural_mig_types %>%
  mutate(Persistent_Poverty_1721 = ifelse(Persistent_Poverty_1721 == 1, 1, 0)) %>%
  group_by(Persistent_Poverty_1721) %>%
  summarise(count = n(),
            pop_estimate_2013 = sum(pop_estimate_2013),
            pop_estimate_2019 = sum(pop_estimate_2019),
            pop_estimate_2025 = sum(pop_estimate_2025)) %>%
  ungroup() %>%
  mutate(Persistent_Poverty_1721 = ifelse(Persistent_Poverty_1721 == 1, "Persistent Poverty", "Not Persistent Poverty"),
         pop_pct_chng_13_19 = (pop_estimate_2019/pop_estimate_2013 - 1) * 100,
         pop_pct_chng_19_25 = (pop_estimate_2025/pop_estimate_2019 - 1) * 100)

write.csv(persist_pov_datawrapper,
          file.path(path_output, "Rural persistent poverty population change.csv"),
          row.names = FALSE)

persist_pov_turnaround <- rural_mig_types %>%
  mutate(Persistent_Poverty_2013 = case_when(Persistent_Poverty_2013 == 1 |
                                               (is.na(Persistent_Poverty_2013) & Persistent_Poverty_1721 == 1) ~ 1,
                                             TRUE ~ 0),
         Persistent_Poverty_1721 = ifelse(Persistent_Poverty_1721 == 1, 1, 0)) %>%
  group_by(Persistent_Poverty_2013, Persistent_Poverty_1721) %>%
  summarise(count = n(),
            pop_estimate_2013 = sum(pop_estimate_2013),
            pop_estimate_2019 = sum(pop_estimate_2019),
            pop_estimate_2025 = sum(pop_estimate_2025)) %>%
  ungroup() %>%
  mutate(pop_pct_chng_13_19 = (pop_estimate_2019/pop_estimate_2013 - 1) * 100,
         pop_pct_chng_19_25 = (pop_estimate_2025/pop_estimate_2019 - 1) * 100)

persist_pov_turn_example <- rural_mig_types %>%
  mutate(Persistent_Poverty_2013 = case_when(Persistent_Poverty_2013 == 1 |
                                               (is.na(Persistent_Poverty_2013) & Persistent_Poverty_1721 == 1) ~ 1,
                                             TRUE ~ 0),
         Persistent_Poverty_1721 = ifelse(Persistent_Poverty_1721 == 1, 1, 0)) %>%
  filter(Persistent_Poverty_2013 == 1, Persistent_Poverty_1721 == 0) %>%
  mutate(pop_pct_chng_13_19 = (pop_estimate_2019/pop_estimate_2013 - 1) * 100,
         pop_pct_chng_19_25 = (pop_estimate_2025/pop_estimate_2019 - 1) * 100)

###### Verify USDA retirement county definition ######
# USDA defines retirement destination counties as counties whose number of residents ages 55 to 74 increased by at least 15 percent
# from 2010 to 2020 because of migration, based on data from the University of Wisconsin - Madison's Applied Population Laboratory.
# 0 = no; 1 = yes; 99 = not available

# 1) University of Wisconsin Applied Population Lab net migration, 2010-2020 (July 2024
#    release). Variables are named [measure][decade][sex][race][hispanic][age]: m1ttt55 is
#    net migrants over the 2010s for the total population aged 55-59 in 2020, e1ttt55 the
#    matching expected 2020 population, which is the 2010 cohort carried forward on life
#    table survival rates. The expected population is the denominator ERS's "increased by
#    15 percent because of migration" is measured against.
#
#    This download stops at ages 75-79; the published series runs to 85-plus. Ages 55-74
#    are complete, so the reconstruction is unaffected, but the comparison cohort below is
#    deliberately capped at 54 rather than "all other ages" so that it is fully observed.
uw_net_mig <- read.csv(
  file.path(path_raw, "netmigration_1788533405114", "netmigration_1788533405114.csv"),
  colClasses = c(fips = "character")
) |>
  filter(str_sub(fips, 3, 5) != "000")   # drop the state-total rows

# Ages 55-74 in 2020 is the ERS criterion cohort. Ages 0-54 is the comparison cohort: it is
# fully observed in this download and excludes the retirement-adjacent 75-79 group, so the
# test is genuinely "did people who are not near retirement move in too?"
uw_ages_5574  <- c(55, 60, 65, 70)
uw_ages_und55 <- seq(0, 50, 5)
uw_ages_2554  <- seq(25, 50, 5)

uw_retirement_rates <- uw_net_mig |>
  transmute(fips,
            uw_area_name = name,
            net_5574  = rowSums(across(all_of(paste0("m1ttt", uw_ages_5574)))),
            exp_5574  = rowSums(across(all_of(paste0("e1ttt", uw_ages_5574)))),
            net_und55 = rowSums(across(all_of(paste0("m1ttt", uw_ages_und55)))),
            exp_und55 = rowSums(across(all_of(paste0("e1ttt", uw_ages_und55)))),
            net_2554  = rowSums(across(all_of(paste0("m1ttt", uw_ages_2554)))),
            exp_2554  = rowSums(across(all_of(paste0("e1ttt", uw_ages_2554)))),
            mig_rate_5574  = net_5574 / exp_5574 * 100,
            mig_rate_und55 = net_und55 / exp_und55 * 100,
            mig_rate_2554  = net_2554 / exp_2554 * 100)

# UW publishes three Alaska areas as combinations of counties; ERS publishes the individual
# counties. Expanding the combined areas onto their constituents puts both on one geography.
ak_uw_combined_areas <- tibble(
  fips_uw  = c("02996", "02996", "02994", "02994", "02994", "02995", "02995"),
  fips_ers = c("02063", "02066", "02195", "02198", "02275", "02230", "02105"))

uw_retirement_rates <- uw_retirement_rates |>
  left_join(ak_uw_combined_areas, by = c("fips" = "fips_uw")) |>
  mutate(fips = coalesce(fips_ers, fips)) |>
  select(-fips_ers)

# 2) Reconstruct the published flag and confirm it reproduces exactly. The nine Connecticut
#    planning regions carry 99 in the ERS file precisely because the UW data is still on the
#    legacy county geography, so they are excluded from scoring.
retirement_reconstruction <- ers_cty_typology |>
  transmute(fips = FIPStxt, county_name = County_Name, state = State,
            metro_flag = as.integer(Metro2023),
            ers_flag = as.integer(Retirement_Destination_2025)) |>
  filter(ers_flag %in% 0:1) |>
  inner_join(uw_retirement_rates, by = "fips") |>
  mutate(reconstructed_flag = as.integer(mig_rate_5574 >= 15))

retirement_mismatch <- retirement_reconstruction |>
  filter(ers_flag != reconstructed_flag)

if (nrow(retirement_reconstruction) != 3143L) {
  stop("Expected 3,143 scored counties after joining ERS to the UW data, got ",
       nrow(retirement_reconstruction))
}
if (nrow(retirement_mismatch) > 0L) {
  stop("Reconstruction of Retirement_Destination_2025 disagrees with the published flag ",
       "for ", nrow(retirement_mismatch), " counties, including ",
       retirement_mismatch$county_name[1])
}

message("Retirement destination flag reconstructed exactly: ",
        nrow(retirement_reconstruction), " counties, ",
        sum(retirement_reconstruction$ers_flag), " flagged, 0 mismatches. ",
        "Formula: sum(net migrants 55-74) / sum(expected population 55-74) >= 15 percent")

# 3) Does the criterion catch counties that simply grew across every age group? Selectivity
#    is the retiree migration rate against the under-55 rate. Where the under-55 rate is
#    zero or negative the county is unambiguously retiree-selective, so the ratio is set to
#    infinity rather than being left as a negative number.
retirement_selectivity <- retirement_reconstruction |>
  mutate(selectivity_gap_pp = mig_rate_5574 - mig_rate_und55,
         selectivity_ratio  = if_else(mig_rate_und55 > 0,
                                      mig_rate_5574 / mig_rate_und55, Inf))

# Counties that actually aged are the yardstick: a retirement destination should have seen
# its 65-and-over share rise unusually fast. Intercensal age detail supplies that
# independently of the migration data the criterion is built from. YEAR 1 is the 4/1/2010
# census and YEAR 12 the 4/1/2020 census in this file.
county_age_65plus <- fread(
  file.path(path_raw, "cc-est2020int-agesex-all.csv"),
  select = c("SUMLEV", "STATE", "COUNTY", "YEAR", "POPESTIMATE", "AGE65PLUS_TOT"),
  showProgress = FALSE
) |>
  as_tibble() |>
  filter(SUMLEV == 50, YEAR %in% c(1L, 12L)) |>
  transmute(fips = paste0(str_pad(STATE, 2, "left", "0"), str_pad(COUNTY, 3, "left", "0")),
            census_year = if_else(YEAR == 1L, "2010", "2020"),
            pop = POPESTIMATE, pop_65plus = AGE65PLUS_TOT) |>
  pivot_wider(names_from = census_year, values_from = c(pop, pop_65plus)) |>
  transmute(fips,
            share_65plus_2020 = pop_65plus_2020 / pop_2020 * 100,
            share_65plus_change_pp = pop_65plus_2020 / pop_2020 * 100 -
              pop_65plus_2010 / pop_2010 * 100,
            pop_growth_10_20 = (pop_2020 / pop_2010 - 1) * 100)

retirement_selectivity <- retirement_selectivity |>
  left_join(county_age_65plus, by = "fips") |>
  left_join(county_locale_type |> transmute(fips = county_fips, locale_type), by = "fips")

if (anyNA(retirement_selectivity$share_65plus_change_pp)) {
  stop("Missing intercensal age detail for ",
       sum(is.na(retirement_selectivity$share_65plus_change_pp)), " counties")
}

national_median_65plus_change <- median(retirement_selectivity$share_65plus_change_pp)

# The counties where the criterion is doing the wrong job: retirees arrived no faster than
# everyone else, so the county qualifies on general growth rather than retiree pull.
retirement_general_growth <- retirement_selectivity |>
  filter(ers_flag == 1, selectivity_ratio < 1) |>
  arrange(selectivity_ratio) |>
  select(fips, county_name, state, metro_flag, locale_type,
         mig_rate_5574, mig_rate_und55, mig_rate_2554, selectivity_ratio,
         share_65plus_change_pp, pop_growth_10_20)

write.csv(retirement_general_growth,
          file.path(path_output, "Retirement Destination General Growth Counties.csv"),
          row.names = FALSE)

message("Of the ", sum(retirement_selectivity$ers_flag), " ERS retirement counties, ",
        nrow(retirement_general_growth), " saw under-55 migration outpace the 55-74 inflow ",
        "and ", sum(retirement_selectivity$ers_flag == 1 &
                      retirement_selectivity$selectivity_ratio < 1.25),
        " came within 25 percent of it; their median 65-plus share moved ",
        sprintf("%+.2f", median(retirement_general_growth$share_65plus_change_pp)),
        " points against ", sprintf("%+.2f", national_median_65plus_change),
        " for the median county")

# 4) Alternative criteria. Each pairs a floor on the 55-74 migration rate with a floor on
#    selectivity, scored on how well the counties it picks actually aged.
retirement_criteria_grid <- expand_grid(rate_floor  = c(10, 12, 15),
                                        ratio_floor = c(1, 1.5, 2, 2.5, 3)) |>
  rowwise() |>
  mutate(scored = list({
    selected <- retirement_selectivity |>
      filter(mig_rate_5574 >= rate_floor, selectivity_ratio >= ratio_floor)
    tibble(n_counties          = nrow(selected),
           median_rate_5574    = median(selected$mig_rate_5574),
           median_rate_und55   = median(selected$mig_rate_und55),
           median_65plus_share = median(selected$share_65plus_2020),
           median_65plus_change_pp = median(selected$share_65plus_change_pp),
           pct_aged_faster_than_median = mean(selected$share_65plus_change_pp >
                                                national_median_65plus_change) * 100,
           pct_65plus_share_fell = mean(selected$share_65plus_change_pp < 0) * 100,
           median_pop_growth   = median(selected$pop_growth_10_20),
           pct_rural           = mean(selected$locale_type == "Rural") * 100)
  })) |>
  unnest(scored) |>
  ungroup() |>
  arrange(rate_floor, ratio_floor)

write.csv(retirement_criteria_grid,
          file.path(path_output, "Retirement Destination Alternative Criteria.csv"),
          row.names = FALSE)

# The recommended alternative keeps the ERS 15 percent floor and adds a requirement that the county aged faster than national average
retirement_destination_alt <- retirement_selectivity |>
  mutate(retirement_destination_alt_flag =
           as.integer((mig_rate_5574 >= 15) & # Original USDA definition
                        (mig_rate_5574 > mig_rate_2554) & # Over 55 migration rate greater than prime age migration rate
                        (share_65plus_change_pp > national_median_65plus_change) # Aged faster than national average
           ))

write.csv(retirement_destination_alt |>
            select(fips, county_name, state, metro_flag, locale_type,
                   mig_rate_5574, mig_rate_und55, mig_rate_2554,
                   selectivity_gap_pp, selectivity_ratio,
                   share_65plus_2020, share_65plus_change_pp, pop_growth_10_20,
                   ers_flag, retirement_destination_alt_flag),
          file.path(path_output, "Retirement Destination Reconstruction and Alternative.csv"),
          row.names = FALSE)

saveRDS(retirement_destination_alt,
        file.path(path_processed, "retirement_destination_criteria.rds"))
arrow::write_parquet(retirement_destination_alt,
                     file.path(path_processed, "retirement_destination_criteria.parquet"),
                     compression = "snappy")

retirement_alt_kept <- sum(retirement_destination_alt$retirement_destination_alt_flag)
message("Alternative keeps ", retirement_alt_kept, " of ",
        sum(retirement_destination_alt$ers_flag), " counties; the share that aged faster ",
        "than the median county rises from ",
        sprintf("%.0f", mean(retirement_selectivity$share_65plus_change_pp[
          retirement_selectivity$ers_flag == 1] > national_median_65plus_change) * 100),
        " to ",
        sprintf("%.0f", mean(retirement_destination_alt$share_65plus_change_pp[
          retirement_destination_alt$retirement_destination_alt_flag == 1] >
            national_median_65plus_change) * 100), " percent")

rural_ret_datawrapper <- rural_mig_types %>%
  left_join(retirement_destination_alt %>% select(fips, retirement_destination_alt_flag),
            by = join_by("county_fips" == "fips")) %>%
  group_by(retirement_destination_alt_flag) %>%
  summarise(count = n(),
            pop_estimate_2013 = sum(pop_estimate_2013),
            pop_estimate_2019 = sum(pop_estimate_2019),
            pop_estimate_2025 = sum(pop_estimate_2025)) %>%
  ungroup() %>%
  mutate(retirement_destination_alt_flag = ifelse(retirement_destination_alt_flag == 1, "Retirement Destination", "Not Retirement Destination"),
         pop_share_2019 = pop_estimate_2019/sum(pop_estimate_2019),
         pop_chng_19_25 = pop_estimate_2025 - pop_estimate_2019,
         pop_growth_share_19_25 = pop_chng_19_25/sum(pop_chng_19_25),
         pop_pct_chng_13_19 = (pop_estimate_2019/pop_estimate_2013 - 1) * 100,
         pop_pct_chng_19_25 = pop_chng_19_25/pop_estimate_2019 * 100)

write.csv(rural_ret_datawrapper,
          file.path(path_output, "Rural retirement destination population growth.csv"),
          row.names = FALSE)

rural_ret_map <- county_locale_type %>%
  filter(locale_type == "Rural") %>%
  left_join(retirement_destination_alt %>% select(fips, retirement_destination_alt_flag),
            by = join_by("county_fips" == "fips")) %>%
  mutate(retirement_destination_alt_flag = ifelse(retirement_destination_alt_flag == 1, "Retirement Destination", "Not Retirement Destination"))

write.csv(rural_ret_map,
          file.path(path_output, "Rural retirement destination counties.csv"),
          row.names = FALSE)
