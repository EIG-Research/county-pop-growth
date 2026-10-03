version 17.0

* eig_theme.do -- EIG graph setup for Stata.
*
* Run it from anywhere inside the repository, then:
*   do Infrastructure/style/themes/stata/eig_theme.do
*   eig_load_tokens
*   capture noisily eig_assert_fonts, allowfallback
*   eig_graph_defaults
*
* The style directory (Infrastructure/style) comes from the Stata global
* $EIG_STYLE_DIR, then the EIG_STYLE_DIR environment variable, then a walk up from
* the working directory. Colors, fonts, and sizes come from the generated
* themes/stata/eig_tokens.do and the generated scheme themes/stata/scheme-eig.scheme;
* this file holds no color values of its own.

capture program drop eig_style_dir
program define eig_style_dir, rclass
    local token_rel "themes/stata/eig_tokens.do"
    local found ""

    * 1) An explicit global or environment variable wins; a wrong one is an error.
    local dir `"$EIG_STYLE_DIR"'
    if `"`dir'"' == "" local dir : environment EIG_STYLE_DIR
    if `"`dir'"' != "" {
        capture confirm file `"`dir'/`token_rel''"'
        if _rc {
            di as error `"ERROR: EIG_STYLE_DIR is `dir', but `token_rel' is not there."'
            exit 601
        }
        local found `"`dir'"'
    }

    * 2) Walk up from the working directory.
    foreach up in "." ".." "../.." "../../.." "../../../.." {
        foreach candidate in "`up'/Infrastructure/style" "`up'" {
            if `"`found'"' == "" {
                capture confirm file `"`candidate'/`token_rel''"'
                if !_rc local found `"`candidate'"'
            }
        }
    }
    if `"`found'"' == "" {
        di as error "ERROR: EIG token file not found from `c(pwd)'."
        di as error "Run inside the repository or set the global EIG_STYLE_DIR to its Infrastructure/style directory."
        exit 601
    }

    * Return an absolute path, so the adopath entry survives a later cd.
    local here `"`c(pwd)'"'
    quietly cd `"`found'"'
    local found `"`c(pwd)'"'
    quietly cd `"`here'"'
    return local dir `"`found'"'
end

capture program drop eig_load_tokens
program define eig_load_tokens
    args tokenfile
    eig_style_dir
    global EIG_STYLE_DIR `"`r(dir)'"'
    if `"`tokenfile'"' == "" local tokenfile `"$EIG_STYLE_DIR/themes/stata/eig_tokens.do"'
    capture confirm file `"`tokenfile'"'
    if _rc {
        di as error `"ERROR: Token file not found: `tokenfile'"'
        exit 601
    }
    quietly do `"`tokenfile'"'
end

capture program drop eig_assert_fonts
program define eig_assert_fonts
    syntax [, ALLOWFALLBACK]
    local mode ""
    if "`allowfallback'" != "" local mode "allow_fallback"

    if `"$EIG_FONT_BODY"' == "" eig_load_tokens
    local checker `"$EIG_STYLE_DIR/scripts/fonts/check-fonts.do"'
    capture confirm file `"`checker'"'
    if _rc {
        di as error `"ERROR: Missing `checker'"'
        exit 601
    }
    * capture keeps a failing check from aborting before its return code is read.
    capture noisily do `"`checker'"' `mode'
    local rc = _rc
    if `rc' {
        di as error "ERROR: EIG font validation failed."
        exit `rc'
    }
end

capture program drop eig_graph_defaults
program define eig_graph_defaults
    syntax [, TITLEFONT(string) BODYFONT(string)]

    if `"$EIG_FONT_BODY"' == "" eig_load_tokens
    * Prefer the families check-fonts.do found installed (eig_assert_fonts sets
    * them): the installers install Source Serif 4, not Source Serif Pro.
    if "`bodyfont'" == "" local bodyfont "$EIG_FONT_BODY_RESOLVED"
    if "`bodyfont'" == "" local bodyfont "$EIG_FONT_BODY"
    if "`titlefont'" == "" local titlefont "$EIG_FONT_HEADLINE_RESOLVED"
    if "`titlefont'" == "" local titlefont "$EIG_FONT_HEADLINE"

    * The generated scheme sets the colors, the white background, and the size.
    adopath + `"$EIG_STYLE_DIR/themes/stata"'
    set scheme eig

    * A scheme cannot set a font face, so fonts are set here.
    graph set window fontface "`bodyfont'"
    graph set print  fontface "`bodyfont'"
    graph set ps     fontface "`bodyfont'"

    * Convenience globals. A title takes the headline face through graph-text markup:
    *   title(`"{fontface "$EIG_CHART_TITLE_FONT":A sentence-case title}"')
    global EIG_CHART_TITLE_FONT "`titlefont'"
    global EIG_CHART_TEXT_FONT  "`bodyfont'"
    global EIG_CHART_BG "$EIG_HEX_EIG_WHITE"
    global EIG_CHART_TEXT "$EIG_HEX_EIG_BLACK"
end

capture program drop eig_palette_discrete
program define eig_palette_discrete, rclass
    return local colors "$EIG_DISCRETE_HEX"
end

capture program drop eig_palette_legacy
program define eig_palette_legacy, rclass
    syntax, SET(string)
    if "`set'" == "dci_quintile" {
        return local colors "$EIG_LEGACY_DCI_QUINTILE_DISTRESSED $EIG_LEGACY_DCI_QUINTILE_AT_RISK $EIG_LEGACY_DCI_QUINTILE_MID_TIER $EIG_LEGACY_DCI_QUINTILE_COMFORTABLE $EIG_LEGACY_DCI_QUINTILE_PROSPEROUS"
        exit
    }
    di as error "ERROR: Unsupported legacy set: `set'"
    exit 198
end
