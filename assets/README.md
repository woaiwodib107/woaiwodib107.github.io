# Assets — drop your files here

Files in these folders are **auto-linked** to publications by the homepage.
Filename matching is fuzzy: just name the file with the first significant word
of the paper title (case-insensitive, alphanumeric only).

## Folders

There are **two kinds** of folders:

### A. URL-style — file is served as a download/embed

| Folder            | Purpose                  | Shows up as       |
|-------------------|--------------------------|-------------------|
| `assets/pdf/`     | Paper PDFs               | `[PDF]` button    |
| `assets/video/`   | Demo videos (.mp4/.webm) | `[Video]` button  |
| `assets/appendix/`| Supplementary materials  | `[Appendix]`      |
| `assets/slides/`  | Talk slides (.pdf/.pptx) | `[Slides]`        |
| `assets/teaser/`  | Paper teaser images      | thumbnail in card |
| `assets/photo/`   | Profile photo            | sidebar avatar    |
| `assets/cv/`      | CV PDF                   | sidebar `CV` btn  |

### B. Content-style — file's TEXT is read into the card

| Folder              | Format       | Shows up as                              |
|---------------------|--------------|------------------------------------------|
| `assets/tldr/`      | `.txt`/`.md` | One-line italic summary above authors    |
| `assets/abstract/`  | `.txt`/`.md` | Click "Abstract" to expand the full text |

## Naming examples

For the paper "**iNet**: visual analysis of irregular transition…", any of these works:
```
assets/pdf/inet.pdf              ← PDF download
assets/teaser/inet.png           ← thumbnail
assets/tldr/inet.txt             ← one-liner
assets/abstract/inet.md          ← full abstract
```

For "**Quantivine**: A Visualization Approach for Large-scale Quantum Circuit…":
```
assets/pdf/quantivine.pdf
assets/video/quantivine.mp4
assets/slides/quantivine.pdf
assets/teaser/quantivine.jpg
assets/tldr/quantivine.txt
assets/abstract/quantivine.txt
```

The matcher takes the filename (without extension and trailing `-year`),
lowercases it, strips non-alphanumeric, and looks for it in any paper title.
The longest filename match wins, so `fraudauditor.pdf` will match
"FraudAuditor: A Visual Analytics Approach…" specifically.

## File format tips

- **TLDR** files: keep to one sentence (≤25 words). Markdown `**bold**` and
  `*italic*` are supported.
- **Abstract** files: any length. Use blank lines for paragraph breaks.
  Markdown `**bold**` and `*italic*` work; HTML is escaped.

## Profile photo

Save as `assets/photo/photo.jpg` (or `.png`/`.webp`). Square crop works best.

## CV

Save as `assets/cv/cv.pdf`. The orange `CV` button appears in the sidebar.

## After adding files

Run **either**:
```bash
python3 fetch_scholar.py --use-cache   # quick (no remote calls)
python3 fetch_scholar.py               # full refresh
```

The script rescans `assets/` every run.
