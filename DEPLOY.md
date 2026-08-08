# Deploying to GitHub Pages

The site is **fully static** — no build step, no server. GitHub Pages serves the
files in this repo exactly as they are.

Target URL: **https://woaiwodib107.github.io/**

## One-time setup

The repo must be named `woaiwodib107.github.io` for a user site served at the
root. (A different name makes it a *project* site served under a subpath, which
would require changing the absolute URLs — see "If you use a different repo
name" below.)

```bash
# 1. Create the repo on GitHub named exactly:  woaiwodib107.github.io
#    (github.com/new — Public, do NOT add a README/.gitignore/license)

# 2. Point this folder at it and push
git remote add origin https://github.com/woaiwodib107/woaiwodib107.github.io.git
git branch -M main
git push -u origin main
```

Then in **Settings → Pages**, set *Source* to **Deploy from a branch**, branch
`main`, folder `/ (root)`. The first build takes ~1 minute; afterwards updates
appear ~30 s after each push.

> `.nojekyll` is already committed, so Pages skips the Jekyll step and will not
> drop any `_`-prefixed file.

## Updating content later

```bash
# Refresh publications + citation metrics from DBLP / OpenAlex / Scholar
python3 fetch_scholar.py

# Regenerate the social-share card so its numbers match the new metrics
python3 make_og_card.py

git add -A
git commit -m "Refresh publications"
git push
```

For content-only edits (bio, news, awards — no network needed):

```bash
python3 fetch_scholar.py --use-cache && python3 make_og_card.py
```

**Always run `make_og_card.py` after the metrics change** — the citation numbers
are baked into `assets/og-card.jpg`, so skipping it leaves a stale social card.

## Local preview

```bash
python3 -m http.server 8081
```

Then open http://localhost:8081. Chrome cannot open `index.html` over `file://`
because the page fetches JSON at runtime. After re-running the pipeline,
hard-refresh (Cmd/Ctrl-Shift-R) — the browser caches the JSON files.

## What must never be committed

`.gitignore` already blocks these, but be aware:

- **`.openclaw-yuanbao-backup/`** — an unrelated local folder in this directory
  that contains API credentials (`appKey` / `appSecret`). It must never be
  published.
- `__pycache__/`, `.DS_Store`, `*.log`, `.claude/settings.local.json`.

Everything in `data/*.json` becomes **world-readable** once deployed (e.g.
`https://woaiwodib107.github.io/data/publications.json`). Do not put private
contact details there — a phone number was removed for this reason.

Sanity check before any push:

```bash
git status --short | grep -iE "openclaw|node_modules|\.env|settings\.local"
# → no output means you are clean
```

## If you use a different repo name

For a project site (`https://woaiwodib107.github.io/<repo>/`) update the three
absolute URLs — everything else on the page is already relative and needs no
change:

- `index.html`: `<link rel="canonical">`, `og:url`, `og:image`, `twitter:image`
- `robots.txt`: the `Sitemap:` line
- `sitemap.xml`: `<loc>` and the `hreflang` hrefs

## After it is live

- Submit `https://woaiwodib107.github.io/sitemap.xml` in
  [Google Search Console](https://search.google.com/search-console) to speed up
  indexing.
- Check the social card with the
  [OpenGraph debugger](https://www.opengraph.xyz/) — it should show the
  1200×630 card with your citation metrics.
