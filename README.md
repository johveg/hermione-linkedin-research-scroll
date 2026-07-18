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

The generator writes `index.html`, `manifest.json`, and selected images under `assets/posts/`.

## Intake publication

After a Telegram intake has written `metadata.json`, `post.txt`, and `intake-summary.md`, publish it by canonical activity ID:

```bash
python3 scripts/publish_from_linkedin_intake.py --activity-id <activity-id>
```

The publisher fails closed for incomplete archives or apparent secrets/private capture markers. For eligible intakes it rebuilds the page, stages only public generated artifacts, checks the staged diff, commits, pushes, and verifies `origin/main`. Re-running it is idempotent: it does not create a commit when the generated page is unchanged.
