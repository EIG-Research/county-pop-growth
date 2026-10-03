# EIG plotting and table theme helpers for R.
#
# Source this file from anywhere inside the repository:
#   source("Infrastructure/style/themes/r/eig_theme.R")
#   ggplot(...) + eig_theme_ggplot()
#
# Every value comes from the generated token file themes/r/eig_tokens.R, which
# Infrastructure/style/scripts/sync_tokens.py writes from the token JSON. The file is
# found through the EIG_STYLE_DIR environment variable (the Infrastructure/style
# directory), then here::here(), then by walking up from the working directory.
#
# Fonts resolve in token order: the primary family, then the families accepted as
# primary (Source Serif 4 for Source Serif Pro), then the fallback stack. Using a
# fallback raises a warning; the theme never substitutes a font silently.

eig_style_dir <- function() {
  token_rel <- file.path("themes", "r", "eig_tokens.R")

  # 1) An explicit EIG_STYLE_DIR wins, and a wrong one is an error, not a fallthrough.
  env_dir <- Sys.getenv("EIG_STYLE_DIR", unset = "")
  if (nzchar(env_dir)) {
    if (!file.exists(file.path(env_dir, token_rel))) {
      stop(
        "EIG_STYLE_DIR is set to '", env_dir, "', but ", token_rel,
        " is not there. Point it at the repository's Infrastructure/style directory.",
        call. = FALSE
      )
    }
    return(normalizePath(env_dir))
  }

  # 2) here::here() when the here package is installed, then 3) walk up from getwd().
  candidates <- character(0L)
  if (requireNamespace("here", quietly = TRUE)) {
    candidates <- c(candidates, here::here("Infrastructure", "style"))
  }
  current_dir <- normalizePath(getwd(), mustWork = FALSE)
  repeat {
    candidates <- c(candidates, file.path(current_dir, "Infrastructure", "style"), current_dir)
    parent_dir <- dirname(current_dir)
    if (identical(parent_dir, current_dir)) break
    current_dir <- parent_dir
  }
  for (candidate in candidates) {
    if (file.exists(file.path(candidate, token_rel))) return(normalizePath(candidate))
  }
  stop(
    "EIG token file not found from '", getwd(), "'. Run inside the repository or set ",
    "EIG_STYLE_DIR to its Infrastructure/style directory.",
    call. = FALSE
  )
}

eig_load_tokens <- function(path = NULL) {
  if (is.null(path)) path <- file.path(eig_style_dir(), "themes", "r", "eig_tokens.R")
  if (!file.exists(path)) {
    stop("Token file not found: ", path, call. = FALSE)
  }
  env <- new.env(parent = baseenv())
  sys.source(path, envir = env)
  env
}

eig_available_fonts <- function() {
  if (requireNamespace("systemfonts", quietly = TRUE)) {
    return(unique(systemfonts::system_fonts()$family))
  }
  fc_lines <- suppressWarnings(system("fc-list : family", intern = TRUE))
  if (length(fc_lines) == 0L) {
    stop(
      "Unable to enumerate system fonts: install the 'systemfonts' package or fontconfig.",
      call. = FALSE
    )
  }
  families <- trimws(unlist(strsplit(fc_lines, ",")))
  unique(families[nzchar(families)])
}

# Generic CSS family names, and the names R graphics devices use for them.
eig_generic_families <- c("serif" = "serif", "sans-serif" = "sans", "monospace" = "mono")

