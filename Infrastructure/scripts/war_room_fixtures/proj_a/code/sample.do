* Fixture script for war-room tests. Not part of any analysis pipeline.
* Synthetic: every value here is invented.

* --- Setup --------------------------------------------------------------
clear all
set more off

use "data/raw/people.dta", clear

* Keep prime-age adults only.
keep if age >= 25
gen byte prime = 1

* --- Helpers ------------------------------------------------------------
program define wage_share
    args wages total
    display wages / total
end

* --- Output -------------------------------------------------------------
collapse (mean) wage, by(prime)

export delimited using "output/tables/wages.csv", replace
