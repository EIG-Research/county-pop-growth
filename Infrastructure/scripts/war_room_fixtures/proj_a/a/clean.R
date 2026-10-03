# Fixture helper: trims whitespace from the id column.
clean_ids <- function(df) {
  df$id <- trimws(df$id)
  df
}
