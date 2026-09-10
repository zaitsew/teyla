# deploy/droplet

Three fragments. They are not a deployment on their own — the shared server's
`add-product.sh` renders them into `/srv/{{name}}/` and starts the stack:

```bash
# on the server, from a checkout of this repo
bash add-product.sh {{name}} <port> --domain <your domain>
```

`{{name}}`, `{{port}}` and `{{domain}}` are the only placeholders substituted. A file that
already exists on the server is kept, so hand-edits there survive a re-run.

Put here only what must keep running: a poller, a queue worker, a scheduler. Accounts,
per-user data and short server-side functions belong with the identity provider; a static
front end belongs on Pages. See `templates/platform/README.md` in the teyla repo for the
whole runbook.
