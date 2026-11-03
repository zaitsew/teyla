# teyla.dev

The public site: the landing page, `/privacy/` and `/support/`. Plain HTML, CSS and one small script, with no build step.

```bash
./site/deploy.sh     # publishes site/public to teyla.dev
```

`deploy.sh` needs a wrangler login on the machine (`npx wrangler login`, once). It runs by hand, after a merge. There is no deploy on push.

## Hosting

Cloudflare Workers static assets on the free plan, in the owner's account. There is no Worker script, so requests are free and unmetered. `wrangler.jsonc` creates the DNS records and certificates for `teyla.dev` and `www.teyla.dev`.

## Rules

- **No telemetry.** No analytics, cookies, web fonts or files from another host. `_headers` sets a strict Content-Security-Policy.
- **Tokens only.** Colours, type and spacing live in `assets/tokens.css`, which mirrors `brand/tokens.json`. `site.css` uses them and adds no literals. Three type sizes: title, head, body.
- **Say what is true today.** The apps are not on sale, so the page links to no store. Sample numbers are labelled as sample.

`tests/test_site.py` checks all of these, and that the commands on the page match the README.
