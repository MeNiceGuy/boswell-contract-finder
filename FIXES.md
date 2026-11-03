# Fixes applied 2026-11-02 (from contract-finder-review-2026-11-02.md)

## Must-fix 1: orals gate now follows the no-live-orals guarantee rule
`scanner/gates.py`
- New `_oral_signal()`: express no-orals guarantee spans are masked out, then `ORAL_ANY` runs on the rest. A guarantee match no longer short-circuits the orals check, and any orals signal anywhere in the text fails the item and overrides a guarantee found elsewhere (e.g. a Phase I guarantee plus Phase II finalist presentations now fails).
- `eval_gates()`: orals is "fail" if any signal or any in-scope live duty is present; otherwise "guaranteed" only when an express guarantee phrase is present; otherwise "unconfirmed". The word "oral" inside a guarantee span ("will not hold oral presentations") is not itself a signal.

`scanner/scan.py`
- `score()` now computes an Unconfirmed bucket: an item that is not screened out still lands in `unconfirmed` when its orals status is "unconfirmed" or its eligibility is unconfirmed. Reasons are stored on `view.unconfirmed`. Unconfirmed items sort below confirmed matches and never count as matches.

`docs/index.html`
- Unconfirmed items render distinctly: dashed card border, dashed amber score circle, tier label "Unconfirmed" (never Strong/Good/Long shot/Weak), and one warning chip per reason ("Orals not confirmed: needs document read", "Eligibility not confirmed: needs document read").
- Matches tab count and the Strong/Good fits summary tiles count confirmed matches only; a separate "Unconfirmed" summary tile was added. Unconfirmed items appear in the list only when the new "Show unconfirmed" filter is on, and sort below confirmed matches. Sidebar explains the bucket.

## Must-fix 2: set-asides fail closed
`scanner/scan.py`
- The SAM detail read no longer stops at the top 20: every federal candidate that survives the first pass gets the full-text detail read, which supplies its real set-aside value (and re-screens its full text).
- `sam_norm()` also reads `typeOfSetAside` / `setAside` from the search payload when present.
- Eligibility states in `score()`: "confirmed" only on an affirmatively eligible set-aside (profile set-asides, or a Virginia designation while SWaM is held); "failed" on a disqualifying set-aside; otherwise "unconfirmed" — including portal values of NONE / N-A and state notices whose portal carries no set-aside field (SC, NC, NV), which now get the eligibility-unconfirmed treatment instead of displaying as eligible. Virginia's existing behavior is unchanged (a VA set-aside designation without SWaM still screens out).
- Consequence to know: a federal notice whose record carries no set-aside value at all lands in Unconfirmed, not Matches, until a human confirms it. That is the fail-closed behavior that was ordered.

## Should-fixes
- On-site: "work on-site" (and worked/working/works), "performed on site", "on-site at", "at the government site", and "on premises" / "on the premises" were promoted from flag to FAIL in `ONSITE_HARD`. Bare "on-site" mentions still only flag.
- Paperwork: the `contract numbers?` pattern was removed from `PAPER` (it matched nearly every federal notice).
- Handled list in `config/profile.json`: added "31PCSA-S4046", "GOHSEP", "BPM059595", "30-2026-048-DHB", "Kentucky HCBS", "746-2500000254", and "FAA Safety". Choice note: "FAA Safety" was added instead of "Safety Culture" because a bare "Safety Culture" substring could suppress unrelated legitimate safety-culture consulting titles; "FAA Safety" still matches the killed FAA item's titles while staying narrow.
- Vendor IDs out of the public copy: `vendor_id` removed from all four `manual_portals` entries in `config/profile.json` (name, site, url, why kept), and scrubbed from the committed `docs/data/results.json` as well since docs/ is the published site. The untouched original profile, IDs included, is preserved privately outside the repo at `~/workspace/contracting/boswell-contract-finder-private-profile.json`. The viewer now renders the Vendor ID line only when an ID is present.

## Verification
- `python3 -m py_compile scanner/gates.py scanner/scan.py`: OK.
- Synthetic gate tests (in /tmp/test_gates.py, run against the real modules): 10/10 passed — guarantee-only passes; no guarantee is unconfirmed and out of Matches; Phase I guarantee plus Phase II presentations fails; discretionary orals fail; 8(a) screens out; unknown set-aside is eligibility-unconfirmed for both SAM and NC items; "work on-site at" fails; "contract numbers" alone raises no paperwork flag; guarantee + SBA is a confirmed match; VA set-aside without SWaM still screens out.
- Viewer page: inline script passes `node --check`; doctype and closing tags intact.

Nothing was deployed or pushed.

## NC eVP fix 2026-11-02 (after the first live run failed: "search grid not found")

`scanner/scan.py` — NC path only; gates, scoring, and other sources untouched.

- What the portal changed: evp.nc.gov (Microsoft Power Pages) no longer renders the `__RequestVerificationToken` hidden input into the solicitations page HTML. The page now carries only `<div id="antiforgerytoken" data-url="/_layout/tokenhtml"></div>`, and the portal's own JavaScript fetches the token as an HTML fragment from `/_layout/tokenhtml`. The old `scan_nc()` scraped the token from the landing page, got nothing, and raised "eVP page layout changed; search grid not found". The grid itself did not change: `data-view-layouts` (base64 layout with `Base64SecureConfiguration`), `data-get-url` (`/_services/entity-grid-data.json/<id>`), the POST body, and the `Records`/`Attributes` response format are all exactly what the old parser expected.
- What the code does now: new `_evp_token()` helper tries the token in the page HTML first (older layout), then fetches `https://evp.nc.gov/_layout/tokenhtml` on the same session (with `X-Requested-With: XMLHttpRequest` and the solicitations page as Referer) and parses the token out of the returned fragment — the same request the portal's shell makes. A missing token now raises a distinct error ("eVP anti-forgery token not found") so future logs separate token failures from grid failures. The landing GET also goes through the module's retrying `get()` helper. POST endpoint, body, headers, and record normalization are unchanged.
- Live verification 2026-11-02: `python3 -m py_compile scanner/scan.py scanner/gates.py` OK; `scan_nc()` run live from the sandbox returned **269 open NC notices**, every record with the full normalized key set and non-empty title, solicitation number, agency, posted date, and deadline. Samples: "RFI: Large, Riverine, Urban Park Site Restoration Project" (298-FY27-CAM-PricingRFI, City of Asheville, due 2026-11-12); "Fletcher Stair Replacement at the Martin Marietta Center for the Performing Arts" (274-2027-RCPAC-07, City of Raleigh, due 2026-12-03); "Skate Rink Tiles" (298-IBR2118-27, City of Asheville, due 2026-11-16). Response paging confirmed single-page at pageSize 1000 (ItemCount 269, MoreRecords false).
