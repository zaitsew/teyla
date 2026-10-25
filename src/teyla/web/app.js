/* Teyla web. No framework, no build step, no network except this server. Every string from the API is
   put in the page with textContent, never as HTML. The figures are the server's; this file only lays them out. */
"use strict";
(() => {
  const TOKEN = document.querySelector('meta[name="teyla-token"]').content;
  const view = document.getElementById("view");
  const SVGNS = "http://www.w3.org/2000/svg";

  // --- small helpers ---------------------------------------------------------------------------

  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") e.className = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat(Infinity)) {
      if (c === null || c === undefined || c === false) continue;
      e.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return e;
  }

  function sv(tag, attrs, ...kids) {
    const e = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) e.setAttribute(k, v);
    for (const c of kids.flat(Infinity)) if (c !== null && c !== undefined) e.append(c.nodeType ? c : document.createTextNode(String(c)));
    return e;
  }

  const money = (x) => (x >= 10 ? "$" + Math.round(x).toLocaleString("en-US") : "$" + x.toFixed(2));
  const pct = (x) => Math.round(x * 100) + "%";
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function ageS(s) {
    if (s < 0) return "in " + Math.floor(-s / 86400) + "d";
    if (s < 3600) return Math.floor(s / 60) + "m";
    if (s < 48 * 3600) return Math.floor(s / 3600) + "h";
    return Math.floor(s / 86400) + "d";
  }

  function ago(iso) {
    if (!iso) return "";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    return s < 60 ? "just now" : ageS(s) + " ago";
  }

  function range(o) {
    const s = o.saving_usd_month;
    const lo = money(s.low), hi = money(s.high);
    return lo === hi ? hi : lo + "-" + hi;
  }

  function changePct(p) {
    return p === null || p === undefined ? "" : (p > 0 ? "+" : "") + p + "%";
  }

  const cap = (text) => text.charAt(0).toUpperCase() + text.slice(1);

  class ApiErr extends Error {
    constructor(message, status, body) {
      super(message);
      this.status = status;
      this.body = body || {};
    }
  }

  async function api(method, path, body) {
    const opt = { method, headers: {} };
    if (method !== "GET") {
      opt.headers["Content-Type"] = "application/json";
      opt.headers["X-Teyla-Token"] = TOKEN;
      opt.body = JSON.stringify(body || {});
    }
    let r;
    try {
      r = await fetch(path, opt);
    } catch (e) {
      throw new ApiErr("Teyla web has stopped. Start it again with `teyla web`.", 0);
    }
    let j = null;
    try { j = await r.json(); } catch (e) { /* not JSON */ }
    if (!r.ok) throw new ApiErr((j && j.error) || "The request failed (" + r.status + ").", r.status, j);
    return j;
  }

  function strip(kind, ...kids) {
    return h("div", { class: "strip " + kind, role: kind === "error" || kind === "warn" ? "alert" : "status" }, ...kids);
  }

  function failure(e, retry) {
    return strip("error", h("span", null, e.message), retry ? h("button", { class: "btn", onclick: retry }, "Try again") : null);
  }

  function empty(title, text, ...more) {
    return h("div", { class: "empty" }, h("strong", null, title), text, ...more);
  }

  function code(text) { return h("code", null, text); }

  // An ask's link is a URL (open it) or a command to run in a terminal (show it, never link it).
  function askLink(link) {
    if (!link) return null;
    if (/^(https?|claude):\/\//.test(link)) return h("span", { class: "cap" }, " ", h("a", { href: link, rel: "noopener" }, "open session"));
    return h("span", { class: "cap" }, " ", code(link));
  }

  // --- routing ---------------------------------------------------------------------------------

  let generation = 0;           // a view that was left stops polling

  function parse() {
    const raw = decodeURIComponent((location.hash || "#start").slice(1));
    const i = raw.indexOf("/");
    return i < 0 ? [raw, ""] : [raw.slice(0, i), raw.slice(i + 1)];
  }

  function show(...nodes) {
    view.replaceChildren(...nodes.flat(Infinity).filter((n) => n !== null && n !== undefined && n !== false));
  }

  function restoreFocus(key) {
    if (!key) return;
    const el = view.querySelector('[data-focus="' + key + '"]');
    if (el) el.focus();
  }

  async function render() {
    const [tab, arg] = parse();
    const gen = ++generation;
    for (const a of document.querySelectorAll("#tabs a")) {
      if (a.dataset.tab === tab) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    }
    const views = { start: startView, today: todayView, products: productsView, notes: notesView, spend: spendView };
    const fn = views[tab] || startView;
    document.title = (views[tab] ? cap(tab) : "Start") + " - Teyla";
    try {
      await fn(arg, gen);
    } catch (e) {
      if (gen === generation) show(h("h1", null, cap(tab)), failure(e, render));
    }
  }

  window.addEventListener("hashchange", () => { render(); view.focus({ preventScroll: true }); });

  // --- Start -----------------------------------------------------------------------------------

  async function startView(_, gen) {
    const ui = {};               // per offer: {confirming, busy, msg: {kind, text, force}}
    let data = await api("GET", "/api/start");
    let sig = "";
    let focusKey = null;

    function refreshStrip() {
      if (data.refreshing && !data.diagnosis) {
        return strip("", h("span", null, "Reading your sessions", h("span", { class: "dots" }), " The first count takes up to a minute on a large machine. Nothing leaves this Mac."));
      }
      if (data.refreshing) {
        return strip("", h("span", null, "Refreshing", h("span", { class: "dots" }), " Showing the count from " + ago(data.at) + "."));
      }
      if (data.error) return failure(new Error(data.error), refresh);
      return h("p", { class: "cap" }, data.at ? "Counted " + ago(data.at) + ". " : "",
        h("button", { class: "btn quiet", onclick: refresh }, "Refresh"));
    }

    async function refresh() {
      try { await api("POST", "/api/refresh", { what: "start" }); } catch (e) { data.error = e.message; }
      data.refreshing = true;
      draw();
      poll();
    }

    async function poll() {
      while (gen === generation) {
        await sleep(2000);
        if (gen !== generation) return;
        try { data = await api("GET", "/api/start"); } catch (e) { return; }
        const now = JSON.stringify([data.at, data.refreshing, data.error]);
        if (now !== sig) draw();
        if (!data.refreshing) return;
      }
    }

    function tiles(d) {
      const t = (num, lbl, cls) => h("div", { class: "stat" }, h("div", { class: "num " + (cls || "") }, num), h("div", { class: "lbl" }, lbl));
      const out = [
        t(pct(d.context_share), "of spend was re-reading or storing context (" + money(d.context_usd) + ")"),
        t(String(d.long_sessions), "sessions ran past " + Math.round(d.long_context_tokens / 1000) + "k tokens (" + money(d.long_sessions_usd) + ")"),
      ];
      if (d.subagent_usd) out.push(t(money(d.subagent_usd), "went to subagents; Opus ran " + pct(d.subagent_opus_share) + " of it"));
      out.push(t(String(d.waiting_asks), "questions are waiting on you", d.waiting_asks ? "needs" : ""));
      return h("div", { class: "stats" }, out);
    }

    function summary() {
      const d = data.diagnosis;
      if (!d) {
        return [h("h1", null, "Start"), h("p", { class: "sub" }, "Teyla reads your Claude Code and Codex sessions on this Mac, shows what they cost, and fixes the waste. Nothing leaves your machine.")];
      }
      if (d.empty) {
        return [h("h1", null, "Start"),
          empty("No sessions yet", "Use Claude Code or Codex for a day, then refresh. Teyla looks in ~/.claude and ~/.codex.")];
      }
      const by = Object.entries(d.by_harness).slice(0, 3).map(([k, v]) => k + " " + money(v)).join(", ");
      return [
        h("h1", null, money(d.total_usd) + " in the last " + d.days + " days"),
        h("p", { class: "sub" }, "At API list price, over " + d.sessions + " sessions on " + d.active_days + " days" + (by ? " (" + by + ")" : "") + ". " + d.note),
        tiles(d),
      ];
    }

    function offerCard(o) {
      const st = ui[o.id] || (ui[o.id] = {});
      const applied = o.applied;
      const saving = o.saving_usd_month
        ? [h("dt", null, "Saving"), h("dd", null, h("span", { class: "saving" }, "About " + range(o) + " a month"), " at list price. " + o.basis)]
        : [h("dt", null, "Brings"), h("dd", null, o.benefit + (o.basis ? " " + o.basis : ""))];
      const head = h("div", { class: "offer-head" },
        h("span", { class: "offer-id" }, o.id), h("h3", null, o.title),
        applied ? h("span", { class: "tag saving" }, "Applied " + ago(applied.at)) : (o.saving_usd_month ? h("span", { class: "tag saving" }, "about " + range(o) + " a month") : null));
      const card = h("section", { class: "card", "aria-label": o.id + " " + o.title }, head,
        h("dl", { class: "facts" },
          h("dt", null, "Change"), h("dd", null, o.change.summary),
          saving,
          h("dt", null, "Trade-off"), h("dd", null, o.tradeoff),
          h("dt", null, "Undo"), h("dd", null, o.undo)),
        h("details", { class: "group" }, h("summary", null, "Explain"), h("p", null, o.explain)));
      const actions = h("div", { class: "actions" });
      if (applied) {
        actions.append(h("button", { class: "btn", "data-focus": "undo-" + o.id, disabled: st.busy, onclick: () => undo(o) }, "Undo"));
        if (!applied.undoable) actions.append(h("span", { class: "cap" }, "Teyla's own sync made this change; see what Undo says."));
      } else if (st.confirming) {
        card.append(h("div", { class: "confirm", role: "group", "aria-label": "Confirm " + o.id },
          h("strong", null, "Make this change?"), h("p", null, o.confirm),
          h("div", { class: "actions" },
            h("button", { class: "btn primary", "data-focus": "confirm-" + o.id, disabled: st.busy, onclick: () => apply(o) }, "Make this change"),
            h("button", { class: "btn", disabled: st.busy, onclick: () => { st.confirming = false; draw("apply-" + o.id); } }, "Cancel"))));
      } else {
        actions.append(h("button", { class: "btn primary", "data-focus": "apply-" + o.id, onclick: () => { st.confirming = true; draw("confirm-" + o.id); } }, "Apply"));
      }
      if (actions.childNodes.length) card.append(actions);
      if (st.msg) {
        card.append(h("div", { class: "strip " + st.msg.kind, role: st.msg.kind === "error" ? "alert" : "status" },
          h("span", null, st.msg.text),
          st.msg.force ? h("button", { class: "btn", onclick: () => undo(o, true) }, "Revert anyway") : null));
      }
      return card;
    }

    async function apply(o) {
      const st = ui[o.id];
      st.busy = true; draw("confirm-" + o.id);
      try {
        const r = await api("POST", "/api/apply", { offer: o.id, confirm: true });
        st.confirming = false;
        st.msg = { kind: "ok", text: (r.lines || []).join(" ") + (r.undoable ? "" : " " + r.undo) };
      } catch (e) {
        st.msg = { kind: "error", text: e.message };
      }
      st.busy = false;
      data = await api("GET", "/api/start").catch(() => data);
      draw("undo-" + o.id);
      if (data.refreshing) poll();
    }

    async function undo(o, force) {
      const st = ui[o.id];
      st.busy = true; st.msg = null; draw("undo-" + o.id);
      try {
        const r = await api("POST", "/api/undo", { ref: o.applied.id, force: !!force });
        st.msg = { kind: "ok", text: "Undone. " + (r.lines || []).join(" ") };
      } catch (e) {
        // The refusal is the answer: an offer that ran a sync has no targeted undo, and a key that changed since needs a decision.
        st.msg = { kind: "warn", text: e.message, force: !!(e.body && e.body.can_force) };
      }
      st.busy = false;
      data = await api("GET", "/api/start").catch(() => data);
      draw("undo-" + o.id);
      if (data.refreshing) poll();
    }

    function offers() {
      const all = data.offers;
      if (!all.length) return [];
      const todo = all.filter((o) => o.applies && !o.applied);
      const done = all.filter((o) => o.applied);
      const rest = all.filter((o) => !o.applies && !o.applied);
      const out = [];
      if (todo.length) out.push(h("h2", null, todo.length === 1 ? "1 change to consider" : todo.length + " changes to consider"), todo.map(offerCard));
      else if (!data.diagnosis.empty) out.push(h("h2", null, "No changes to suggest"), h("p", { class: "muted" }, "Your settings already match what Teyla would change."));
      if (done.length) out.push(h("h2", null, "Applied"), done.map(offerCard));
      if (rest.length) {
        const row = (o) => h("li", null, h("span", { class: "offer-id" }, o.id),
          h("span", { class: "grow" }, o.title, h("div", { class: "cap" }, cap(o.reason || "not available"))));
        out.push(h("details", { class: "group" }, h("summary", null, "Already in place or not available (" + rest.length + ")"),
          h("ul", { class: "list" }, rest.map(row))));
      }
      return out;
    }

    function draw(focus) {
      if (gen !== generation) return;
      sig = JSON.stringify([data.at, data.refreshing, data.error]);
      const d = data.diagnosis;
      show(...summary(), refreshStrip(), d && !d.empty ? offers() : [],
        d && !d.empty ? h("p", { class: "cap" }, "Every change keeps a backup, and ", code("teyla changes"), " lists them. Apply and Undo here call the same code as ", code("teyla apply"), " and ", code("teyla undo"), ".") : null);
      restoreFocus(focus || focusKey);
    }

    draw();
    if (data.refreshing) poll();
  }

  // --- Today -----------------------------------------------------------------------------------

  async function todayView(_, gen) {
    let snap = await api("GET", "/api/today");
    let tries = 0;

    function nextCard(s) {
      const links = { offer: ["#start", "Open Start"], inbox: ["#notes", "Open Notes"] };
      const l = links[s.kind];
      return h("section", { class: "card", "aria-label": "Next" },
        h("div", { class: "cap" }, "Next"), h("p", { class: "lead" }, s.text),
        s.command ? h("div", { class: "actions" }, code(s.command), l ? h("a", { class: "btn", href: l[0] }, l[1]) : null) : null);
    }

    function questions(q) {
      if (!q.waiting) return [h("h2", null, "Waiting on you"), empty("Nothing is waiting on you", "A question an agent session leaves for you shows up here.")];
      const groups = q.products.map((g) => {
        const first = g.asks.slice(0, 3), more = g.asks.slice(3);
        const row = (a) => h("li", null,
          h("span", { class: "grow" }, a.critical ? h("span", { class: "tag needs" }, "critical") : null, a.critical ? " " : "", a.question,
            askLink(a.link)),
          h("span", { class: "age" }, ageS(a.age_s)));
        return h("section", { class: "card group", "aria-label": g.name },
          h("div", { class: "group-head" }, h("a", { href: "#products/" + encodeURIComponent(g.product) }, g.name),
            h("span", { class: "needs" }, g.count + " waiting"), g.stage ? h("span", { class: "tag" }, g.stage) : null, g.focus ? h("span", { class: "tag primary" }, "focus") : null),
          h("ul", { class: "list" }, first.map(row)),
          more.length ? h("details", null, h("summary", null, "+" + more.length + " more"), h("ul", { class: "list" }, more.map(row))) : null);
      });
      return [h("h2", null, q.waiting + (q.waiting === 1 ? " question" : " questions") + " waiting on you in " + q.products.length + (q.products.length === 1 ? " product" : " products")), groups];
    }

    function inbox(n) {
      if (!n.inbox) return [h("h2", null, "Inbox"), h("p", { class: "muted" }, "Empty. ", h("a", { href: "#notes" }, "Add a note"), " when an idea comes up.")];
      return [h("h2", null, "Inbox: " + n.inbox + (n.inbox === 1 ? " note" : " notes") + " with no product yet"),
        h("section", { class: "card" }, h("ul", { class: "list" }, n.newest.map((x) => h("li", null, h("span", { class: "grow" }, x.text), h("span", { class: "age" }, ageS(x.age_s))))),
          h("div", { class: "actions" }, h("a", { class: "btn", href: "#notes" }, "File them under a product")))];
    }

    function spend(s, sessions) {
      if (!sessions) return [h("h2", null, "Spend"), empty("No sessions yet", "Use Claude Code or Codex for a day. The cost of your sessions shows up here.")];
      if (!s) return [h("h2", null, "Spend"), strip("", h("span", null, "Counting two weeks of sessions", h("span", { class: "dots" }), " The first count takes up to a minute."))];
      return [h("h2", null, "Spend"),
        h("div", { class: "stats" },
          h("div", { class: "stat" }, h("div", { class: "num" }, money(s.this_week)), h("div", { class: "lbl" }, "last 7 days, API list price")),
          h("div", { class: "stat" }, h("div", { class: "num" }, money(s.last_week)), h("div", { class: "lbl" }, "the 7 days before" + (s.change_pct === null ? "" : " (" + changePct(s.change_pct) + " now)")))),
        s.note ? h("p", { class: "cap" }, s.note) : null,
        h("p", null, h("a", { href: "#spend" }, "By model and by product"))];
    }

    function draw() {
      if (gen !== generation) return;
      const day = new Date(snap.generated).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
      show(h("h1", null, "Today"), h("p", { class: "sub" }, day),
        snap.sessions ? null : strip("warn", h("span", null, "No agent sessions found yet. Use Claude Code or Codex for a day.")),
        nextCard(snap.suggestion), questions(snap.questions), inbox(snap.notes), spend(snap.spend, snap.sessions));
    }

    draw();
    // The spend comes from a cache that a background job fills; look again until it is there.
    while (gen === generation && snap.sessions && !snap.spend && tries++ < 30) {
      await sleep(4000);
      if (gen !== generation) return;
      try { snap = await api("GET", "/api/today"); draw(); } catch (e) { return; }
    }
  }

  // --- Products --------------------------------------------------------------------------------

  async function productsView(arg, gen) {
    if (arg) return productView(arg, gen);
    const d = await api("GET", "/api/products");
    if (gen !== generation) return;
    if (!d.products.length) {
      show(h("h1", null, "Products"), empty("No products yet", "Teyla groups your sessions, questions and notes by product. ", code("teyla product init"), " proposes them from your repos."));
      return;
    }
    const row = (p) => h("tr", null,
      h("td", null, h("a", { href: "#products/" + encodeURIComponent(p.id) }, p.name), p.registered ? null : h("span", { class: "cap" }, " not registered"),
        p.focus ? [" ", h("span", { class: "tag primary" }, "focus")] : null),
      h("td", null, p.stage ? h("span", { class: "tag" }, p.stage) : h("span", { class: "muted" }, "-")),
      h("td", { class: "n" }, p.waiting ? h("span", { class: "needs" }, p.waiting) : "0", p.muted ? h("span", { class: "cap" }, " +" + p.muted + " muted") : null),
      h("td", { class: "n" }, String(p.notes)));
    show(h("h1", null, "Products"),
      h("p", { class: "sub" }, d.products.length + (d.products.length === 1 ? " product" : " products") + ". Focus first, then by what waits on you."),
      h("section", { class: "card" }, h("table", null,
        h("thead", null, h("tr", null, h("th", null, "Product"), h("th", null, "Stage"), h("th", { class: "n" }, "Waiting"), h("th", { class: "n" }, "Notes"))),
        h("tbody", null, d.products.map(row)))),
      d.inbox ? h("p", { class: "muted" }, d.inbox + (d.inbox === 1 ? " note has" : " notes have") + " no product yet. ", h("a", { href: "#notes" }, "File them")) : null);
  }

  async function productView(id, gen) {
    let p = await api("GET", "/api/products/" + encodeURIComponent(id));
    let notesData = null;

    async function draw() {
      if (gen !== generation) return;
      // The page is drawn again while the spend is counted: keep what is typed in the note box.
      const box = document.getElementById("note-text");
      const draft = box ? box.value : "", typing = box === document.activeElement;
      const sp = p.spend;
      const spendNum = sp ? money(sp.this_week) : "-";
      const stats = h("div", { class: "stats" },
        h("div", { class: "stat" }, h("div", { class: "num " + (p.asks.length ? "needs" : "") }, String(p.asks.filter((a) => !a.muted).length)), h("div", { class: "lbl" }, "questions waiting")),
        h("div", { class: "stat" }, h("div", { class: "num" }, String(p.notes.length)), h("div", { class: "lbl" }, "open notes")),
        h("div", { class: "stat" }, h("div", { class: "num" }, spendNum), h("div", { class: "lbl" }, sp ? "last 7 days, list price (" + money(sp.last_week) + " the 7 before)" : (p.spend_refreshing || !p.spend_error ? "last 7 days, list price: counting" : "last 7 days, list price"))));
      const asks = p.asks.length
        ? h("section", { class: "card" }, h("ul", { class: "list" }, p.asks.map((a) => h("li", null,
          h("span", { class: "grow" }, a.critical ? h("span", { class: "tag needs" }, "critical") : null, a.critical ? " " : "", a.muted ? h("span", { class: "tag" }, "muted") : null, a.muted ? " " : "",
            a.question || a.title, askLink(a.link)),
          h("span", { class: "age" }, ageS(a.age_s))))))
        : empty("Nothing is waiting on you", "A question an agent session leaves for this product shows up here.");
      const noteList = p.notes.length
        ? h("section", { class: "card" }, h("ul", { class: "list" }, p.notes.map((n) => h("li", null, h("span", { class: "grow pre" }, n.text), h("span", { class: "age" }, ago(n.created).replace(" ago", ""))))))
        : null;
      let sessions;
      if (p.sessions.length) {
        sessions = h("section", { class: "card" }, h("table", null,
          h("thead", null, h("tr", null, h("th", null, "Session"), h("th", null, "Harness"), h("th", null, "Last active"), h("th", { class: "n" }, "Cost, 14 days"))),
          h("tbody", null, p.sessions.map((s) => h("tr", null, h("td", null, code(s.sid)), h("td", null, s.harness), h("td", null, ago(s.last)), h("td", { class: "n" }, money(s.usd)))))));
      } else if (p.spend_refreshing || (!p.spend && !p.spend_error)) {
        sessions = strip("", h("span", null, "Counting recent sessions", h("span", { class: "dots" })));
      } else if (p.spend_error) {
        sessions = failure(new Error(p.spend_error), null);
      } else {
        sessions = empty("No sessions in the last 14 days", "Work on this product with Claude Code or Codex, and its sessions and cost appear here.");
      }
      const facts = h("section", { class: "card" }, h("dl", { class: "facts" },
        h("dt", null, "Primary"), h("dd", null, p.primary || "not set"),
        h("dt", null, "Stage"), h("dd", null, p.stage || "not set"),
        h("dt", null, "Repos"), h("dd", null, p.repos.length ? p.repos.map((r) => h("div", null, code(r))) : ["None registered. ", code("teyla product set " + p.id + " add-repo=PATH")]),
        p.paths.length ? [h("dt", null, "Paths"), h("dd", null, p.paths.map((r) => h("div", null, code(r))))] : null,
        p.aliases.length ? [h("dt", null, "Also called"), h("dd", null, p.aliases.join(", "))] : null));
      show(h("a", { class: "back", href: "#products" }, "All products"),
        h("h1", null, p.name),
        h("p", { class: "sub" }, p.stage ? h("span", { class: "tag" }, p.stage) : null, " ", p.focus ? h("span", { class: "tag primary" }, "focus") : null, " ", p.registered ? null : h("span", { class: "tag" }, "not registered")),
        stats,
        h("h2", null, "Waiting on you"), asks,
        h("h2", null, "Notes"), noteList, noteForm({ product: p.id, candidates: null, onAdded: reload }),
        h("h2", null, "Recent sessions"), sessions,
        h("h2", null, "Repos and platform"), facts);
      const again = document.getElementById("note-text");
      if (again && draft) again.value = draft;
      if (again && typing) again.focus();
    }

    async function reload() {
      p = await api("GET", "/api/products/" + encodeURIComponent(id));
      draw();
    }

    draw();
    let tries = 0;
    while (gen === generation && (p.spend_refreshing || (!p.spend && !p.spend_error)) && tries++ < 40) {
      await sleep(3000);
      if (gen !== generation) return;
      try { p = await api("GET", "/api/products/" + encodeURIComponent(id)); draw(); } catch (e) { return; }
    }
  }

  // --- Notes -----------------------------------------------------------------------------------

  const HOW = { owner: "you chose it", text: "named in the text", cwd: "from the directory", "": "no product matched" };

  /* The form that adds a note. `product` fixes the product; without it the choice is "Pick for me" (the
     product the text names, else the Inbox) or any registered product. */
  function noteForm({ product, candidates, onAdded }) {
    const ta = h("textarea", { id: "note-text", "aria-label": "Note", placeholder: "An idea, kept as you type it" });
    const sel = candidates
      ? h("select", { id: "note-product", "aria-label": "Product" },
        h("option", { value: "" }, "Pick for me"), h("option", { value: "inbox" }, "Inbox"),
        candidates.map((c) => h("option", { value: c.id }, c.name)))
      : null;
    const msg = h("div", { "aria-live": "polite" });
    async function add() {
      const text = ta.value.trim();
      if (!text) { msg.replaceChildren(strip("warn", "Write the note first.")); ta.focus(); return; }
      btn.disabled = true;
      try {
        const body = { text };
        const choice = product || (sel && sel.value);
        if (choice) body.product = choice;
        const n = await api("POST", "/api/notes", body);
        ta.value = "";
        msg.replaceChildren(strip("ok", "Kept in " + (n.product === "inbox" ? "the Inbox" : n.product) + " (" + HOW[n.linked_by] + ")."));
        if (onAdded) await onAdded(n);
      } catch (e) {
        msg.replaceChildren(failure(e, null));
      }
      btn.disabled = false;
    }
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); add(); } });
    const btn = h("button", { class: "btn primary", onclick: add }, "Add note");
    return h("section", { class: "card" }, h("label", { for: "note-text" }, "New note"), ta,
      h("div", { class: "form-row" }, sel ? h("div", null, h("label", { for: "note-product" }, "Product"), sel) : null, btn,
        h("span", { class: "cap" }, "Cmd+Enter adds it")), msg);
  }

  async function notesView(_, gen) {
    let showDropped = false;
    let data = await api("GET", "/api/notes");

    async function reload() {
      data = await api("GET", "/api/notes" + (showDropped ? "?all=1" : ""));
      draw();
    }

    function noteRow(n) {
      const sel = h("select", { "aria-label": "Product for this note" },
        h("option", { value: "inbox" }, "Inbox"), data.candidates.map((c) => h("option", { value: c.id }, c.name)));
      sel.value = n.product;
      if (sel.value !== n.product) sel.append(h("option", { value: n.product }, n.product)), sel.value = n.product;
      const msg = h("div", { "aria-live": "polite" });
      async function act(path, body) {
        try { await api("POST", "/api/notes/" + encodeURIComponent(n.id) + "/" + path, body); await reload(); }
        catch (e) { msg.replaceChildren(failure(e, null)); }
      }
      return h("li", null, h("div", { class: "grow" },
        h("div", { class: "pre" }, n.text, n.dropped ? h("span", { class: "tag" }, " dropped") : null),
        h("div", { class: "cap" }, n.id + " - " + ago(n.created) + " - " + HOW[n.linked_by]),
        h("div", { class: "form-row" }, sel,
          n.dropped ? h("button", { class: "btn", onclick: () => act("undrop", {}) }, "Undrop")
            : [h("button", { class: "btn", onclick: () => act("link", { product: sel.value }) }, "Link"),
              h("button", { class: "btn", onclick: () => act("drop", {}) }, "Drop")]),
        msg));
    }

    function draw() {
      if (gen !== generation) return;
      const order = [], by = {};
      for (const n of data.notes) {
        if (!by[n.product]) { by[n.product] = []; order.push(n.product); }
        by[n.product].push(n);
      }
      order.sort((a, b) => (a === "inbox" ? -1 : b === "inbox" ? 1 : 0));
      const names = Object.fromEntries(data.candidates.map((c) => [c.id, c.name]));
      const groups = order.map((pid) => h("section", { class: "card group", "aria-label": pid === "inbox" ? "Inbox" : names[pid] || pid },
        h("div", { class: "group-head" }, h("h3", null, pid === "inbox" ? "Inbox" : names[pid] || pid), h("span", { class: "cap" }, by[pid].length)),
        h("ul", { class: "list" }, by[pid].map(noteRow))));
      show(h("h1", null, "Notes"),
        h("p", { class: "sub" }, "Ideas kept as you typed them. No model reads or rewrites a note. A note linked to a product reaches its record of your words."),
        noteForm({ product: null, candidates: data.candidates, onAdded: reload }),
        h("div", { class: "form-row" }, h("label", null, h("input", { type: "checkbox", checked: showDropped, onchange: (e) => { showDropped = e.target.checked; reload(); } }), " Show dropped notes")),
        groups.length ? groups : empty("No notes yet", "Type an idea above. The Inbox keeps notes that name no product."));
    }

    draw();
  }

  // --- Spend -----------------------------------------------------------------------------------

  async function spendView(_, gen) {
    let data = await api("GET", "/api/spend");
    let sig = "";

    function bars(rows, key, label) {
      const max = Math.max(...rows.map((r) => Math.max(r.this_week, r.last_week)), 0.01);
      return h("section", { class: "card" }, h("p", { class: "cap" }, "Bars: this week above, last week below."), h("table", null,
        h("thead", null, h("tr", null, h("th", null, label), h("th", { class: "n" }, "This week"), h("th", { class: "n" }, "Last week"), h("th", { class: "bar" }))),
        h("tbody", null, rows.map((r) => h("tr", null,
          h("td", null, r.name || r[key]), h("td", { class: "n" }, money(r.this_week)), h("td", { class: "n" }, money(r.last_week)),
          h("td", { class: "bar" }, sv("svg", { class: "bar", viewBox: "0 0 100 12", preserveAspectRatio: "none", "aria-hidden": "true" },
            sv("rect", { class: "bar-bg", x: 0, y: 0, width: 100, height: 12 }),
            sv("rect", { class: "bar-this", x: 0, y: 0, width: (r.this_week / max) * 100, height: 5 }),
            sv("rect", { class: "bar-last", x: 0, y: 7, width: (r.last_week / max) * 100, height: 5 }))))))));
    }

    function dayChart(days) {
      const max = Math.max(...days.map((d) => d.usd), 0.01);
      const W = 640, H = 150, base = 120, bw = 34, gap = (W - 20 - days.length * bw) / (days.length - 1);
      const label = (d) => new Date(d + "T12:00:00").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
      const g = days.map((d, i) => {
        const x = 10 + i * (bw + gap), hgt = Math.max(1, (d.usd / max) * (base - 14));
        return sv("g", null, sv("title", null, label(d.day) + ": " + money(d.usd)),
          sv("rect", { class: d.week === "this" ? "bar-this" : "bar-last", x, y: base - hgt, width: bw, height: hgt, rx: 2 }),
          d.usd > 0 ? sv("text", { class: "axis", x: x + bw / 2, y: base - hgt - 4, "text-anchor": "middle" }, money(d.usd)) : null,
          sv("text", { class: "axis", x: x + bw / 2, y: base + 16, "text-anchor": "middle" }, new Date(d.day + "T12:00:00").toLocaleDateString("en-GB", { weekday: "narrow" })));
      });
      return h("section", { class: "card" },
        sv("svg", { class: "chart", viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Spend per day for the last 14 days" }, sv("desc", null, "Bars per day, last week grey and this week blue. Hover a bar for the amount."), g),
        h("div", { class: "legend" }, h("span", null, h("i", { class: "last" }), "last week"), h("span", null, h("i", { class: "this" }), "this week")));
    }

    function draw() {
      if (gen !== generation) return;
      sig = JSON.stringify([data.at, data.refreshing, data.error]);
      const s = data.spend;
      const head = [h("h1", null, "Spend"), h("p", { class: "sub" }, "This week against last, at API list price, every harness. A subscription bills differently.")];
      if (!s) {
        show(...head, data.error ? failure(new Error(data.error), refresh)
          : strip("", h("span", null, "Counting two weeks of sessions", h("span", { class: "dots" }), " The first count takes up to a minute.")));
        return;
      }
      const state = data.refreshing ? strip("", h("span", null, "Refreshing", h("span", { class: "dots" }), " Showing the count from " + ago(data.at) + "."))
        : h("p", { class: "cap" }, "Counted " + ago(data.at) + ". ", h("button", { class: "btn quiet", onclick: refresh }, "Refresh"));
      if (!s.sessions) {
        show(...head, empty("No sessions yet", "Use Claude Code or Codex for a day. Their cost shows up here."), state);
        return;
      }
      show(...head,
        h("div", { class: "stats" },
          h("div", { class: "stat" }, h("div", { class: "num" }, money(s.this_week)), h("div", { class: "lbl" }, "last 7 days")),
          h("div", { class: "stat" }, h("div", { class: "num" }, money(s.last_week)), h("div", { class: "lbl" }, "the 7 days before")),
          h("div", { class: "stat" }, h("div", { class: "num" }, s.change_pct === null ? "-" : changePct(s.change_pct)), h("div", { class: "lbl" }, "change"))),
        state,
        h("h2", null, "By day"), dayChart(s.by_day),
        h("h2", null, "By model"), s.by_model.length ? bars(s.by_model, "model", "Model") : empty("No model cost", "No priced model ran in these two weeks."),
        h("h2", null, "By product"), s.by_product.length ? bars(s.by_product, "product", "Product") : empty("No product cost", "No session ran in a registered product."));
    }

    async function refresh() {
      try { await api("POST", "/api/refresh", { what: "spend" }); } catch (e) { data.error = e.message; }
      data.refreshing = true;
      draw();
      poll();
    }

    async function poll() {
      while (gen === generation) {
        await sleep(2500);
        if (gen !== generation) return;
        try { data = await api("GET", "/api/spend"); } catch (e) { return; }
        if (JSON.stringify([data.at, data.refreshing, data.error]) !== sig) draw();
        if (!data.refreshing) return;
      }
    }

    draw();
    if (data.refreshing) poll();
  }

  render();
})();
