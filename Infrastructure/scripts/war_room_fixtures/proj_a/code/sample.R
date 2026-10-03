# Fixture script for war-room tests. Not part of any analysis pipeline.
# Synthetic: every value here is invented.

# --- Setup --------------------------------------------------------------
library(dplyr)
library(readr)

raw <- read_csv("data/raw/people.csv")

# Keep prime-age adults only.
adults <- raw %>%
  filter(age >= 25) %>%
  mutate(age_group = "prime")

# --- Helpers ------------------------------------------------------------
wage_share <- function(wages, total) {
  wages / total
}

summarise_wages <- function(df) {
  df %>%
    group_by(age_group) %>%
    summarise(mean_wage = mean(wage, na.rm = TRUE))
}

# --- Output -------------------------------------------------------------
summary_tbl <- summarise_wages(adults)

write_csv(summary_tbl, "output/tables/wages.csv")
