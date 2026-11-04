# review-channel

A write-only drop box for test-build feedback captures. Every product and platform PUTs its capture here; the owner's Mac moves the captures into the `teyla review` inbox once an hour and the server copy goes. Python 3 standard library only, one file, `server.py`.

A capture can show another person's data, so nothing can be read, listed or deleted over HTTP. Design and caps: [docs/REVIEW.md](../../docs/REVIEW.md), "The shared channel".

## Install

You need the shared server from `templates/platform` (Docker, Caddy, the external `apps` network) and SSH access as a user whose uid is 1000: the container runs as uid 1000, and the Mac reads and deletes what it writes.

1. **Make the folders** on the box, as that user. Run this before step 2, so Docker does not create them as root.

   ```sh
   mkdir -p /srv/review-channel/app /srv/review-channel/data/{ready,incoming,state,keys}
   chmod -R go-rwx /srv/review-channel/data
   chmod go+rx /srv/review-channel/data /srv/review-channel/data/keys
   ```

2. **Copy the service and start it.** From a checkout of this repo, copy `server.py` and `Dockerfile` into `/srv/review-channel/app/`, and these fragments to a temporary folder on the box together with `templates/platform/add-product.sh`. Then, on the box:

   ```sh
   bash add-product.sh review-channel 8080 --from <that folder> --domain <your domain>
   cd /srv && docker compose up -d --build review-channel
   docker compose logs --tail 5 review-channel     # "listening on 8080"
   ```

3. **Point DNS at the box.** `review.<your domain>`, an A record, DNS only. Caddy gets the certificate when the name resolves. Do this before step 2 on a new name, so the first attempt does not fail.

4. **Tell the Mac.** Create `~/.teyla/review-channel.toml`:

   ```toml
   ssh  = "user@host"             # the SSH login from the start of this page
   root = "/srv/review-channel/data"   # the data folder from step 1
   ```

5. **Make a key per product** on the Mac. It prints only where the secret is stored.

   ```sh
   teyla review channel key add myapp     # lowercase letters, digits and dashes
   teyla review channel key path myapp
   ```

   The product's `deliver` closure (or web overlay) sends `Authorization: Bearer <that key>` and puts the same slug in `app.product`. `teyla review channel key revoke myapp` ends it; the service reads its keys file again within a request of the change. A key shipped in a test build proves the build, not the person: anyone with the build can use it, which is why the caps below exist.

6. **Check, then switch on the hourly pull.**

   ```sh
   curl -fsS https://<your name>/healthz
   teyla review pull --channel            # exit 0, "0 new"
   teyla review channel install           # an hourly LaunchAgent; teyla schedules lists it
   ```

## The wire

| Request | Answer |
|---|---|
| `GET /healthz` | 200 |
| `PUT /v1/captures/<uuid>/capture.png` | 200 stored (or already delivered); 400 not a PNG; 401; 411 no Content-Length; 413 over 10 MiB; 422 picture does not match `screenshot.sha256`; 429 daily cap; 507 storage full; 503 busy |
| `PUT /v1/captures/<uuid>/capture.json` | the same, with 256 KiB; 400 unless `v` is 1, `id` equals the path and `screenshot.sha256` is there; 403 unless `app.product` equals the key's product |
| `OPTIONS` on those paths | 204, CORS for web builds: origin `*`, no credentials, methods PUT, headers `authorization` and `content-type` |
| anything else | 405 |

The UUID is lowercase. A capture is complete when both files are in and the picture matches the hash; it then moves, in one rename, from `incoming/<product>/<id>/` to `ready/<product>/<id>/`. A PUT for an id already in `ready` answers 200 and counts for nothing, so a client may retry freely.

## Caps

20 new captures per product and 100 in total per UTC day; `ready` plus `incoming` at most 500 MiB; at most 8 requests at once; a socket times out after 30 seconds. The counts are kept in `state/counters.json`, so a restart does not reset them. An `incoming` folder untouched for 24 hours is removed.

## Files

| File | Holds |
|---|---|
| `server.py` | the service |
| `Dockerfile` | a pinned `python:3.12-alpine` image, runs as uid 1000 |
| `docker-compose.fragment.yml` | the service, the `apps` network, 64 MB, the data and keys volumes |
| `Caddyfile.fragment` | the site block for `review.{{domain}}` |
| `keys/keys.txt` (on the box) | one `<sha256 of the key> <product>` per line; written by the Mac over SSH |

Tests: `tests/test_review_channel_server.py` in the repo root starts the service on a local port. Run it with `./check.sh`.
