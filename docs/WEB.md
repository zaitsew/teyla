# teyla web

`teyla web` opens a dashboard in your browser: what your agent sessions cost and the changes that fix it, what
waits on you today, your products, your notes and your spend. It is the terminal's commands laid out on a page.
It calls the same functions, so a figure on the page is the figure the command prints.

```bash
teyla web                  # opens the page; prints the address too
teyla web --no-open        # print the address, open nothing
teyla web --port 8800      # listen on this port instead of a free one
```

It listens on 127.0.0.1 only, and nothing leaves your machine. It stops on Ctrl-C, and on its own after two hours
with no request. It has no npm step, no CDN and no web fonts: the page is three files in the package.

## What it shows

| Tab | Shows | Same as |
|---|---|---|
| Start | The diagnosis card (total at list price, share spent on context, long sessions, subagents, questions waiting) and the seven offers. Apply asks once, in words that name the file and the key it will change. Undo reverts it. | `teyla start`, `teyla apply`, `teyla undo`, `teyla changes` |
| Today | The one next step, the questions waiting on you by product, the Inbox, this week's spend. | `teyla today` |
| Products | Every product: stage, focus, questions waiting, notes. A product page lists its questions, notes (with a form to add one), recent sessions with their cost, repos and primary platform. | `teyla product`, `teyla asks`, `teyla notes` |
| Notes | Add a note (Pick for me, Inbox or a product), link it to a product, drop it, bring it back. | `teyla note`, `teyla notes` |
| Spend | This week against the one before, by day, by model and by product, at API list price. Plain numbers and inline-SVG bars; no chart library. | `teyla spend` |

The diagnosis takes from 5 to 60 seconds on a large machine. The page opens at once with the last count (kept in
`~/.teyla/web-cache.json`, mode 0600) marked "Refreshing", and fills in when the new count is done. An Apply or an
Undo starts a new count.

An offer that ran one of Teyla's own syncs (O5 to O7) has no targeted undo. The Undo button shows the message the
command line prints: Teyla's sync owns those files, and `teyla uninstall` removes them. An Undo after a setting
changed since offers "Revert anyway", which is `teyla undo --force`.

## The security model

Anything on your machine can open a port. These rules keep other pages and other processes out:

1. **127.0.0.1 only.** The socket is never bound to 0.0.0.0, and the port is random unless you pin it.
2. **A token per run.** 32 random bytes, in the address `teyla web` prints. The first request swaps the token for
   an HttpOnly, SameSite=Strict cookie and redirects, so the token leaves the address bar and the history. Without
   the cookie every request is a 403.
3. **A Host allowlist.** Only `127.0.0.1:<port>` and `localhost:<port>` are answered. A page on another site that
   points its own name at 127.0.0.1 (DNS rebinding) is refused.
4. **A POST needs the token again**, in an `X-Teyla-Token` header that only the served page can read, and an
   `Origin` (when sent) that names this server. The body is a JSON object of at most 64 KB. There are no CORS
   headers, so another site cannot read a response or send that header.
5. **A strict policy on the page.** `script-src 'self'; style-src 'self'`, no inline script or style, no frames,
   `no-store`, `nosniff`. Text from a note, a session or a file reaches the page as text, never as markup.

Apply and Undo write only what `teyla apply` and `teyla undo` write, after the same 0600 backup, and one at a time.
They need `"confirm": true` in the request, so a request that skips the page's confirmation step is refused.

## The API

The page is the only client this supports. Errors are JSON, `{"error": "<one sentence>"}`, with a 4xx or 5xx.

| Route | Does |
|---|---|
| `GET /api/start` | The cached diagnosis, `refreshing`, and the offers with `applies`, `applied` (the active change, if any), `confirm` (the sentence Apply asks) and the last changes. |
| `GET /api/today` | The `teyla today --json` snapshot. |
| `GET /api/products` | The product list with stage, focus, waiting and note counts, and the Inbox count. |
| `GET /api/products/<id>` | One product: questions, notes, recent sessions and spend, repos and primary. 404 for an unknown id. |
| `GET /api/notes[?all=1&product=<id>]` | Notes, newest first, and the products a note can be linked to. |
| `GET /api/spend` | This week and last, by day, model and product, and whether a recount is running. |
| `POST /api/apply` | `{"offer": "O1", "confirm": true}` makes one change. 409 when there is nothing to do. |
| `POST /api/undo` | `{"ref": "O1" or a change id, "force": false}`. 409 carries the message and `can_force`. |
| `POST /api/refresh` | `{"what": "start" or "spend"}` starts a recount in the background (202). |
| `POST /api/notes` | `{"text": "...", "product": "<id>" or "inbox" (optional)}` keeps a note (201). |
| `POST /api/notes/<id>/link` | `{"product": "<id>" or "inbox"}` |
| `POST /api/notes/<id>/drop` · `undrop` | Drops a note, or brings it back. |

## Design

The page uses the brand tokens (`brand/tokens.json`) as CSS variables, in light and dark by the system setting. The
test suite fails when the stylesheet's colours drift from the tokens. Every control is reachable by keyboard and
shows its focus. The layout works from 800 px wide up. Numbers come first; an empty section says what to do next.
