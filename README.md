# Boswell Contract Finder

A daily scan of open government contract opportunities for **Boswell Consulting Agency LLC**, screened against the firm's rules and published as a web page.

**View it:** https://meniceguy.github.io/boswell-contract-finder/

## What it does

Every weekday at 7:37 AM Eastern, a GitHub Actions job:

1. Pulls open notices from **SAM.gov** (federal), **Virginia eVA**, **South Carolina SCBO**, **North Carolina eVP** and **Nevada NevadaEPro**.
2. Scores each one against `config/profile.json`: NAICS codes, service keywords, notice type and portal category.
3. Applies the firm's screening gates:
   - **Paperwork:** flags requests for financial statements, staff resumes or government past performance.
   - **References:** screens out anything requiring client references or past performance questionnaires.
   - **No live orals:** passes only when the notice states no oral presentations will be held. Possible, conditional or optional orals, and live briefings, meetings or training in the scope, screen it out.
   - **Hard exclusions:** ineligible set-asides (including Virginia Small/Micro Priority without SWaM certification), deadlines under 7 days, staff required on site, security clearances, required licensed credentials, and anything on the "already handled" list.
4. Reads the full notice text for the top 20 federal candidates and screens them again.
5. Writes `docs/data/results.json`, which the page in `docs/` displays.

Maryland, West Virginia, Kentucky and Maine can't be scanned automatically; the page links to them with the firm's vendor IDs.

## Important limit

The scan reads notice text, not attached RFP documents. Oral presentation requirements, reference forms and staffing rules often sit in the attachments (federal RFP Sections C, L and M), so every match is preliminary until those are read.

## Running a scan now

Go to the **Actions** tab, choose **Daily contract scan**, and click **Run workflow**. Results appear on the page a minute or two after it finishes.

## Changing what it looks for

Edit `config/profile.json` on GitHub (pencil icon) and commit. The next scan uses the new settings.

- `naics`: codes and their tier (`core` scores higher than `secondary`)
- `keywords`: words that raise a notice's score when they appear in its title or text
- `federal_searches`: extra SAM.gov keyword searches
- `exclude`: kinds of work the firm doesn't do
- `handled`: title phrases or solicitation numbers already answered or ruled out; these are screened out
- `set_asides`, `swam`, `min_days`: eligibility settings

## If SAM.gov stops loading

SAM.gov sometimes blocks its public search from cloud servers. If the page says so, get a free API key from your SAM.gov account (Workspace, then Profile, then Public API Key), and add it in this repo under **Settings, Secrets and variables, Actions** as a secret named `SAM_API_KEY`. The scanner will switch to the official API automatically.
