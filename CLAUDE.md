# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A static, zero-build academic homepage for Dongming Han (韩东明). Three editable surfaces:

- `index.html` — single ~1.5k-line file (HTML + inline CSS + inline JS, no framework, no bundler) that fetches three JSON files at runtime and renders the page.
- `fetch_scholar.py` — Python data pipeline (stdlib only; `scholarly` optional) that produces `data/publications.json`.
- `make_og_card.py` — regenerates `assets/og-card.jpg` (the 1200×630 social-share card) from the live metrics in `publications.json`. **Re-run it whenever the citation numbers change**, or the social card goes stale. Needs Pillow.
- `data/profile.json` + `data/profile.zh.json` + `data/publications_manual.json` — hand-edited content (bio, news, awards, manual paper overrides). The first two control the bilingual UI; the third feeds the Python pipeline.

There is no `package.json`, no test suite, no lint config. Editing means: change a JSON file or `index.html`, reload the browser.

## Commands

```bash
# Serve locally for development (matches .claude/launch.json — port 8081).
# This is LOCAL ONLY. Production is GitHub Pages, which serves the static files
# directly from the repo — no Python server runs in production.
python3 -m http.server 8081

# Full refresh: DBLP → cache restore → DOI crawl → OpenAlex → Scholar → manual merge → assets
python3 fetch_scholar.py

# Fast path — skip ALL remote calls. Re-merges manual overrides (publications + author block),
# rescans assets/, re-picks photo/CV, AND recomputes h-index/i10/citedby from per-paper counts
# (max with existing, so a higher Scholar value never gets clobbered). Use this after editing
# data/publications_manual.json, data/profile*.json, or dropping files in assets/.
python3 fetch_scholar.py --use-cache

# Useful flags when network is unreliable:
python3 fetch_scholar.py --no-scholar    # skip Google Scholar (often CAPTCHA-blocked)
python3 fetch_scholar.py --no-openalex   # skip OpenAlex AND the DOI publisher-page crawler
                                          # (both are gated on the same flag)
python3 fetch_scholar.py --use-proxy     # opt into scholarly's FreeProxies probe (slow,
                                          # only useful when Scholar is rate-limiting)
```

The pipeline is stdlib-only by default. To enable richer Google Scholar lookups, `pip install scholarly`; the script auto-detects the import and falls back gracefully if it's missing (h-index gets derived locally from per-paper citation counts instead).

## Architecture

### Data pipeline (`fetch_scholar.py`)

Order of operations in `main()` — each stage mutates the in-memory list, and most are independently skippable:

1. **DBLP** (`fetch_from_dblp`) — primary source via `https://dblp.org/pid/231/6878.xml`. Always run; if it fails, the script falls back to the previously-saved `publications.json` and continues. On XML ParseError it logs the first 200 chars of the body so HTML maintenance pages are easy to diagnose.
2. **Cache restore** (`apply_cache`) — reads existing `data/publications.json`; restores `pdf_url`, `video_url`, `code_url`, `project_url`, `citations` for any title/DOI it recognizes. Lets you re-fetch without losing slowly-acquired PDF links.
3. **DOI crawl** (`crawl_doi_for_pdf`) — follows DOI → publisher page, scrapes `<meta name="citation_pdf_url">`. Works for Springer/Frontiers/Nature/PLOS/BMC/JCST/FITEE — i.e. any publisher that emits a `citation_pdf_url` meta tag. Does NOT work for IEEE Xplore, ACM DL, ScienceDirect, or Sage.
4. **OpenAlex** (`enrich_with_openalex`) — free, no API key. Adds open-access PDF + citation count. Title-search results are accepted only when the first 40 chars match AND the year agrees, to suppress same-prefix collisions.
5. **Google Scholar** (`enrich_with_scholar` → `scrape_scholar_indices` → derived-from-per-paper-counts fallback at `fetch_scholar.py:942`) — best-effort h-index/i10. If Scholar is blocked AND the HTML scrape fails, h-index is computed locally from each paper's `citations` count.
6. **Manual merge** (`merge_manual_overrides` at `fetch_scholar.py:677`) — see "Disambiguation" below.
7. **Asset auto-link** (`link_local_assets` at `fetch_scholar.py:262`) — see "Assets" below.