eig_resolve_family <- function(role = c("headline", "body"), tokens = NULL,
                               available = NULL, warn = TRUE) {
  role <- match.arg(role)
  if (is.null(tokens)) tokens <- eig_load_tokens()
  if (is.null(available)) available <- eig_available_fonts()
  spec <- tokens$EIG_TYPOGRAPHY[[role]]
  primary_chain <- c(spec$primary_family, unlist(spec$accept_as_primary))
  fallback_chain <- unlist(spec$fallback_stack)

  # 1) The primary family or a family accepted as primary: no warning.
  primary_hits <- primary_chain[primary_chain %in% available]
  if (length(primary_hits) > 0L) {
    family <- primary_hits[[1L]]
    attr(family, "eig_primary") <- TRUE
    return(family)
  }

  # 2) The first installed fallback, or the generic family that ends the stack.
  fallback_ok_flag <- fallback_chain %in% available | fallback_chain %in% names(eig_generic_families)
  if (!any(fallback_ok_flag)) {
    stop(
      "No EIG ", role, " font is available (tried: ",
      paste(c(primary_chain, fallback_chain), collapse = ", "), ").",
      call. = FALSE
    )
  }
  family <- fallback_chain[fallback_ok_flag][[1L]]
  if (family %in% names(eig_generic_families)) family <- eig_generic_families[[family]]
  if (warn) {
    warning(
      "EIG ", role, " font: '", spec$primary_family, "' is not installed; using fallback '",
      family, "'. Install the EIG fonts (Infrastructure/style/scripts/fonts/).",
      call. = FALSE
    )
  }
  attr(family, "eig_primary") <- FALSE
  family
}

eig_assert_fonts <- function(tokens = NULL, allow_fallback = FALSE) {
  if (is.null(tokens)) tokens <- eig_load_tokens()
  available <- eig_available_fonts()
  resolved <- lapply(
    c(headline = "headline", body = "body"),
    function(role) eig_resolve_family(role, tokens = tokens, available = available, warn = FALSE)
  )
  primary_flag <- vapply(resolved, function(x) isTRUE(attr(x, "eig_primary")), logical(1L))
  if (!allow_fallback && !all(primary_flag)) {
    missing_roles <- names(resolved)[!primary_flag]
    missing_families <- vapply(
      missing_roles,
      function(role) tokens$EIG_TYPOGRAPHY[[role]]$primary_family,
      character(1L)
    )
    stop(
      "Missing required EIG primary fonts: ", paste(missing_families, collapse = ", "),
      ". Run an installer in Infrastructure/style/scripts/fonts/ and restart the session.",
      call. = FALSE
    )
  }
  invisible(TRUE)
}

# A semibold alias for `family`, registered with systemfonts so devices built on it
# (ragg, svglite) draw the semibold weight. NULL when it cannot be registered, for
# example for a generic family; callers then fall back to face = "bold".
eig_semibold_family <- function(family) {
  if (!requireNamespace("systemfonts", quietly = TRUE)) return(NULL)
  alias <- paste(family, "EIG Semibold")
  if (alias %in% systemfonts::registry_fonts()$family) return(alias)
  registered_flag <- tryCatch(
    {
      systemfonts::register_variant(name = alias, family = family, weight = "semibold")
      TRUE
    },
    error = function(e) FALSE
  )
  if (registered_flag) alias else NULL
}

# Family and ggplot2 face for a typography role, honoring its token weight.
eig_role_font <- function(role_name, tokens, headline_family, body_family) {
  role <- tokens$EIG_TYPOGRAPHY$roles[[role_name]]
  is_headline_flag <- identical(role$family, tokens$EIG_TYPOGRAPHY$headline$primary_family)
  family <- if (is_headline_flag) headline_family else body_family
  if (identical(role$weight, "semibold")) {
    semibold_family <- eig_semibold_family(family)
    if (!is.null(semibold_family)) return(list(family = semibold_family, face = "plain"))
    return(list(family = family, face = "bold"))
  }
  face <- if (identical(role$weight, "bold")) "bold" else "plain"
  list(family = family, face = face)
}

eig_role_size <- function(role_name, tokens) {
  tokens$EIG_TYPOGRAPHY$roles[[role_name]]$size_pt
}

