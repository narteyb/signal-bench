# Post 1 OG Image

## What this is

This directory contains the Open Graph image for Post 1, "TinyML Reality Check: The Floor of the Curve." The PNG is the reference asset for the published post, and the HTML/CSS source makes the image reproducible.

The composition is intentionally sparse so the title survives mobile feed
thumbnailing and dense link previews.

## How to re-render

Run:

```bash
bash docs/post-1/og/render.sh
```

The script renders `index.html` at `1200x630` with Playwright and writes `tinyml-reality-check-og.png`. It also creates `preview-thumbnail.png` at `300x158` for thumbnail legibility review.

## How to edit

Edit `index.html`. Brand colors are CSS variables on `:root`; the Agoo AI signal mark and the small curve silhouette are inline SVG. Re-run `render.sh` after any text, layout, or SVG change.

## How to port

Publish `tinyml-reality-check-og.png` at the path named by the post front matter:

```text
/assets/blog/tinyml-reality-check-og.png
```

If the publishing asset pipeline fingerprints or relocates blog images, keep the final public path aligned with the post front matter: `/assets/blog/tinyml-reality-check-og.png`.

The template is intentionally reusable for Posts 2-5. Copy this directory, update the title/subtitle and any curve styling, then re-render.

## Validation

- Full-size PNG is exactly `1200x630`.
- Thumbnail preview keeps "TinyML Reality Check" legible.
- File size stays under `500KB`.
- No real Phase 5 data, MCU names, or benchmark numbers appear in the image.
- External OG validator check should be run after the post exists on agoo-ai.com.

## File sizes

Generated on 2026-05-11:

- `tinyml-reality-check-og.png`: 34KB (`34,385` bytes).
- `preview-thumbnail.png`: 14KB (`14,121` bytes).