The pipeline is deliberately resilient: every external call is wrapped, fallbacks chain. If everything remote fails, the script still produces a valid `publications.json` from cache + manual file.

### Author identity is hardcoded in Python

The author identity block at `fetch_scholar.py:36-49` is the single source of truth: `SCHOLAR_ID`, `DBLP_PID`, `AUTHOR_NAME`, `AUTHOR_ALIASES`, `CONTACT_EMAIL`, `DEFAULT_AFFILIATION`, `DEFAULT_INTERESTS`. **None** of these come from a JSON file — forking this template for a different researcher requires editing those Python constants. `CONTACT_EMAIL` is reused as the OpenAlex `User-Agent` mailto and as the default `author.email` in the output JSON.

### "Dongming Han" disambiguation (important)

DBLP's PID `231/6878` indexes every paper authored by anyone named "Dongming Han"; it is a name-collision hub, not a single-author profile. `KNOWN_COAUTHORS` at `fetch_scholar.py:64` is the union of `_VAG_LAB` (Zhejiang University VAG group) and `_HITHINK` (Hithink/financial-AI co-authors); a paper is marked `confidence="high"` if any author appears in this union. By default, `confidence="low"` papers are **dropped**. When adding a new co-author, append to the matching sub-set so the grouping stays self-documenting.

To keep a low-confidence paper, add a substring of its title (≥ 12 chars; the merger warns on shorter keys because they substring-match many papers) to `data/publications_manual.json`:
```json
"include_low_confidence": ["SGCR: A Specification-Grounded Framework", ...]
```
To force-drop a paper, use the `exclude` list (same length warning applies). To bypass the confidence filter entirely while triaging, set `"keep_all_low_confidence": true` at the top level. To add a paper DBLP doesn't index at all (e.g., Chinese-venue papers), append to the `publications` array — these are merged on top.

A third per-record lever: any entry in the `publications` array of the manual file can set `"confidence": "high"` directly, which the override merge writes back onto the matched DBLP record (`fetch_scholar.py:764-765`). Every example in the existing manual file does this.

**Manual override field whitelist:** `merge_manual_overrides` only honours a fixed list of fields (`fetch_scholar.py:756-759`: `pdf_url`, `video_url`, `project_url`, `code_url`, `teaser_url`, `slides_url`, `appendix_url`, `doi`, `pub_url`, `venue`, `year`, `authors`, `author_position`, `title_zh`, `award`, `tldr`, `abstract`). Adding a new key (e.g. `bibtex`, `note`) to a manual entry won't propagate to `publications.json` until you add it to that whitelist. Top-level keys prefixed with `_` (e.g. `_comment`, `_filtering`, `_help_below`) and entries whose title starts with `example ` are ignored — use them for in-file documentation.

### Front-end (`index.html`)

Single file, all behavior in inline `<script>` starting at `index.html:801`. On load, `init()` parallel-fetches three files (no cache-buster — the head emits `<link rel="preload" as="fetch" href="data/publications.json">` so the same URL is reused; hard-refresh to see new data after running the pipeline):

- `data/publications.json` — generated by `fetch_scholar.py`; provides `author` + `publications`.
- `data/profile.json` — hand-edited; provides `bio`, `tagline`, `cta`, `selected`, `news`, `awards`, `patents`, `projects`, `experience`, `service`, and an `author_override` block that wins over `publications.json#author`.
- `data/profile.zh.json` — Chinese variant of the same shape; activated via the `中`/`EN` button (`toggleLang()`).

Bilingual rendering: `STRINGS` table at `index.html:811` holds UI labels; elements with `data-i18n="key"` get swapped on language toggle. The toggle swaps the entire profile object — there is no per-field fallback, so a `news` entry added only to the English file simply won't appear in Chinese mode.

The `selected` array in `profile.json` is matched to publication titles by case-insensitive substring (so `"Quantivine"` matches the full paper title). **Footgun:** each entry takes the FIRST matching publication; the renderer `console.warn`s when a key is < 4 chars or matches multiple papers, so watch DevTools.

