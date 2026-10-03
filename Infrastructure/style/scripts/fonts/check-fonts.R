#!/usr/bin/env Rscript
# check-fonts.R -- report whether the EIG headline and body fonts are installed.
#
# Uses the R theme's resolver, so it passes exactly when the theme would draw with a
# primary family (or one the tokens accept as primary, such as Source Serif 4).
#   Rscript Infrastructure/style/scripts/fonts/check-fonts.R [--allow-fallback]
# Exit codes: 0 pass, 1 fonts missing, 2 the check could not run.

args <- commandArgs(trailingOnly = TRUE)
allow_fallback <- "--allow-fallback" %in% args

# 1) Locate the style directory from this script's own path.
cmd_args <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("^--file=", cmd_args, value = TRUE)
if (length(file_arg) == 0L) {
  message("ERROR: Run this file with Rscript so its location is known.")
  quit(status = 2L)
}
script_path <- normalizePath(sub("^--file=", "", file_arg[[1L]]), mustWork = FALSE)
style_dir <- normalizePath(file.path(dirname(script_path), "..", ".."), mustWork = FALSE)
theme_path <- file.path(style_dir, "themes", "r", "eig_theme.R")
if (!file.exists(theme_path)) {
  message("ERROR: R theme not found: ", theme_path)
  quit(status = 2L)
}

# 2) Resolve each role with the theme's resolver.
source(theme_path)
tokens <- tryCatch(
  eig_load_tokens(file.path(style_dir, "themes", "r", "eig_tokens.R")),
  error = function(e) {
    message("ERROR: ", conditionMessage(e))
    quit(status = 2L)
  }
)
available <- tryCatch(
  eig_available_fonts(),
  error = function(e) {
    message("ERROR: ", conditionMessage(e))
    quit(status = 2L)
  }
)

roles <- c("headline", "body")
resolved <- lapply(roles, function(role) {
  tryCatch(
    eig_resolve_family(role, tokens = tokens, available = available, warn = FALSE),
    error = function(e) NA_character_
  )
})
names(resolved) <- roles

# 3) Report.
failed_flag <- FALSE
for (role in roles) {
  family <- resolved[[role]]
  primary <- tokens$EIG_TYPOGRAPHY[[role]]$primary_family
  if (is.na(family)) {
    message("MISSING ", role, ": no family in the token chain is installed (primary: ", primary, ")")
    failed_flag <- TRUE
  } else if (isTRUE(attr(family, "eig_primary"))) {
    message("OK ", role, ": ", family)
  } else {
    message("FALLBACK ", role, ": ", family, " (primary ", primary, " is not installed)")
    if (!allow_fallback) failed_flag <- TRUE
  }
}

if (failed_flag) {
  message("ERROR: Required EIG fonts are missing. Run an installer in Infrastructure/style/scripts/fonts/ and restart the session.")
  quit(status = 1L)
}
message("PASS: EIG fonts resolve", if (allow_fallback) " (fallbacks allowed)." else " to primary families.")
quit(status = 0L)
