# Fixture helper: drops rows with a missing id.
clean_ids <- function(df) {
  df[!is.na(df$id), ]
}
