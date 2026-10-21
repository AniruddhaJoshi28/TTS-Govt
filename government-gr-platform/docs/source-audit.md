# Source Audit

**Audit date:** 2026-10-21 · **Audit host:** Windows 11 developer machine, direct internet (no proxy)
**Method:** HTTP fetch of each listing page and `robots.txt`, inspection of HTML/JS for forms, pagination and AJAX endpoints, test requests for pagination and PDF downloads. All findings below come from real responses captured during the audit; captured HTML is stored under `tests/fixtures/html/`.

A source is marked **VERIFIED_WORKING** only after an adapter discovered documents *and* downloaded at least one PDF that passed signature, structure (PyMuPDF parse) and SHA-256 checks.

## Summary

| Key | State | Source | Status | Validated PDFs |
|---|---|---|---|---|
| `mh_gr_portal` | Maharashtra | gr.maharashtra.gov.in GR portal | VERIFIED_WORKING | 8 |
| `mh_orgpedia_backfill` | Maharashtra | Orgpedia seed list → official PDFs | VERIFIED_WORKING | 5 |
| `od_stsc_resolutions` | Odisha | ST & SC Development Dept | VERIFIED_WORKING | 5 |
| `od_agri_resolutions` | Odisha | Agriculture & Farmers' Empowerment – Resolutions | VERIFIED_WORKING | 5 |
| `od_agri_circulars` | Odisha | Agriculture – Circulars & Office Orders | PARTIALLY_WORKING | 0 (listing parsed, no download yet) |
| `od_agri_notifications` | Odisha | Agriculture – Notifications | PARTIALLY_WORKING | 0 (20 rows discovered via Scrapy, no download yet) |
| `od_egazette` | Odisha | eGazette search | PARTIALLY_WORKING | 0 (no result rows observable) |
| `mp_socialjustice_circulars` | Madhya Pradesh | Social Justice & Disabled Persons Welfare Dept | VERIFIED_WORKING | 5 |
| `od_cabinet` | Odisha | cabinet.odisha.gov.in | UNAVAILABLE | – |
| `od_ctz_edespatch` | Odisha | ctz.edodisha.gov.in (e-Despatch) | REQUIRES_MANUAL_ACCESS | – |
| `mp_services_portal` | Madhya Pradesh | services.mp.gov.in | NOT_YET_TESTED (no document repository found) | – |
| `mh_dte_grs` | Maharashtra | dte.maharashtra.gov.in | NOT_YET_TESTED | – |
| `mh_bhumiabhilekh_grs` | Maharashtra | bhumiabhilekh.maharashtra.gov.in | UNAVAILABLE | – |

PDF counts are from the bounded test crawls run during this audit (small download limits on purpose). They are **not** coverage figures.

---

## Maharashtra

### gr.maharashtra.gov.in — `mh_gr_portal` — VERIFIED_WORKING
- **robots.txt:** `Allow: /`, disallows only `/admin/`, `/wp-login.php`, `/private/`, `/tmp/`.
- **Technology:** ASP.NET WebForms (`__VIEWSTATE` ≈ 27 KB, `__EVENTVALIDATION`), IIS 10.
- **Listing:** table `#SitePH_dgvDocuments`. Columns: क्रमांक / विभागाचे नाव / शीर्षक / सांकेतांक क्रमांक (18-digit unique code) / जी.आर. दिनांक (`DD-MM-YYYY`) / आकार (KB) / PDF link.
- **Default view:** recent GRs only, 25 pages × 10 rows (≈ 244 GRs, 14–21 Oct 2026). Page numbers are shown in Devanagari digits (`२५`).
- **Pagination:** postback with `ctl00$SitePH$ucPaging$txtPageNo` + `btnGo`. Tested directly to page 25 — **does not require the CAPTCHA**.
- **Search:** department/date-range/GR-number search needs the image CAPTCHA (`ctl00$SitePH$txtimgcode`). **Not automated** (no CAPTCHA bypass). Consequence: historical traversal through the portal's own search is not possible automatically → see Orgpedia seed below and the manual-import workflow.
- **PDF URLs:** `/Site/Upload/Government%20Resolutions/{Marathi|English}/<code>.pdf`. Both folders return identical bytes for the same code (verified on `202607091751031101`, 162,859 bytes each) → the canonical URL always uses `Marathi`, the identity is the unique code.
- **Download behaviour:** `HEAD` returns 404; `GET` returns `application/pdf` with `ETag` and `Last-Modified` → conditional GET supported.
- **Departments:** some names carry a validity suffix such as `(पासुन २४-जून-२०२६)` after reorganisation; normalised away, raw value kept.
- **Text-layer quality:** PDFs have Unicode text layers, but with Devanagari glyph-ordering errors (e.g. `यािी` for `यादी`). 13/13 archived MH PDFs were flagged `glyph_order_errors` → OCR recommended.

### Orgpedia (github.com/orgpedia) — `mh_orgpedia_backfill` — VERIFIED_WORKING
- **Licence:** MIT (mahGRs and per-department repos such as `mahagri`).
- **Data:** `mahGRs` README lists 101,074 GRs across 33 departments (2017–2026) as Marathi/English text. Per-department repos publish `import/documents/documents.json` with `url`, `code`, `date`, `dept`, `text` (English title), `num_pages`. `mahagri` has 3,639 entries.
- **Use in this platform:** identifiers only. URLs are rebuilt from the code against `gr.maharashtra.gov.in` and every PDF is downloaded and validated from the official server; Orgpedia fields are kept under `raw.provenance`. Orgpedia's English titles never overwrite official Marathi titles.
- **Verified:** 5 seeded 2018 GRs downloaded from the official server.
- Only `mahagri` is configured; add other repo names to `options.repos` (names should be checked against github.com/orgpedia first).

