# The shared server

One box, one proxy, one directory per product. Set up once; every product after the first
is two commands and a DNS record.

```
1. brew install doctl                                     # once per laptop
2. token   → DIGITALOCEAN_ACCESS_TOKEN= in ~/.config/teyla/platform.env  (chmod 600)
3. bash provision-droplet.sh --yes                        # creates the droplet, prints its IP
4. host = "<ip>" in ~/.teyla/platform.toml                # so `teyla platform` stops asking
5. DNS: A record *.<your domain> → <ip>                   # Caddy gets the certificate itself
6. scp setup-server.sh Caddyfile root@<ip>:/root/
7. ssh root@<ip> 'bash /root/setup-server.sh'             # docker, ufw, deploy user, proxy
8. ssh deploy@<ip>                                        # root is done; never needed again
9. bash add-product.sh <name> <port> --domain <domain>    # from the product's checkout
10. teyla platform                                        # confirms the box answers
```

Each product repo ships three fragments in `deploy/droplet/`, which step 9 renders into
`/srv/<name>/`:

| fragment | becomes | holds |
|---|---|---|
| `docker-compose.fragment.yml` | `/srv/<name>/docker-compose.yml` | the service, on the shared `apps` network, no published ports |
| `Caddyfile.fragment` | `/srv/<name>/Caddyfile` | one site block: `<name>.<domain> { reverse_proxy <name>:<port> }` |
| `.env.example` | `/srv/<name>/.env` (mode 600) | the names the service reads; values filled in on the server |

`{{name}}`, `{{port}}` and `{{domain}}` are substituted; nothing else is touched, and a
file that already exists is kept, so hand-edits on the server survive a re-run.

**Why one box.** Long-running work — a poller, a queue worker, a scheduler — cannot live
in a serverless function and must not live on your laptop, which sleeps and travels. It
does not need one box per product: at this size the second product costs nothing but a
directory. Split when per-product metering says to, not before.

**What it does not host.** Accounts, per-user data and short server-side functions belong
with the identity provider in `platform.toml`, not here. A static site belongs on Pages.
This box is for the processes that must keep running.
