# Fixture script for war-room tests. Not part of any analysis pipeline.
# Synthetic: every value here is invented.

# %% Setup
import csv
import statistics

ROWS = "data/raw/people.csv"

# Keep prime-age adults only.
def prime_age(rows):
    return [r for r in rows if int(r["age"]) >= 25]


# --- Helpers ------------------------------------------------------------
def wage_share(wages, total):
    return wages / total


def mean_wage(rows):
    return statistics.mean(float(r["wage"]) for r in rows)


# --- Output -------------------------------------------------------------
def main():
    with open(ROWS, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    print(mean_wage(prime_age(rows)))