### dte.maharashtra.gov.in — `mh_dte_grs` — NOT_YET_TESTED
WordPress page with an 85-row table (date / title / PDF / size), PDFs under `/wp-content/uploads/`. Page contains a CAPTCHA widget (for site search). No adapter written yet.

### bhumiabhilekh.maharashtra.gov.in — UNAVAILABLE
Connection timed out from the audit host (both `www.` and bare host).

## Madhya Pradesh

No central GR repository was found. Orders are spread across departmental sites.

### socialjustice.mp.gov.in — `mp_socialjustice_circulars` — VERIFIED_WORKING
- **robots.txt:** the URL returns an HTML page, so there are no robots rules.
- **Technology:** CodeIgniter. `/circular` renders an empty `#ajaxdata` container; rows come from `POST /Circular/ajaxPaginationData/<offset>` (fields `page, cat_id, issed_by, year, sTitle, csrf_token_id`).
- **Session:** needs the `ci_session` cookie from a GET on the **same host**. A request from `www.socialjustice.mp.gov.in` to the bare host returned **403**; a same-host request returned 200.
- **Pagination:** offset steps of 10 (`searchFilter(10)`, `searchFilter(20)`, …).
- **Columns:** क्रमांक / आदेश क्रमांक / श्रेणी / शीर्षक / को जारी / जारीकर्ता / प्रकाशित तिथि / लिंक.
- **PDFs:** `/uploads/files/<name>.pdf`; file names may contain Devanagari (percent-encoded consistently).
- **Browser automation:** not needed. The "dynamic" listing is plain AJAX and works over HTTP.
- **Text-layer quality:** 2 PDFs had Private-Use-Area glyphs and control characters (broken ToUnicode maps); 3 had no text layer. All 5 flagged `needs_ocr`.

### services.mp.gov.in — NOT_YET_TESTED
Redirects to `/eservice/`, a citizen service portal. No order/circular repository found.

### Other MP departments
`gad.mp.gov.in` and `finance.mp.gov.in` are reachable (HTTP 200), but no order-listing links were found on their homepages. They need per-site investigation (candidates for future adapters).

## Odisha

### Odisha Drupal departmental template — `od_stsc_resolutions`, `od_agri_*`
- **robots.txt:** HTTP **403** on both stsc and agri, so no published rules. The crawler treats this as "no rules" and stays at the conservative default rate.
- **Technology:** Drupal Views. `table.views-table` with columns identified by class (`views-field-title`, `views-field-field-letter-number`, `views-field-field-date`, link in `views-field-nothing`). **Column order differs between departments** (STSC: title/letter/date; Agri: title/date/letter), so the parser maps columns by class, not position.
- **Pagination:** `?page=N` (0-based). STSC shows pages 0–8; Agri resolutions fit on one page (17 rows).
- **PDFs:** `/sites/default/files/YYYY-MM/<name>.pdf`, same host.
- **Date formats:** STSC `DD-MM-YYYY`, Agri `DD/MM/YYYY`.
- **Text-layer quality:** of 10 archived PDFs, 6 were fully digital English and 4 were scans without a text layer.
- Other Odisha departments probably use the same template. Adding one is a config change in `configs/sources.yaml`, but each new site must still be audited.

### egazette.odisha.gov.in — `od_egazette` — PARTIALLY_WORKING
- GET `/search_gazette/` returns a form that posts to `/search_gazette_result`, with hidden `csrf_gazette_odisha` and fields gType (Extraordinary/Weekly), cYear, monthName, weekTime, deptID, notNum, date range and keywords. **No CAPTCHA observed.**
- The year selector offered **only 2024**. Searches for 2024/January/Extraordinary and for 2026 both returned "In this section no document available at this moment".
- The adapter can submit searches. The result-row parser targets the 5-column result table but has **not been verified against a real result row**.

### cabinet.odisha.gov.in — `od_cabinet` — UNAVAILABLE
TLS handshake failed with `SEC_E_CERT_EXPIRED` (expired certificate); plain HTTP gave no response. Not crawled: TLS verification is never disabled. Use the manual-import workflow if needed.

### ctz.edodisha.gov.in — `od_ctz_edespatch` — REQUIRES_MANUAL_ACCESS
e-Despatch citizen portal. It shows office-wise despatch/receipt counts and a hierarchy lookup (`/Home/FillHierarchyCitizen`). No public document listing was found.

## Cross-cutting observations
- **Duplicates / alternate URLs:** MH serves the same file under the `Marathi/` and `English/` folders, and MP is reachable via `www.` and the bare host. Both are canonicalised. Identical binaries across different listing entries are linked as `duplicate_binary`.
- **Indic digits:** MH renders page counts and some dates in Devanagari numerals. They are converted only in numeric fields; titles are stored verbatim.
- **No source needed Playwright.** All dynamic behaviour seen (ASP.NET postbacks, CodeIgniter AJAX, CSRF forms) works over plain HTTP.
- **Text layers are unreliable for Indic PDFs.** OCR (Tesseract mar/hin/ori) is required for good Marathi/Hindi text. See `docs/IMPLEMENTATION_STATUS.md`.
