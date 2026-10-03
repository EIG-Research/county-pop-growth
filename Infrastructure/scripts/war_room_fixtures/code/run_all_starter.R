# run_all.R -- baseline pipeline orchestrator
# Author - *Insert Human Author Here*
# research title -
# research question -

rm(list = ls())
options(scipen = 999)
set.seed(42)

################################################################################
###                           1. Select scripts                              ###
################################################################################

# 1) Toggle numbered scripts with explicit TRUE/FALSE flags
run_01_build_dataset_flag <- FALSE
run_02_analysis_flag <- FALSE
run_03_make_figures_flag <- FALSE

# 2) Map each flag to one script; list order determines execution order
script_flags <- list(
  "01_build_dataset.R" = run_01_build_dataset_flag,
  "02_analysis.R" = run_02_analysis_flag,
  "03_make_figures.R" = run_03_make_figures_flag
)

scripts_to_run <- names(script_flags)[
  vapply(script_flags, isTRUE, logical(1L))
]

################################################################################
###                           2. Load packages                               ###
################################################################################

# 3) Declare packages required by the selected analysis scripts
required_packages <- c(
  # "tidyverse",
  # "fixest"
)

# 4) Verify and attach each required package
for (package_name in required_packages) {
  if (!requireNamespace(package_name, quietly = TRUE)) {
    stop(
      paste0(
        "Missing package: ", package_name,
        ". Please install it before running the pipeline."
      ),
      call. = FALSE
    )
  }

  library(package_name, character.only = TRUE)
}

################################################################################
###                              3. Set paths                                ###
################################################################################

# 5) Resolve the project root without a hard-coded, user-specific path
# Prefer here::here(), which works from any subdirectory in an RStudio project or
# Git repository. Otherwise, use the working directory and require the analyst to
# run this script from the project root.
if (requireNamespace("here", quietly = TRUE)) {
  path_project <- here::here()
} else {
  path_project <- getwd()
  message(
    "Package 'here' is not installed; using the working directory as the ",
    "project root:\n  ", path_project,
    "\nRun this script from the project root, or install 'here'."
  )
}

# 6) Declare project-relative input and output paths
path_data <- file.path(path_project, "data")
path_code <- file.path(path_project, "code")
path_output <- file.path(path_project, "output")

path_raw <- file.path(path_data, "raw")
path_processed <- file.path(path_data, "processed")
path_figures <- file.path(path_output, "figures")
path_tables <- file.path(path_output, "tables")

################################################################################
###                        4. Configure run logging                          ###
################################################################################

# 7) Create a distinct log file and open one append-only connection
path_logs <- file.path(path_output, "logs")

if (!dir.exists(path_logs)) {
  dir.create(path_logs, recursive = TRUE)
}

run_stamp <- format(Sys.time(), "%Y%m%d_%H%M%S")
log_file <- file.path(path_logs, paste0("run_all_", run_stamp, ".log"))
log_connection <- file(log_file, open = "at", encoding = "UTF-8")

progress_message <- paste0(
  "[", format(Sys.time(), "%Y-%m-%d %H:%M:%S"), "] Starting run_all.R"
)
message(progress_message)
writeLines(progress_message, con = log_connection)

progress_message <- paste0(
  "[", format(Sys.time(), "%Y-%m-%d %H:%M:%S"), "] Project path: ",
  path_project
)
message(progress_message)
writeLines(progress_message, con = log_connection)
flush(log_connection)

################################################################################
###                            5. Run scripts                                ###
################################################################################

# 8) Source each selected script in a fresh environment and stop on fatal errors
tryCatch(
  {
    if (length(scripts_to_run) == 0L) {
      progress_message <- paste0(
        "[", format(Sys.time(), "%Y-%m-%d %H:%M:%S"),
        "] No scripts selected; all flags are FALSE."
      )
      message(progress_message)
      writeLines(progress_message, con = log_connection)
      flush(log_connection)
    } else {
      for (script_name in scripts_to_run) {
        script_path <- file.path(path_code, script_name)

        if (!file.exists(script_path)) {
          stop(
            paste0("Selected script not found: ", script_path),
            call. = FALSE
          )
        }

        progress_message <- paste0(
          "[", format(Sys.time(), "%Y-%m-%d %H:%M:%S"), "] Running: ",
          script_name
        )
        message(progress_message)
        writeLines(progress_message, con = log_connection)
        flush(log_connection)

        script_start <- Sys.time()

        source(
          script_path,
          local = new.env(parent = globalenv())
        )

        elapsed_seconds_num <- round(
          as.numeric(
            difftime(Sys.time(), script_start, units = "secs")
          ),
          2L
        )

        progress_message <- paste0(
          "[", format(Sys.time(), "%Y-%m-%d %H:%M:%S"), "] Completed: ",
          script_name, " (", elapsed_seconds_num, " seconds)"
        )
        message(progress_message)
        writeLines(progress_message, con = log_connection)
        flush(log_connection)
      }
    }

    progress_message <- paste0(
      "[", format(Sys.time(), "%Y-%m-%d %H:%M:%S"), "] Finished run_all.R"
    )
    message(progress_message)
    writeLines(progress_message, con = log_connection)

    progress_message <- paste0(
      "[", format(Sys.time(), "%Y-%m-%d %H:%M:%S"), "] Log saved to: ",
      log_file
    )
    message(progress_message)
    writeLines(progress_message, con = log_connection)
    flush(log_connection)
  },
  error = function(e) {
    error_message <- paste0(
      "[", format(Sys.time(), "%Y-%m-%d %H:%M:%S"), "] ERROR: ",
      conditionMessage(e)
    )
    message(error_message)
    writeLines(error_message, con = log_connection)
    flush(log_connection)
    stop(e)
  },
  finally = {
    close(log_connection)
  }
)
