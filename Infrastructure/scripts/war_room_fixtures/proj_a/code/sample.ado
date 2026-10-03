* Fixture ado file for war-room tests. Not part of any analysis pipeline.
* Synthetic: every value here is invented.

* --- Program ------------------------------------------------------------
program define prime_share, rclass
    syntax varlist(max=1) [if]
    marksample touse
    quietly count if touse == 1 & age >= 25
    return scalar n_prime = r(N)
end

* --- Notes --------------------------------------------------------------
* The caller is expected to have loaded the person-level extract already.