eig_theme_ggplot <- function(tokens = NULL) {
  if (is.null(tokens)) tokens <- eig_load_tokens()
  if (!requireNamespace("ggplot2", quietly = TRUE)) {
    stop("Package 'ggplot2' is required.", call. = FALSE)
  }
  headline_family <- eig_resolve_family("headline", tokens = tokens)
  body_family <- eig_resolve_family("body", tokens = tokens)
  title_font <- eig_role_font("chart_title", tokens, headline_family, body_family)
  subtitle_font <- eig_role_font("subtitle", tokens, headline_family, body_family)
  text_pt <- eig_role_size("axis_legend_table_body", tokens)
  black <- tokens$EIG_COLORS[["eig_black"]]
  white <- tokens$EIG_COLORS[["eig_white"]]

  # Titles stay in the image, flush left with the whole plot, in sentence case and
  # without a "Figure N." prefix; the document supplies the numbering. A plot with no
  # title (labs(title = NULL)) needs nothing from the theme.
  ggplot2::theme_minimal(base_size = text_pt, base_family = body_family) +
    ggplot2::theme(
      plot.title.position = "plot",
      plot.caption.position = "plot",
      text = ggplot2::element_text(family = body_family, color = black),
      plot.title = ggplot2::element_text(
        family = title_font$family,
        face = title_font$face,
        size = eig_role_size("chart_title", tokens),
        color = black,
        hjust = 0
      ),
      plot.subtitle = ggplot2::element_text(
        family = subtitle_font$family,
        face = subtitle_font$face,
        size = eig_role_size("subtitle", tokens),
        color = tokens$EIG_COLORS[["eig_teal_900"]],
        hjust = 0
      ),
      axis.title = ggplot2::element_text(size = text_pt, color = black),
      axis.text = ggplot2::element_text(size = text_pt, color = black),
      legend.title = ggplot2::element_text(size = text_pt, color = black),
      legend.text = ggplot2::element_text(size = text_pt, color = black),
      panel.grid.minor = ggplot2::element_blank(),
      panel.grid.major.x = ggplot2::element_blank(),
      panel.grid.major.y = ggplot2::element_line(
        color = tokens$EIG_NEUTRALS[["eig_neutral_grid"]],
        linewidth = 0.3
      ),
      plot.background = ggplot2::element_rect(fill = white, color = NA),
      panel.background = ggplot2::element_rect(fill = white, color = NA),
      plot.caption = ggplot2::element_text(
        family = body_family,
        size = eig_role_size("notes_caption", tokens),
        color = tokens$EIG_NEUTRALS[["eig_neutral_caption"]],
        hjust = 0
      )
    )
}

eig_scale_color <- function(tokens = NULL, ...) {
  if (is.null(tokens)) tokens <- eig_load_tokens()
  if (!requireNamespace("ggplot2", quietly = TRUE)) {
    stop("Package 'ggplot2' is required.", call. = FALSE)
  }
  ggplot2::scale_color_manual(values = tokens$EIG_DISCRETE, ...)
}

eig_scale_fill <- function(tokens = NULL, ...) {
  if (is.null(tokens)) tokens <- eig_load_tokens()
  if (!requireNamespace("ggplot2", quietly = TRUE)) {
    stop("Package 'ggplot2' is required.", call. = FALSE)
  }
  ggplot2::scale_fill_manual(values = tokens$EIG_DISCRETE, ...)
}

eig_scale_fill_seq <- function(which = c("eig_seq_blue_5", "eig_seq_red_5"), tokens = NULL, ...) {
  if (is.null(tokens)) tokens <- eig_load_tokens()
  if (!requireNamespace("ggplot2", quietly = TRUE)) {
    stop("Package 'ggplot2' is required.", call. = FALSE)
  }
  which <- match.arg(which)
  cols <- unname(unlist(tokens$EIG_SEQUENTIAL[[which]]))
  ggplot2::scale_fill_gradientn(colors = cols, ...)
}

