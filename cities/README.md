# US city selection (`cities/`)

This folder holds the **US-directed city-sampling tool** and its inputs. It
produces a stratified sample of US cities — a study list — used as one of the
sources for the cities GSV Tracker follows. It does **not** collect any imagery;
it only chooses *which* cities to collect.

For the full picture of every way a city ends up in the catalog (this US sample,
archival baseline imports, ad-hoc partner requests, and the proposed worldwide
frame), see [`../docs/city_sampling.md`](../docs/city_sampling.md).

> **⚠️ Caveat.** Appearing on this study list (886 cities) does **not** mean a
> city has been collected — selection and collection are separate steps.
> Catalog-wide "cities tracked" counts are currently **provisional and under
> investigation** ([#112](https://github.com/jonfroehlich/gsv-tracker/issues/112));
> see `../docs/city_sampling.md` for the definitions and caveats.

## Files

| File | What it is |
|------|------------|
| `us_census_city_analyzer.py` | The selection script. |
| `SUB-IP-EST2023-POP.xlsx` | Input: US Census Bureau **Subcounty Resident Population Estimates** (Vintage 2023), covering 2020–2023 population for incorporated places and minor civil divisions. |
| `selected_cities.txt` | Output: the selected study list, one `City, State` per line (currently **886 cities**), sorted by state then city. |
| `us_census_city_selection.log` | Run log (created on execution; parsing warnings, per-state notes). |

## Selection methodology

Implemented in `select_study_cities()`. For **each state independently**:

1. **Always include the state capital** (from a hardcoded state→capital map).
2. **Always include the largest city** by 2023 population (or the 2nd-largest if
   the capital is already the largest).
3. **Quartile-stratify the rest**: bin the remaining cities into four population
   quartiles (`Q1`–`Q4`) with `pandas.qcut`, then **randomly sample 5 cities
   from each quartile** (`cities_per_quartile`, default 5).
4. States with fewer than `4 * cities_per_quartile + 2` (= 22 at the default)
   qualifying cities are **skipped** for insufficient data.

The goal is a per-state sample that spans the full population range — from the
capital and largest metro down through small towns — rather than only big
cities. `analyze_selection_coverage()` / `print_selection_analysis()` report how
much of each state's population and size range the sample covers.

Input cleaning (`extract_city_state()`) strips Census classification suffixes
(`city`, `town`, `village`, `township`, `borough`, `municipality`, etc.) and
resolves parenthetical place names so entries like `"Albany city, New York"`
become `City="Albany", State="New York"`.

## Reproducibility caveats

- **The random sampling is not seeded.** `DataFrame.sample()` is called without a
  `random_state`, so **re-running produces a different quartile sample.**
  `selected_cities.txt` is the frozen artifact of one particular run — treat the
  checked-in file as the source of truth, not something to regenerate casually.
  (If exact reproducibility is ever needed, thread a `--seed` through
  `select_study_cities()` → `.sample(random_state=seed)`.)
- The capital list is **hardcoded** in `map_state_to_capital`; it covers the 50
  states (no DC / territories).
- Population is a **Vintage 2023** snapshot; refreshing the study list means
  dropping in a newer Census `SUB-IP-EST*` file and re-running.

## Usage

```bash
# from the repo root, with the venv active
python cities/us_census_city_analyzer.py \
  --input-file cities/SUB-IP-EST2023-POP.xlsx \
  --log-level INFO
# writes selected_cities.txt (in the current working directory) + prints coverage analysis
```

Requires `pandas` (and `openpyxl` to read the `.xlsx`). To actually collect the
selected cities, feed the list to the batch runner — see the main
[`../README.md`](../README.md) ("Batch Processing Multiple Cities").