Renderers (definition order): `renderSidebar`, `renderBio`, `renderCTA`, `renderNews`, `renderSelected`, `renderFilterBar`, `renderPublications`, `renderPub` (per-paper card builder, used by both `renderSelected` and `renderPublications`), `renderAwards`, `renderPatents`, `renderProjects`, `renderExperience`, `renderService`. `renderAll()` (`index.html:861`) calls them in DOM order: Sidebar, Bio, CTA, News, Experience, Selected, FilterBar, Publications, Projects, Awards, Service, Patents. Adding a renderer means deciding where in that sequence it belongs, not just appending. Each renderer must hide its `<section>` on empty data (set `display: none`) and show it (`display: ''` or `'block'`) on populated data — language toggle re-renders, so a stale empty section will linger if the renderer only handles one direction.

Two helpers worth knowing about:

- **`safeUrl(href)`** at `index.html:1364` — URL scheme allowlist (`http(s):`, `mailto:`, `tel:`, `#`, `/`, `./`, `../`, `assets/`). Any other scheme falls back to `#`. Every place a JSON-supplied URL becomes an `href` or `src` (sidebar links, CV button, CTA buttons, publication title links, `linkBtn`, awards URLs, teaser images) routes through it to block `javascript:` injection.
- **`injectJsonLd()`** at `index.html:1383` — builds Schema.org Person + up to 30 ScholarlyArticle entries from `DATA` and injects an `application/ld+json` script into `<head>` after data loads. Googlebot executes JS so this is indexable. If you change the author schema or want the JSON-LD to include more papers, edit this function (the slice limit is at `slice(0, 30)`).

Venue-tier highlighting uses regex constants `TIER1`/`TIER2` at the top of the script; self-author bolding uses `SELF_NAME_PATTERNS`. If the user changes their name or institution, those regexes need updating too.

The head also emits `<meta name="theme-color">` (light + dark variants), an author meta, OG/Twitter cards, and `<link rel="preload" as="image" href="assets/photo/photo.jpg" fetchpriority="high">`. The teaser images use `loading="lazy" decoding="async" fetchpriority="low"` so they don't compete with the photo for first paint.

### Assets folder (`assets/`)

Files dropped here are auto-linked to publications by **fuzzy filename match** (slugify → longest substring of paper title wins; year tokens are stripped wherever they sit, so `inet-2022.pdf`, `2022_inet.pdf`, `inet(2022).pdf` all reduce to `inet`). The matcher warns and skips when (a) the match covers < 25% of the filename slug, or (b) two papers tie for the best match — rename the file more specifically. A defensive `is_safe_asset()` check rejects filenames with non-ASCII/special characters and symlinks that escape `assets/`. See `assets/README.md` for canonical user-facing details. Folders declared at `fetch_scholar.py:74-85`:

- **URL-style** (`pdf/`, `video/`, `appendix/`, `slides/`, `teaser/`) — file path stored as `pdf_url`, etc.
- **Text-content** (`tldr/`, `abstract/`) — file body read into the publication record.

Plus a profile photo at `assets/photo/*.{jpg,jpeg,png,webp}` and a CV PDF at `assets/cv/*.pdf` (the first alphabetical match in each folder wins; convention is `photo.jpg` / `cv.pdf`), picked up by `find_local_photo` / `find_local_cv`.

**Precedence for asset-style fields** (`pdf_url`, `video_url`, etc.): an external URL set in `publications_manual.json` wins; otherwise the local file in `assets/<folder>/` is used. A previous local-asset path is overwritten by a newer matching file, but is *not* allowed to override an external manual URL.

## Deployment (GitHub Pages)

**See `DEPLOY.md` for the step-by-step deploy runbook.** Target URL is
`https://woaiwodib107.github.io/` (user site, served at the root); `robots.txt`,
`sitemap.xml`, and the `canonical`/`og:url`/`og:image` tags all hardcode that
URL — changing the repo name means updating those three places.

