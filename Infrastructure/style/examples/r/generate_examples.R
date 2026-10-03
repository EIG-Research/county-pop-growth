#!/usr/bin/env Rscript
# EIG-styled R example outputs: a base plot, a ggplot, a plotly widget, and a gt table.
#   Rscript Infrastructure/style/examples/r/generate_examples.R [out_dir]
# Outputs go to out_dir, or to a new temporary directory when it is omitted, so a run
# leaves nothing in the repository. Every color, font, and size comes from the tokens.

args <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("^--file=", args, value = TRUE)
if (length(file_arg) == 0L) {
  stop("Run this file with Rscript so its location is known.", call. = FALSE)
}
script_path <- normalizePath(sub("^--file=", "", file_arg[[1L]]), mustWork = FALSE)
style_dir <- normalizePath(file.path(dirname(script_path), "..", ".."), mustWork = FALSE)

out_args <- commandArgs(trailingOnly = TRUE)
# R deletes its own session tempdir() on exit, so the default goes in its parent.
out_dir <- if (length(out_args) > 0L) {
  out_args[[1L]]
} else {
  tempfile("eig-examples-r-", tmpdir = dirname(tempdir()))
}
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

source(file.path(style_dir, "themes", "r", "eig_theme.R"))
tokens <- eig_load_tokens(file.path(style_dir, "themes", "r", "eig_tokens.R"))
eig_assert_fonts(tokens, allow_fallback = TRUE)

# Figure text follows Infrastructure/style/docs/eig-figure-style.md: a sentence-case
# title in the image, then a note line above the source line.
title_text <- "Heavier cars get fewer miles per gallon"
note_text <- "Note: Simulated data for illustration."
source_text <- "Source: Synthetic example data."

set.seed(42)
n_obs <- 140L
weight <- pmax(pmin(rnorm(n_obs, mean = 3.1, sd = 0.65), 5.7), 1.5)
cyl <- sample(c(4, 6, 8), n_obs, replace = TRUE, prob = c(0.4, 0.35, 0.25))
mpg <- 41.5 - 5.0 * weight - 0.75 * (cyl - 4) + rnorm(n_obs, sd = 2.1)
cars_df <- data.frame(weight = weight, mpg = mpg, cyl = factor(cyl))

# Open the device first: par() with no device open would create Rplots.pdf.
png(file.path(out_dir, "base_scatter.png"), width = 1400, height = 900, res = 180)
eig_base_defaults(tokens)
par(mar = c(7, 4.5, 3, 1))
plot(
  cars_df$weight,
  cars_df$mpg,
  pch = 16,
  col = tokens$EIG_COLORS[["eig_teal_900"]],
  xlab = "Weight (thousands of pounds)",
  ylab = "Miles per gallon"
)
title(main = title_text, adj = 0)
mtext(note_text, side = 1, line = 4.5, adj = 0, cex = 0.7)
mtext(source_text, side = 1, line = 5.5, adj = 0, cex = 0.7)
invisible(dev.off())

if (requireNamespace("ggplot2", quietly = TRUE)) {
  scatter_plot <- ggplot2::ggplot(cars_df, ggplot2::aes(weight, mpg, color = cyl)) +
    ggplot2::geom_point(size = 2.1, alpha = 0.9) +
    eig_scale_color(tokens = tokens, name = "Cylinders") +
    ggplot2::labs(
      title = title_text,
      subtitle = "Miles per gallon by vehicle weight and cylinder count",
      x = "Weight (thousands of pounds)",
      y = "Miles per gallon",
      caption = paste(note_text, source_text, sep = "\n")
    ) +
    eig_theme_ggplot(tokens = tokens)

  ggplot2::ggsave(
    filename = file.path(out_dir, "ggplot_scatter.png"),
    plot = scatter_plot,
    width = tokens$EIG_FIGURE_DEFAULT_WIDTH_IN,
    height = tokens$EIG_FIGURE_DEFAULT_HEIGHT_IN,
    dpi = 220
  )
}

if (requireNamespace("plotly", quietly = TRUE) && requireNamespace("htmlwidgets", quietly = TRUE)) {
  layout_cfg <- eig_plotly_layout(tokens = tokens)
  interactive_plot <- plotly::plot_ly(
    data = cars_df,
    x = ~weight,
    y = ~mpg,
    color = ~cyl,
    colors = unname(tokens$EIG_DISCRETE),
    type = "scatter",
    mode = "markers"
  )
  interactive_plot <- plotly::layout(
    interactive_plot,
    title = title_text,
    xaxis = modifyList(layout_cfg$xaxis, list(title = "Weight (thousands of pounds)")),
    yaxis = modifyList(layout_cfg$yaxis, list(title = "Miles per gallon")),
    font = layout_cfg$font,
    paper_bgcolor = layout_cfg$paper_bgcolor,
    plot_bgcolor = layout_cfg$plot_bgcolor,
    colorway = layout_cfg$colorway,
    annotations = list(list(
      text = paste(note_text, source_text, sep = "<br>"),
      x = 0, y = -0.2, xref = "paper", yref = "paper",
      xanchor = "left", yanchor = "top", showarrow = FALSE, align = "left"
    ))
  )
  htmlwidgets::saveWidget(
    interactive_plot,
    file = file.path(out_dir, "plotly_scatter.html"),
    selfcontained = FALSE
  )
}

if (requireNamespace("gt", quietly = TRUE)) {
  summary_tbl <- aggregate(cbind(mpg, weight) ~ cyl, data = cars_df, FUN = mean)
  names(summary_tbl) <- c("Cylinders", "Mean miles per gallon", "Mean weight")
  summary_tbl[, 2:3] <- round(summary_tbl[, 2:3], 1)
  table_gt <- gt::gt(summary_tbl)
  table_gt <- gt::tab_source_note(table_gt, source_text)
  table_gt <- eig_style_gt(table_gt, tokens = tokens)
  gt::gtsave(table_gt, filename = file.path(out_dir, "gt_table.html"))
}

cat("Wrote R example outputs to:", out_dir, "\n")
