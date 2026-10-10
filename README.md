# job-hunter

Collects software jobs in Australia from public job sites (no logins) into an Excel sheet, so you can open the
link and apply. It filters out roles that aren't software and roles that strictly need Australian citizenship / PR
or a security clearance.

## Sources
Seek, LinkedIn (public search), Hatch, Built In Sydney, Employment Hero, and company career feeds
(Greenhouse / Lever / Ashby / SmartRecruiters - see `COMPANIES` in `jobs.py`).
Wellfound and Indeed block scripts, so they are not included.

## Setup (once)
Needs Python 3.10+.

```bash
pip install -r requirements.txt
```

## Run
```bash
python jobs.py
```
A full run takes about 10-15 minutes (it waits between requests so the sites don't block you).
It writes `jobs.xlsx` next to the script.

## Using the sheet
- **Jobs** sheet: one row per job, with a clickable URL. Pick **Applied / Skip / Interview...** in the *Status* column
  (default is *Ready*), then **save (Ctrl+S)**.
- **Excluded** sheet: jobs that were dropped and why (not software, citizen/PR only, clearance...). Skim it to check
  the filter isn't dropping good jobs.
- *Visa note* column: "citizen/PR + visa OK?" means the ad mentions citizen/PR but also allows visa holders - read it
  before applying. "asks for work rights" means it wants full work rights.

## Re-running
- Rows whose Status is **not** "Ready" are kept as they are. "Ready" rows are re-checked every run.
- Close `jobs.xlsx` in Excel before running; the script refuses to run if the file is open, so edits aren't lost.
- A copy of the previous sheet is saved to `backups/` before each run.

## Tuning
- `jobs.py` top: search keywords, pages per site, cities for Hatch, delay between requests.
- `filters.py`: title rules, "is this a software role" rules, citizen/PR/clearance rules.
  Run `python filters.py` to see the built-in self-tests.

## Notes
Seek and LinkedIn terms of use don't allow scraping. Keep the volume low, and use this for personal job searching only.