⚠️ **Never commit `.openclaw-yuanbao-backup/`** — it is an unrelated local folder
in this directory holding API credentials (`appKey`/`appSecret`). It is
gitignored; keep it that way. Also remember every file under `data/` becomes
world-readable once deployed, so no private contact details belong there.

The site is fully static. Nothing runs server-side at request time — `fetch_scholar.py` is a build-time tool that runs on the author's machine, and its output (`data/publications.json`) is committed to the repo so the browser can fetch it as a plain file.

**To deploy:**

1. Push the repo to GitHub. In `Settings → Pages`, point the source at `main` branch (root). GitHub will publish to `https://<user>.github.io/<repo>/` (or `https://<user>.github.io/` for the special `<user>.github.io` repo name).
2. `.nojekyll` (already in the repo root) tells Pages to skip the Jekyll build step — important so that any future `_`-prefixed file or directory isn't silently dropped.
3. `.gitignore` excludes `__pycache__/`, `*.log`, `*.bak`, and `.claude/settings.local.json` from the deploy.

**Editing loop in production:**

```bash
# locally
python3 fetch_scholar.py            # or --use-cache for content-only changes
git add data/publications.json assets/   # commit any updated PDFs/teasers/etc.
git commit -m "Refresh publications"
git push
# GitHub Pages picks it up within ~30s
```

The pipeline does NOT run on GitHub Actions by default — generated `publications.json` is committed by hand. If you want scheduled refreshes, add `.github/workflows/refresh.yml` that runs `python3 fetch_scholar.py` on a cron and commits the result; that's the only piece you'd need to make the data auto-update without manual pushes.

**A few GitHub Pages gotchas to keep in mind when editing:**

- All paths in `index.html` and JSON-supplied URLs are **relative** (`assets/photo/photo.jpg`, `data/publications.json`, etc.). Don't introduce absolute `/` paths — they'd break when deployed under `/<repo>/`.
- `<meta property="og:image">` is `assets/photo/photo.jpg` (relative). Most modern social-card crawlers resolve relative OG URLs correctly, but if richer cards matter, replace with an absolute `https://<user>.github.io/<repo>/assets/photo/photo.jpg` once the URL is known. Same for adding `<meta property="og:url">` and `<link rel="canonical">`.
- The page uses runtime `fetch()` for the three JSON files, which means Chrome **cannot** open `index.html` directly via `file://` — it blocks local-file fetches. On GitHub Pages this is irrelevant (HTTPS, same origin); locally use the http.server above or open in Safari.
- After running the pipeline locally, reload with hard-refresh (Ctrl/Cmd-Shift-R) — the cache-buster was removed so the browser may otherwise reuse a cached `publications.json`.

## Common editing flows

- **Fix a paper's metadata / add a missing paper** → edit `data/publications_manual.json` → `python3 fetch_scholar.py --use-cache`.
- **Update bio, news, awards, etc.** → edit BOTH `data/profile.json` AND `data/profile.zh.json` and keep them in lockstep (no per-field fallback) → reload (hard-refresh after pipeline runs); no script needed.
- **Add a PDF / teaser / video / slides** → drop the file into the matching `assets/` folder with a name containing a distinctive word from the paper title → `python3 fetch_scholar.py --use-cache`. Watch the console for `[assets] WARN: ambiguous` or `WARN: too generic` messages — those mean the file was skipped.
- **Layout / styling / new section** → edit `index.html` directly. CSS rules in the inline `<style>` are grouped by `/* ============== Foo ============== */` banner comments. HTML sections are plain `<section id="…">` elements; the renderer for each section fills in its body. Adding a section means: add `<section>`, add a renderer that hides on empty data, call it from `renderAll()`, add a nav link, and add i18n keys to both `STRINGS.en` and `STRINGS.zh`.
- **Refresh citation counts / pull new DBLP entries** → `python3 fetch_scholar.py` (full run; ~30–90 s).

In production (GitHub Pages → HTTPS, same origin) `fetch()` always works. Locally, Chrome blocks runtime `fetch()` for `file://` so use the HTTP server or open the page in Safari.
