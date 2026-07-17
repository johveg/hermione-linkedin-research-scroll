# Hermione LinkedIn Research Scroll

A single, newest-first GitHub Pages surface for public LinkedIn articles filed through `@al_hermoine_linkedin_bot`.

The site deliberately publishes only sanitized material:

- public/guest-visible post metadata and post text;
- locally archived post images;
- the research-oriented `intake-summary.md` assessment.

It deliberately excludes raw LinkedIn HTML, authenticated-page files/screenshots, browser/session data, and comments.

## Rebuild

On the Hermes host, rebuild from the intake archive:

```bash
python3 scripts/build_site.py
```

The generator writes `index.html`, `manifest.json`, and selected images under `assets/posts/`. Commit and push those generated static files to update GitHub Pages.
