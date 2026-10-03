version 17.0

* generate_examples.do -- EIG-styled Stata example outputs.
*   do Infrastructure/style/examples/stata/generate_examples.do [out_dir]
* Outputs go to out_dir, or to eig-examples-stata under Stata's temporary directory
* when it is omitted, so a run leaves nothing in the repository. Every color, font,
* and size comes from the token globals and the generated eig scheme. Figure text
* follows Infrastructure/style/docs/eig-figure-style.md: a sentence-case title, then a
* note line above the source line.

args out_dir

* Load the theme programs from the style directory: the global EIG_STYLE_DIR, then the
* EIG_STYLE_DIR environment variable, then a walk up from the working directory.
local theme ""
local style_dir `"$EIG_STYLE_DIR"'
if `"`style_dir'"' == "" local style_dir : environment EIG_STYLE_DIR
if `"`style_dir'"' != "" local theme `"`style_dir'/themes/stata/eig_theme.do"'
foreach up in "." ".." "../.." "../../.." "../../../.." {
    if `"`theme'"' == "" {
        capture confirm file `"`up'/Infrastructure/style/themes/stata/eig_theme.do"'
        if !_rc local theme `"`up'/Infrastructure/style/themes/stata/eig_theme.do"'
    }
}
if `"`theme'"' == "" {
    di as error "ERROR: eig_theme.do not found. Set EIG_STYLE_DIR (a global or an environment variable)."
    exit 601
}
quietly do `"`theme'"'
eig_load_tokens

if `"`out_dir'"' == "" local out_dir `"`c(tmpdir)'/eig-examples-stata"'
capture mkdir `"`out_dir'"'

capture noisily eig_assert_fonts, allowfallback
if _rc {
    di as error "WARNING: Font check failed; proceeding with available fonts."
}

eig_graph_defaults

sysuse auto, clear
local note   "Note: 1978 automobile data shipped with Stata."
local source "Source: StataCorp, auto dataset."

* The scheme supplies the white background, text colors, and gridlines; the series
* colors below name token globals because each plot layer sets its own.
twoway ///
    (scatter mpg weight, mcolor("$EIG_RGB_EIG_TEAL_900") msymbol(circle)) ///
    (lfit mpg weight, lcolor("$EIG_RGB_EIG_BLUE_800") lwidth(medthick)), ///
    title(`"{fontface "$EIG_CHART_TITLE_FONT":Heavier cars get fewer miles per gallon}"', position(11) span) ///
    xtitle("Weight (pounds)") ///
    ytitle("Miles per gallon") ///
    legend(order(1 "Observed" 2 "Linear fit") region(lstyle(none))) ///
    note("`note'" "`source'", span)
graph export `"`out_dir'/twoway_scatter.png"', replace width(1600)

graph bar (mean) mpg, over(foreign) ///
    bar(1, color("$EIG_RGB_EIG_TEAL_900")) ///
    title(`"{fontface "$EIG_CHART_TITLE_FONT":Foreign cars average more miles per gallon}"', position(11) span) ///
    ytitle("Mean miles per gallon") ///
    note("`note'" "`source'", span)
graph export `"`out_dir'/bar_chart.png"', replace width(1600)

* putdocx colors are hex digits without the leading "#".
local header_bg   = subinstr("$EIG_TABLE_HEADER_BG_HEX", "#", "", .)
local header_text = subinstr("$EIG_TABLE_HEADER_TEXT_HEX", "#", "", .)
local body_text   = subinstr("$EIG_HEX_EIG_BLACK", "#", "", .)

* putdocx table ... = data() takes variables in memory, so build the summary first.
preserve
collapse (mean) mean_mpg = mpg mean_weight = weight, by(foreign)
decode foreign, generate(origin)
format mean_mpg mean_weight %9.1f

putdocx clear
putdocx begin
putdocx paragraph, style(Heading1)
putdocx text ("Foreign cars average more miles per gallon")
putdocx table t1 = data(origin mean_mpg mean_weight), varnames
putdocx table t1(1,.), shading("`header_bg'") ///
    font("$EIG_FONT_BODY", $EIG_SIZE_PT_SUBTITLE, "`header_text'") bold
putdocx table t1(2/3,.), font("$EIG_FONT_BODY", $EIG_SIZE_PT_AXIS_LEGEND_TABLE_BODY, "`body_text'")
putdocx paragraph
putdocx text ("`source'"), font("$EIG_FONT_BODY", $EIG_SIZE_PT_NOTES_CAPTION, "`body_text'")
putdocx save `"`out_dir'/eig_table_example.docx"', replace
restore

display as text `"Wrote Stata example outputs to `out_dir'"'