eig_base_defaults <- function(tokens = NULL) {
  if (is.null(tokens)) tokens <- eig_load_tokens()
  black <- tokens$EIG_COLORS[["eig_black"]]
  old <- graphics::par(
    family = eig_resolve_family("body", tokens = tokens),
    bg = tokens$EIG_COLORS[["eig_white"]],
    fg = black,
    col.axis = black,
    col.lab = black,
    las = 1,
    bty = "l"
  )
  invisible(old)
}

# A CSS font-family list for browser renderers (plotly, gt): the token chain, in order.
eig_css_family <- function(role = c("headline", "body"), tokens) {
  role <- match.arg(role)
  spec <- tokens$EIG_TYPOGRAPHY[[role]]
  chain <- c(spec$primary_family, unlist(spec$accept_as_primary), unlist(spec$fallback_stack))
  quoted <- ifelse(grepl(" ", chain), paste0("'", chain, "'"), chain)
  paste(quoted, collapse = ", ")
}

# Points to CSS pixels at 96 dpi.
eig_pt_to_px <- function(pt) pt * 96 / 72

eig_plotly_layout <- function(tokens = NULL) {
  if (is.null(tokens)) tokens <- eig_load_tokens()
  black <- tokens$EIG_COLORS[["eig_black"]]
  list(
    font = list(
      family = eig_css_family("body", tokens),
      size = eig_pt_to_px(eig_role_size("axis_legend_table_body", tokens)),
      color = black
    ),
    title = list(
      font = list(
        family = eig_css_family("headline", tokens),
        size = eig_pt_to_px(eig_role_size("chart_title", tokens)),
        color = black
      ),
      x = 0
    ),
    paper_bgcolor = tokens$EIG_COLORS[["eig_white"]],
    plot_bgcolor = tokens$EIG_COLORS[["eig_white"]],
    colorway = unname(unlist(tokens$EIG_DISCRETE)),
    xaxis = list(showgrid = FALSE, zeroline = FALSE),
    yaxis = list(showgrid = TRUE, gridcolor = tokens$EIG_NEUTRALS[["eig_neutral_grid"]], zeroline = FALSE)
  )
}

eig_style_gt <- function(gt_tbl, tokens = NULL) {
  if (is.null(tokens)) tokens <- eig_load_tokens()
  if (!requireNamespace("gt", quietly = TRUE)) {
    stop("Package 'gt' is required.", call. = FALSE)
  }
  table_tokens <- tokens$EIG_TABLES
  color_of <- function(token_id) c(tokens$EIG_COLORS, tokens$EIG_NEUTRALS)[[token_id]]
  rule_color <- color_of(table_tokens$body$rule_color_token)
  header_role <- tokens$EIG_TYPOGRAPHY$roles[[table_tokens$header$font_role]]
  body_role <- tokens$EIG_TYPOGRAPHY$roles[[table_tokens$body$font_role]]
  header_weight <- if (identical(header_role$weight, "semibold")) 600L else "bold"

  gt_tbl |>
    gt::tab_options(
      table.font.names = eig_css_family("body", tokens),
      table.font.size = gt::px(eig_pt_to_px(body_role$size_pt)),
      column_labels.font.size = gt::px(eig_pt_to_px(header_role$size_pt)),
      table.border.top.width = gt::px(0),
      table.border.bottom.color = rule_color,
      heading.border.bottom.width = gt::px(0),
      column_labels.border.top.width = gt::px(0),
      column_labels.border.bottom.color = rule_color,
      table_body.hlines.color = color_of(table_tokens$body$row_rule_color_token),
      table_body.hlines.width = gt::px(1),
      table_body.vlines.width = gt::px(0)
    ) |>
    gt::tab_style(
      style = list(
        gt::cell_fill(color = color_of(table_tokens$header$background_token)),
        gt::cell_text(color = color_of(table_tokens$header$text_token), weight = header_weight)
      ),
      locations = gt::cells_column_labels(columns = gt::everything())
    )
}
