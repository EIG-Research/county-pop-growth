version 17.0

* check-fonts.do -- report whether the EIG headline and body fonts are available to Stata.
*   do Infrastructure/style/scripts/fonts/check-fonts.do [allow_fallback]
* Exit codes: 0 pass, 459 fonts missing, 601 token file not found.
*
* The family lists come from the generated token globals, like the R and Python
* checkers: the primary family and the families the tokens accept as primary (Source
* Serif 4 for Source Serif Pro) pass; the fallback stack passes with allow_fallback.
*
* Each candidate is probed by setting it as the window font. Stata has no command
* that reports the current font, so the check ends by setting the window font back
* to Stata's default on every path; eig_graph_defaults then sets the EIG fonts.

local mode "`1'"
local allow_fallback 0
if "`mode'" == "allow_fallback" local allow_fallback 1

* Load the token globals when the caller has not.
if `"$EIG_FONT_BODY"' == "" {
    local tokens ""
    if `"$EIG_STYLE_DIR"' != "" local tokens `"$EIG_STYLE_DIR/themes/stata/eig_tokens.do"'
    foreach up in "." ".." "../.." "../../.." "../../../.." {
        foreach candidate in "`up'/Infrastructure/style" "`up'" {
            if `"`tokens'"' == "" {
                capture confirm file `"`candidate'/themes/stata/eig_tokens.do"'
                if !_rc local tokens `"`candidate'/themes/stata/eig_tokens.do"'
            }
        }
    }
    capture confirm file `"`tokens'"'
    if _rc {
        di as error "ERROR: EIG token file not found. Set the global EIG_STYLE_DIR."
        exit 601
    }
    quietly do `"`tokens'"'
}

foreach role in HEADLINE BODY {
    local `role'_primary ""
    foreach f in `"${EIG_FONT_`role'}"' ${EIG_FONT_`role'_ACCEPT} {
        capture graph set window fontface `"`f'"'
        if _rc == 0 & `"``role'_primary'"' == "" local `role'_primary `"`f'"'
    }
    local `role'_fallback ""
    foreach f in ${EIG_FONT_`role'_FALLBACK} {
        capture graph set window fontface `"`f'"'
        if _rc == 0 & `"``role'_fallback'"' == "" local `role'_fallback `"`f'"'
    }
}

* The first family that passed, for eig_graph_defaults; empty when none did.
foreach role in HEADLINE BODY {
    if `"``role'_primary'"' != "" global EIG_FONT_`role'_RESOLVED `"``role'_primary'"'
    else global EIG_FONT_`role'_RESOLVED `"``role'_fallback'"'
}

graph set window fontface default

local failed 0
foreach role in HEADLINE BODY {
    local name = lower("`role'")
    if `"``role'_primary'"' != "" {
        di as text `"OK `name': ``role'_primary'"'
    }
    else if `"``role'_fallback'"' != "" {
        di as text `"FALLBACK `name': ``role'_fallback' (primary ${EIG_FONT_`role'} is not installed)"'
        if !`allow_fallback' local failed 1
    }
    else {
        di as error `"MISSING `name': no family in the token chain is available (primary: ${EIG_FONT_`role'})"'
        local failed 1
    }
}

if `failed' {
    di as error "ERROR: Required EIG fonts are missing. Run an installer in Infrastructure/style/scripts/fonts/ and restart Stata."
    exit 459
}
di as text "PASS: EIG fonts resolve" cond(`allow_fallback', " (fallbacks allowed).", " to primary families.")
exit 0
