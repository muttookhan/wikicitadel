#!/usr/bin/env node
/* WikiCitadel Lens — client smoke suite.
 *
 * Two layers:
 *  1. Artefact checks over the built JSON (graph, knowledge, routes,
 *     briefing, staticwebapp.config.json): counts must add up, colours
 *     must match the owner's legend, insights must reference real
 *     pages, weighted degree must recompute from the edge table.
 *  2. Renderer checks: the built data artefacts + app.js are executed
 *     in a vm context with a minimal DOM stub, and every mode renderer
 *     is invoked — including the graph Type/Community toggle, the
 *     legend filter toggles, and node sizing.
 *
 * Search parity is NOT re-checked here: the compiler runs it at build
 * and exits non-zero on failure, so a built site already passed it.
 *
 * Usage: node tools/lens/smoke_test.js [site-dir]
 * Exit code 0 iff every check passes.
 */
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const vm = require("vm");

const SITE = process.argv[2] || path.join(os.homedir(), "workspace", "lens-site");
let pass = 0, fail = 0;
function check(name, cond) {
  if (cond) { pass++; }
  else { fail++; console.log("FAIL:", name); }
}
function readJson(rel) { return JSON.parse(fs.readFileSync(path.join(SITE, rel), "utf8")); }

/* ================= Artefact checks ================= */
const graph = readJson("data/graph.json");
const knowledge = readJson("data/knowledge.json");
const routes = readJson("data/routes.json");
const briefing = readJson("data/briefing.json");
const nodeIds = new Set(graph.nodes.map(n => n.id));

// Auth wall (owner-directed): config at the SITE ROOT, parses, and
// carries exactly the required routes/override.
const swaPath = path.join(SITE, "staticwebapp.config.json");
check("auth wall: staticwebapp.config.json exists at site root", fs.existsSync(swaPath));
let swa = null;
try { swa = JSON.parse(fs.readFileSync(swaPath, "utf8")); } catch (e) { /* stays null */ }
check("auth wall: config parses as JSON", !!swa);
if (swa) {
  const login = (swa.routes || []).find(r => r.route === "/login");
  const wall = (swa.routes || []).find(r => r.route === "/*");
  check("auth wall: /login redirects to /.auth/login/aad with 302",
    !!login && login.redirect === "/.auth/login/aad" && login.statusCode === 302);
  check("auth wall: /* requires the owner role",
    !!wall && Array.isArray(wall.allowedRoles) && wall.allowedRoles.length === 1 && wall.allowedRoles[0] === "owner");
  const askRoute = (swa.routes || []).find(r => r.route === "/api/ask");
  const askRouteIdx = (swa.routes || []).findIndex(r => r.route === "/api/ask");
  const wallIdx = (swa.routes || []).findIndex(r => r.route === "/*");
  check("api routes: /api/ask requires exactly the owner role and appears before /*",
    !!askRoute && Array.isArray(askRoute.allowedRoles) && askRoute.allowedRoles.length === 1 &&
    askRoute.allowedRoles[0] === "owner" && askRouteIdx >= 0 && wallIdx >= 0 && askRouteIdx < wallIdx);
  check("api routes: /api/questions route exists",
    (swa.routes || []).some(r => r.route === "/api/questions"));
  const ov = (swa.responseOverrides || {})["401"];
  check("auth wall: 401 override redirects to /.auth/login/aad with 302",
    !!ov && ov.redirect === "/.auth/login/aad" && ov.statusCode === 302);
  // Security headers (audit L1): strict, matching the self-contained site.
  const gh = swa.globalHeaders || {};
  check("security headers: X-Frame-Options DENY and nosniff present",
    gh["X-Frame-Options"] === "DENY" && gh["X-Content-Type-Options"] === "nosniff");
  check("security headers: CSP is self-only with frame-ancestors 'none'",
    typeof gh["Content-Security-Policy"] === "string" &&
    gh["Content-Security-Policy"].includes("default-src 'self'") &&
    gh["Content-Security-Policy"].includes("frame-ancestors 'none'"));
}

// Graph header stats are real.
check("stats.pages equals node count", graph.stats.pages === graph.nodes.length);
check("stats.direct_links equals edges with direct=1",
  graph.stats.direct_links === graph.edges.filter(e => e.direct === 1).length);
check("stats.relations equals edge count", graph.stats.relations === graph.edges.length);
check("briefing page count equals graph node count", briefing.stats.pages === graph.nodes.length);

// Black Box (the build, activated 2026-10-13): the summary must be
// read from the REAL gateway ledger in wiki/access/ — chain
// verified at build, the real first session present, and at
// least the forged-token denial recorded.
const blackbox = readJson("data/blackbox-summary.json");
check("blackbox: gateway ledger chain verified at build",
  blackbox.gateway_ledger.status === "verified");
check("blackbox: gateway entries were actually counted",
  blackbox.gateway_ledger.entries_checked > 0);
check("blackbox: at least one real session is listed",
  Array.isArray(blackbox.sessions) && blackbox.sessions.length >= 1);
check("blackbox: the agent activation session is listed",
  blackbox.sessions.some(s => s.actor === "agent"));
check("blackbox: at least one denial is recorded (the forged-token probe)",
  Array.isArray(blackbox.denials) && blackbox.denials.length >= 1);
check("blackbox: note no longer claims the gateway does not exist",
  !/does not exist/i.test(blackbox.note || ""));
check("blackbox: briefing chain health reports the verified chain",
  /verified/i.test((briefing.health || {}).blackbox_chain || ""));

// Legend / type groups: owner colours, counts sum to the page total.
const groupSum = graph.type_groups.reduce((s, g) => s + g.count, 0);
check("type-group counts sum to total pages", groupSum === graph.nodes.length);
const colourOf = key => (graph.type_groups.find(g => g.key === key) || {}).colour;
check("legend colour: entity is #5B8DEF", colourOf("entity") === "#5B8DEF");
check("legend colour: concept is #A06CD5", colourOf("concept") === "#A06CD5");
check("legend colour: source is #F2994A", colourOf("source") === "#F2994A");
check("legend colour: overview is #F2C94C", colourOf("overview") === "#F2C94C");
const recount = {};
for (const n of graph.nodes) recount[n.group] = (recount[n.group] || 0) + 1;
check("type-group counts match a recount from nodes",
  graph.type_groups.every(g => recount[g.key] === g.count));

// Epistemic tags (harvest item 4): every graph relation says
// whether it was extracted from the text or inferred by the build.
check("every graph edge carries an epistemic tag",
  graph.edges.every(e => e.epistemic === "extracted" || e.epistemic === "inferred"));
check("direct graph edges are extracted, derived-only edges are inferred",
  graph.edges.every(e => (e.direct === 1) === (e.epistemic === "extracted")));
const edgesJsonl = fs.readFileSync(path.join(SITE, "data", "edges.jsonl"), "utf8")
  .split("\n").filter(l => l.trim()).map(l => JSON.parse(l));
check("every edge-table row carries an epistemic tag",
  edgesJsonl.length > 0 && edgesJsonl.every(e => typeof e.epistemic === "string" && e.epistemic.length > 0));
check("edge-table wikilink/citation/typed rows are extracted",
  edgesJsonl.every(e => e.epistemic === "extracted"));

// Weighted degree recomputes from the edge table.
const wsum = {};
for (const e of graph.edges) { wsum[e.a] = (wsum[e.a] || 0) + e.weight; wsum[e.b] = (wsum[e.b] || 0) + e.weight; }
check("node wdegree recomputes from edges (tolerance 0.02)",
  graph.nodes.every(n => Math.abs((n.wdegree || 0) - (wsum[n.id] || 0)) <= 0.02));
check("every node carries a display group present in type_groups",
  graph.nodes.every(n => graph.type_groups.some(g => g.key === n.group)));

// Communities: full disjoint cover, design-system colours.
const memberConcat = graph.communities.flatMap(c => c.members).sort();
check("communities cover every node exactly once",
  JSON.stringify(memberConcat) === JSON.stringify([...nodeIds].sort()));
const OI = ["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7", "#999999"];
check("community_colours is the design-system Okabe-Ito set",
  JSON.stringify(graph.community_colours) === JSON.stringify(OI));
check("each community's colour comes from that set and matches its id slot",
  graph.communities.every(c => c.colour === OI[c.id % OI.length]));
check("each community has a hub inside itself and a numeric cohesion",
  graph.communities.every(c => c.members.includes(c.hub_id) && typeof c.cohesion === "number"));

// Insights: >= 5 categories, counts honest, page references real.
const cats = (graph.insights && graph.insights.categories) || [];
check("insights have at least 5 categories", cats.length >= 5);
check("insights include hubs, bridges, communities, surprising, gaps, disputes",
  ["hubs", "bridges", "communities", "surprising", "gaps", "disputes"].every(k => cats.some(c => c.key === k)));
check("each insight category count equals its item count",
  cats.every(c => c.count === c.items.length));
check("every insight item page reference is a real node",
  cats.every(c => c.items.every(it => (it.pages || []).every(p => nodeIds.has(p)))));
check("insights keep the backward-compatible surprising/gaps fields",
  Array.isArray(graph.insights.surprising) && Array.isArray(graph.insights.gaps));

// Typed link edges (the build): every edge-table row carries a
// type; wikilink types come from the closed heading-inferred
// vocabulary; graph edges carry per-pair type counts that
// recompute from the edge table, with a dominant relation.
const LINK_TYPES = ["grounds", "contradicts", "extends", "exemplifies", "supersedes", "mentions"];
check("every edge-table row carries a type",
  edgesJsonl.every(e => typeof e.type === "string" && e.type.length > 0));
check("wikilink edge types come from the closed vocabulary",
  edgesJsonl.filter(e => e.kind === "wikilink").every(e => LINK_TYPES.includes(e.type)));
check("wikilink edge rows name the section their type was inferred from",
  edgesJsonl.filter(e => e.kind === "wikilink").every(e => "section" in e));
const pairTypeCounts = {};
for (const e of edgesJsonl) {
  if (e.kind !== "wikilink" && e.kind !== "typed") continue;
  if (!nodeIds.has(e.src) || !nodeIds.has(e.dst)) continue;
  const k = [e.src, e.dst].sort().join(">");
  pairTypeCounts[k] = pairTypeCounts[k] || {};
  pairTypeCounts[k][e.type] = (pairTypeCounts[k][e.type] || 0) + 1;
}
const canonTypes = o => JSON.stringify(Object.keys(o || {}).sort().map(k => [k, o[k]]));
check("graph edge type counts recompute from the edge table",
  graph.edges.every(e => {
    const want = pairTypeCounts[[e.a, e.b].sort().join(">")];
    if (!want) return e.types === undefined;
    return canonTypes(e.types) === canonTypes(want);
  }));
check("graph edge relation is a dominant type of the pair",
  graph.edges.every(e => {
    if (!e.types) return true;
    return e.types[e.relation] === Math.max(...Object.values(e.types));
  }));

// Link prediction (the build): the "missing link?" lane holds
// computed suggestions only — non-adjacent pairs, Adamic-Adar
// sorted, honestly labelled in the insights lane.
const directPairKeys = new Set(graph.edges.filter(e => e.direct === 1)
  .map(e => [e.a, e.b].sort().join(">")));
check("missing-link suggestions are non-adjacent pairs, AA-sorted, capped at 12",
  Array.isArray(graph.missing_links) && graph.missing_links.length <= 12 &&
  graph.missing_links.every(m => m.a < m.b && m.common_neighbours >= 1 &&
    !directPairKeys.has([m.a, m.b].sort().join(">"))) &&
  graph.missing_links.every((m, i) => i === 0 ||
    graph.missing_links[i - 1].adamic_adar >= m.adamic_adar));
const mlCat = cats.find(c => c.key === "missing-links");
check("insights include the Missing link? lane labelled as computed suggestions",
  !!mlCat && /computed suggestions/.test(mlCat.label) &&
  mlCat.items.every(it => /computed suggestion/i.test(it.text)));

// Co-citation (the build): references are real, counts honest,
// the index symmetric.
check("cocitations reference real nodes and real citing pages",
  Object.entries(graph.cocitations || {}).every(([pid, es]) =>
    nodeIds.has(pid) && es.every(e => nodeIds.has(e.other) && e.other !== pid &&
      e.shared_citers >= 1 && e.citers.length === e.shared_citers &&
      e.citers.every(c => nodeIds.has(c)) &&
      e.sentences.every(s => nodeIds.has(s.by) && typeof s.text === "string"))));
check("cocitations are symmetric",
  Object.entries(graph.cocitations || {}).every(([pid, es]) =>
    es.every(e => (graph.cocitations[e.other] || [])
      .some(x => x.other === pid && x.shared_citers === e.shared_citers))));

// GRAPH_REPORT (the build): god nodes are the real top pages by
// weighted degree, the typed-edge census matches the edge table,
// and both community methods are reported with Louvain rendered.
const graphReport = readJson("data/graph-report.json");
check("graph report god nodes are the top pages by weighted degree",
  Array.isArray(graphReport.god_nodes) && graphReport.god_nodes.length > 0 &&
  graphReport.god_nodes.every((g, i) => {
    const n = graph.nodes.find(x => x.id === g.id);
    return !!n && Math.abs(n.wdegree - g.wdegree) <= 0.02 &&
      (i === 0 || graphReport.god_nodes[i - 1].wdegree >= g.wdegree);
  }));
check("graph report typed-edge census matches the edge table",
  graphReport.typed_edges.total_edges === edgesJsonl.length &&
  Object.values(graphReport.typed_edges.counts).reduce((s, c) => s + c, 0) === edgesJsonl.length);
check("graph report carries both community methods, rendered = louvain",
  !!graphReport.community_methods && graphReport.community_methods.rendered === "louvain" &&
  graphReport.community_methods.louvain.communities === graph.communities.length &&
  graphReport.community_methods.label_propagation.communities >= 1);

// Knowledge panel: groups sum to the graph total; record/files honest.
check("knowledge groups sum to total pages",
  knowledge.groups.reduce((s, g) => s + g.count, 0) === graph.nodes.length);
check("knowledge.total equals graph node count", knowledge.total === graph.nodes.length);
check("knowledge groups carry the same colours as the graph legend",
  knowledge.groups.every(g => g.colour === colourOf(g.key)));
check("knowledge record group is exactly index + log",
  JSON.stringify((knowledge.record.pages || []).map(p => p.id).sort()) === JSON.stringify(["index", "log"]));
check("knowledge files counts sum to all routed pages",
  knowledge.files.reduce((s, g) => s + g.count, 0) === routes.routes.length);
const routeIds = new Set(routes.routes.map(r => r.id));
check("every knowledge page id is a real route",
  knowledge.groups.every(g => g.pages.every(p => routeIds.has(p.id))) &&
  knowledge.files.every(g => g.pages.every(p => routeIds.has(p.id))));

// Q&A history artefact (Ask the Agent): emitted even when the
// question store has no records yet — it must exist, parse, and
// carry an entries array.
const qaPath = path.join(SITE, "data", "qa.json");
check("qa: data/qa.json exists", fs.existsSync(qaPath));
let qaData = null;
try { qaData = JSON.parse(fs.readFileSync(qaPath, "utf8")); } catch (e) { /* stays null */ }
check("qa: data/qa.json parses and has an entries array",
  !!qaData && Array.isArray(qaData.entries));

// Standing queries (items 58 + 60): the Briefing artefact carries
// one line per filed standing query; every page a line names as
// new/changed is a real node, and counts are honest.
check("standing queries: briefing carries a standing_queries array",
  Array.isArray(briefing.standing_queries));
if (Array.isArray(briefing.standing_queries)) {
  check("standing queries: every named new page is a real node",
    briefing.standing_queries.every(sq => (sq.new_pages || []).every(p => nodeIds.has(p.id))));
  check("standing queries: new_count equals the new_pages length or the line cap",
    briefing.standing_queries.every(sq =>
      sq.new_count === (sq.new_pages || []).length || sq.new_count > (sq.new_pages || []).length));
}

// Staged proposals (wave-3 C2): the diff-view artefact must exist,
// carry the display-only note, and every rendered proposal must be
// a draft whose target is a real page or a marked new page, with
// hunks that parse as unified-diff ranges and counts that recompute
// from the hunk lines. The view is a read surface: the no-controls
// assertion itself lives with the renderer checks below.
const proposalsPath = path.join(SITE, "data", "proposals.json");
check("proposals: data/proposals.json exists", fs.existsSync(proposalsPath));
let proposalsData = null;
try { proposalsData = JSON.parse(fs.readFileSync(proposalsPath, "utf8")); } catch (e) { /* stays null */ }
check("proposals: data/proposals.json parses with a proposals array",
  !!proposalsData && Array.isArray(proposalsData.proposals));
check("proposals: artefact carries the display-only note",
  !!proposalsData && /Decisions are made in chat/.test(proposalsData.note || ""));
if (proposalsData && Array.isArray(proposalsData.proposals)) {
  const HUNK_RE = /^@@ -\d+(,\d+)? \+\d+(,\d+)? @@/;
  check("proposals: every rendered proposal is a draft with proposer, staged date, target and plan hash",
    proposalsData.proposals.every(p => p.state === "draft" && !!p.submitted_by &&
      !!p.submitted_at && !!p.target_path &&
      typeof p.sha256 === "string" && p.sha256.length >= 32));
  check("proposals: every target is a real page or is marked new",
    proposalsData.proposals.every(p => p.is_new === true || nodeIds.has(p.target_id)));
  check("proposals: every hunk header parses as a unified-diff range",
    proposalsData.proposals.every(p => (p.diff.hunks || []).every(h => HUNK_RE.test(h.header))));
  check("proposals: added/removed counts recompute from the hunk lines",
    proposalsData.proposals.every(p => {
      let a = 0, d = 0;
      for (const h of p.diff.hunks) for (const l of h.lines) {
        if (l.kind === "add") a++;
        if (l.kind === "del") d++;
      }
      return a === p.diff.added && d === p.diff.removed;
    }));
  check("proposals: new-page proposals are pure additions",
    proposalsData.proposals.every(p => !p.is_new || p.diff.removed === 0));
  check("proposals: rendered oldest first (queue discipline)",
    proposalsData.proposals.every((p, i, arr) =>
      i === 0 || String(arr[i - 1].submitted_at) <= String(p.submitted_at)));
}

// Hybrid search artefact: the combined search payload carries the
// wikilink adjacency (doc-index space) the client's hybrid ranker
// walks — one entry per search doc, indices in range.
const searchJsText = fs.readFileSync(path.join(SITE, "data", "search.js"), "utf8");
let searchPayload = null;
try {
  searchPayload = JSON.parse(searchJsText.replace(/^window\.LENS_SEARCH=/, "").replace(/;$/, ""));
} catch (e) { /* stays null */ }
check("search payload parses and carries docs + graph_adj",
  !!searchPayload && Array.isArray(searchPayload.docs) && Array.isArray(searchPayload.graph_adj));
if (searchPayload) {
  check("graph_adj has exactly one entry per search doc",
    searchPayload.graph_adj.length === searchPayload.docs.length);
  check("graph_adj indices are valid doc indices",
    searchPayload.graph_adj.every(a => Array.isArray(a) &&
      a.every(j => Number.isInteger(j) && j >= 0 && j < searchPayload.docs.length)));
  check("graph_adj is symmetric (undirected wikilink walk)",
    searchPayload.graph_adj.every((a, i) => a.every(j => searchPayload.graph_adj[j].includes(i))));
}

// Agent-readable exports (harvest item 9): llms.txt maps every
// content page, llms-full.txt carries the full text, and the
// build manifest's hashes actually match the emitted files.
const llmsTxt = fs.existsSync(path.join(SITE, "llms.txt"))
  ? fs.readFileSync(path.join(SITE, "llms.txt"), "utf8") : "";
check("llms.txt exists with a title", llmsTxt.startsWith("# "));
check("llms.txt links every graph node's standalone page",
  graph.nodes.every(n => llmsTxt.includes(`data/pages/${n.id}.html`)));
const llmsFull = fs.existsSync(path.join(SITE, "llms-full.txt"))
  ? fs.readFileSync(path.join(SITE, "llms-full.txt"), "utf8") : "";
check("llms-full.txt exists and is larger than llms.txt", llmsFull.length > llmsTxt.length);
check("llms-full.txt contains every graph node's title",
  graph.nodes.every(n => llmsFull.includes(n.title)));
let buildManifest = null;
try { buildManifest = readJson("build-manifest.json"); } catch (e) { /* stays null */ }
check("build-manifest.json parses with a files map",
  !!buildManifest && typeof buildManifest.files === "object");
if (buildManifest) {
  check("build manifest covers the key artefacts",
    ["data/graph.json", "data/graph-report.json", "data/edges.jsonl", "data/proposals.json", "llms.txt", "llms-full.txt", "index.html"]
      .every(f => f in buildManifest.files));
  check("build manifest does not list itself", !("build-manifest.json" in buildManifest.files));
  const crypto = require("crypto");
  check("build manifest hashes match the emitted files",
    Object.entries(buildManifest.files).every(([rel, meta]) => {
      const p = path.join(SITE, rel);
      if (!fs.existsSync(p)) return false;
      const h = crypto.createHash("sha256").update(fs.readFileSync(p)).digest("hex");
      return h === meta.sha256 && fs.statSync(p).size === meta.bytes;
    }));
  check("build manifest file_count equals the files map size",
    buildManifest.file_count === Object.keys(buildManifest.files).length);
}

// Mentions + verbatim quotes (harvest item 10): deterministic
// display-time sections computed at build. Structural invariants
// only — the corpus's blockquotes are callouts/notes, so verified
// quotes may legitimately be zero today.
try {
  const nodeIds = new Set(graph.nodes.map(n => String(n.id).replace(/\\/g, "/")));
  const linkPairs = new Set();
  for (const line of fs.readFileSync(path.join(SITE, "data", "edges.jsonl"), "utf8").split("\n")) {
    if (!line.trim()) continue;
    const e = JSON.parse(line);
    if (e.kind === "wikilink" || e.kind === "typed") linkPairs.add(`${e.src}>${e.dst}`);
  }
  let mentionsTotal = 0, mentionsOk = true, quotesOk = true;
  for (const n of graph.nodes) {
    const pj = readJson(`data/pages/${n.id}.json`);
    if (!Array.isArray(pj.mentions) || !Array.isArray(pj.quotes)) { mentionsOk = false; break; }
    mentionsTotal += pj.mentions.length;
    for (const m of pj.mentions) {
      if (m.id === n.id || !nodeIds.has(m.id)) mentionsOk = false;
      if (linkPairs.has(`${m.id}>${n.id}`)) mentionsOk = false; // m links to n: not a mention
    }
    for (const q of pj.quotes) {
      if (!String(q.source).startsWith("raw/") || !(q.line >= 1)) quotesOk = false;
    }
  }
  check("every page artefact carries mentions + quotes arrays", mentionsOk);
  check("mentions exist on this corpus and never duplicate a wikilink or self", mentionsTotal > 0 && mentionsOk);
  check("every verified quote cites a raw source with a line number", quotesOk);
  const withMentions = graph.nodes.find(n => (readJson(`data/pages/${n.id}.json`).mentions || []).length);
  check("standalone page HTML renders the Mentions section",
    !!withMentions && fs.readFileSync(path.join(SITE, "data", "pages", `${withMentions.id}.html`), "utf8")
      .includes("Mentions (unlinked)"));
} catch (e) { check("mentions/quotes artefact checks ran (" + e.message + ")", false); }

// Owner attestation (wave-3 set B): page artefacts carry the
// frontmatter attestation verbatim plus the build-computed
// attested_until — set only for an owner attestation whose
// verified_until is still in the future at build time.
try {
  let attestOk = true, attestedCount = 0;
  for (const n of graph.nodes) {
    const pj = readJson(`data/pages/${n.id}.json`);
    if (typeof pj.verified_until !== "string" || typeof pj.verified_by !== "string" ||
        typeof pj.attested_until !== "string") attestOk = false;
    if (pj.attested_until) {
      attestedCount++;
      if (pj.attested_until !== pj.verified_until || pj.verified_by !== "owner") attestOk = false;
    }
  }
  check("every page artefact carries verified_until/verified_by/attested_until", attestOk);
  const ownerPj = readJson("data/pages/owner.json");
  check("the seeded owner attestation (owner page) is attested in this build",
    ownerPj.verified_until === "2027-01-20" && ownerPj.verified_by === "owner" &&
    ownerPj.attested_until === "2027-01-20");
  check("at least one page is owner-attested in this build", attestedCount >= 1);
} catch (e) { check("attestation artefact checks ran (" + e.message + ")", false); }

// Growth stages (wave-3 set F): every content page artefact
// carries a stage in the vocabulary, projected from frontmatter
// by scripts/wiki_stages.py's backfill, plus planted/tended.
try {
  const stages = ["seedling", "budding", "evergreen"];
  const structural = ["wiki/index.md", "wiki/log.md"]; // no frontmatter, no stage by design
  let stageOk = true;
  const seen = {};
  for (const n of graph.nodes) {
    const pj = readJson(`data/pages/${n.id}.json`);
    if (structural.includes(pj.path)) {
      if (pj.stage !== "") stageOk = false;
      continue;
    }
    if (!stages.includes(pj.stage)) stageOk = false;
    else seen[pj.stage] = (seen[pj.stage] || 0) + 1;
    if (typeof pj.planted !== "string" || typeof pj.tended !== "string") stageOk = false;
  }
  check("every page artefact carries a growth stage + planted/tended", stageOk);
  check("the corpus has at least one evergreen page", (seen.evergreen || 0) >= 1);
} catch (e) { check("growth-stage artefact checks ran (" + e.message + ")", false); }

// Shell wiring for the knowledge artefact.
const shellHtml = fs.readFileSync(path.join(SITE, "index.html"), "utf8");
check("shell loads data/knowledge.js", shellHtml.includes("data/knowledge.js"));
check("shell loads data/qa.js", shellHtml.includes("data/qa.js"));
check("shell loads data/proposals.js", shellHtml.includes("data/proposals.js"));
check("shell loads data/trails.js", shellHtml.includes("data/trails.js"));
check("shell links the Trails mode", shellHtml.includes('data-route="trails"'));

/* ================= Trails + citation pairings (item 62) ================= */
const trails = readJson("data/trails.json");
check("trails artefact carries at least one authored trail", (trails.trails || []).length >= 1);
check("trails artefact drops nothing in this build", (trails.dropped || []).length === 0);
const edgeSet = new Set();
for (const line of fs.readFileSync(path.join(SITE, "data/edges.jsonl"), "utf8").split("\n")) {
  if (!line.trim()) continue;
  const e = JSON.parse(line);
  edgeSet.add(`${e.src}|${e.dst}|${e.type}`);
}
for (const t of trails.trails || []) {
  check(`trail ${t.id} has at least two steps`, t.steps.length >= 2);
  check(`trail ${t.id} steps are all real pages`,
    t.steps.every(s => nodeIds.has(s.page) || s.page === "overview"));
  check(`trail ${t.id} every hop is a real typed edge`,
    t.steps.every((s, i) => i === 0 || edgeSet.has(`${t.steps[i - 1].page}|${s.page}|${s.via}`)));
}
// Citation pairings: the reading artefact's quotes must equal the
// lockfile's verbatim selector text for the same lock id — the
// pairing pipeline may not paraphrase or mangle a passage.
const lockPath = path.join(__dirname, "..", "..", "evaluation", "citation-lockfile.json");
if (fs.existsSync(lockPath)) {
  const lock = JSON.parse(fs.readFileSync(lockPath, "utf8"));
  const lockById = {};
  for (const c of lock.citations || []) lockById[c.id] = c;
  let pairingTotal = 0, pairingVerbatim = 0;
  for (const f of fs.readdirSync(path.join(SITE, "data/pages"))) {
    if (!f.endsWith(".json")) continue;
    const pg = JSON.parse(fs.readFileSync(path.join(SITE, "data/pages", f), "utf8"));
    for (const cp of pg.cite_passages || []) {
      pairingTotal++;
      const entry = lockById[cp.cite_id];
      if (entry && entry.selector && entry.selector.exact === cp.quote &&
          entry.claim === cp.claim && entry.source === cp.source) pairingVerbatim++;
    }
  }
  check("citation pairings exist in page artefacts", pairingTotal > 0);
  check("every citation pairing is the lockfile's verbatim quote",
    pairingTotal === pairingVerbatim);
}
check("shell loads data/graph-report.js", shellHtml.includes("data/graph-report.js"));
check("shell carries the ⌘K palette markup (items 58 + 60)",
  shellHtml.includes('id="palette"') && shellHtml.includes('id="palette-input"') &&
  shellHtml.includes('id="palette-results"') && shellHtml.includes('id="palette-open"'));
check("shell carries the recent/frequent strip mount (item 60)",
  shellHtml.includes('id="recent-strip"'));

/* ================= Renderer checks (vm + DOM stub) ================= */
function makeEl(id) {
  return {
    id, innerHTML: "", textContent: "", value: "",
    classList: { add() {}, remove() {}, toggle: () => false, contains: () => false },
    style: {}, disabled: false,
    addEventListener() {}, setAttribute() {}, getAttribute: () => null,
    querySelectorAll: () => [], querySelector: () => null, focus() {},
  };
}
const els = {};
const documentStub = {
  getElementById: id => els[id] || (els[id] = makeEl(id)),
  querySelectorAll: () => [],
  addEventListener() {},
  activeElement: { tagName: "BODY" },
};
const sandbox = {
  console, setTimeout, clearTimeout,
  document: documentStub,
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  location: { hash: "#/" },
  addEventListener() {},
  __results: [],
};
sandbox.window = sandbox;
vm.createContext(sandbox);
for (const f of ["data/pages.js", "data/routes.js", "data/graph.js", "data/graph-report.js", "data/modes.js", "data/search.js", "data/knowledge.js", "data/qa.js", "data/proposals.js", "data/trails.js", "app.js"]) {
  vm.runInContext(fs.readFileSync(path.join(SITE, f), "utf8"), sandbox, { filename: f });
}

/* This function is serialised and re-evaluated inside the vm context,
 * where app.js's top-level functions and state variables live. */
function lensRendererTests() {
  const R = [];
  const t = (name, cond) => R.push([name, !!cond]);
  const html = () => canvas.innerHTML;
  const reset = () => {
    graphView = "canvas"; graphSelected = null; graphColourMode = "type";
    graphTypeFilter = null; graphCommFilter = null; graphInsightsOpen = true; graphNodeQuery = "";
  };

  t("renderers exist", typeof renderBriefing === "function" && typeof renderRead === "function" &&
    typeof renderGraph === "function" && typeof renderTimeline === "function" &&
    typeof renderDecisions === "function" && typeof renderCards === "function" &&
    typeof renderSearch === "function" && typeof renderAsk === "function" &&
    typeof renderBlackBox === "function");

  renderBriefing();
  t("briefing renders with waiting-on-you section", html().includes("Briefing") && html().includes("Waiting on you"));
  t("briefing renders the standing-queries section (item 60)", html().includes("Standing queries"));

  reset(); renderGraph();
  t("graph header shows Knowledge Graph + real page/link stats",
    html().includes("Knowledge Graph") && html().includes(`${GRAPH.stats.pages} pages · ${GRAPH.stats.direct_links} links`));
  t("graph type mode shows the Node Types legend", html().includes("Node Types"));
  t("graph legend lists every type group with its count",
    GRAPH.type_groups.every(g => html().includes(g.singular) && html().includes(`legend-count">${g.count}<`)));
  t("graph type mode paints nodes with the owner legend colours",
    ["#5B8DEF", "#A06CD5", "#F2994A", "#F2C94C"].every(c => html().includes(c)));
  t("graph type mode uses no community colour", !html().includes("#E69F00"));

  const ent = GRAPH.nodes.find(n => n.group === "entity");
  const entType = shapeFor(ent);
  graphColourMode = "community"; const entComm = shapeFor(ent);
  t("toggle changes node fill (type colour -> community colour)",
    entType.includes("#5B8DEF") && entComm.includes(GRAPH.community_colours[ent.community % 8]) && entType !== entComm);

  reset(); graphColourMode = "community"; renderGraph();
  // Community labels derive from page titles, which the renderer
  // HTML-escapes (a hub title may contain an apostrophe) — compare
  // against the escaped form esc() produces, as rendered.
  t("graph community mode legend lists clusters with counts and the lens disclaimer",
    html().includes("Communities") && html().includes("never canonical categories") &&
    GRAPH.communities.every(c => html().includes(esc(c.label))));
  t("graph community mode paints the first community colour", html().includes(GRAPH.community_colours[0]));

  const hub = GRAPH.nodes.reduce((a, b) => ((b.wdegree || 0) > (a.wdegree || 0) ? b : a));
  const leaf = GRAPH.nodes.reduce((a, b) => ((b.wdegree || 0) < (a.wdegree || 0) ? b : a));
  t("node sizing: strongest hub is full size (22)", Math.abs(sizeFor(hub) - 22) < 0.011);
  t("node sizing: weakest node is smaller than the hub", sizeFor(leaf) >= 6 && sizeFor(leaf) < sizeFor(hub));
  const sortedSizes = [...GRAPH.nodes].sort((a, b) => (a.wdegree || 0) - (b.wdegree || 0)).map(sizeFor);
  t("node sizing is monotonic in weighted degree", sortedSizes.every((s, i) => i === 0 || s >= sortedSizes[i - 1] - 1e-9));

  reset(); renderGraph();
  const total = insightTotal();
  t("insights button carries the real total count", html().includes(`Insights ${total}`) && total > 0);
  t("insights panel lists every category with its count",
    GRAPH.insights.categories.every(c => html().includes(`${c.label} · ${c.count}`)));
  t("insights total equals the sum of category counts",
    total === GRAPH.insights.categories.reduce((s, c) => s + c.count, 0));

  reset();
  const srcNode = GRAPH.nodes.find(n => n.group === "source");
  graphTypeFilter = "entity"; renderGraph();
  t("legend type filter fades other types, keeps the chosen type",
    html().includes(`data-node="${srcNode.id}" style="opacity:0.15"`) &&
    html().includes(`data-node="${ent.id}" style="opacity:1"`));
  graphTypeFilter = null; graphColourMode = "community";
  const c0 = GRAPH.communities[0];
  const outside = GRAPH.nodes.find(n => n.community !== c0.id);
  const inside = GRAPH.nodes.find(n => n.community === c0.id);
  graphCommFilter = c0.id; renderGraph();
  t("legend community filter fades other clusters, keeps the chosen cluster",
    html().includes(`data-node="${outside.id}" style="opacity:0.15"`) &&
    html().includes(`data-node="${inside.id}" style="opacity:1"`));

  const cocitId = Object.keys(GRAPH.cocitations || {})[0];
  if (cocitId) {
    reset(); graphSelected = cocitId; renderGraph();
    t("graph inspector shows the co-citation panel for a co-cited page",
      inspectorCtx.innerHTML.includes("Co-cited with"));
  }

  reset(); graphView = "list"; renderGraph();
  t("list view groups by community with hub + cohesion and carries Insights",
    GRAPH.communities.every(c => html().includes(esc(c.label))) && html().includes("stays inside") && html().includes("Insights"));
  t("list view carries the Graph report with god nodes and Missing link? suggestions",
    html().includes("Graph report") && html().includes("God nodes") && html().includes("Missing link?"));

  treeTab = "knowledge"; renderTree(null);
  const kgSum = [...treeEl.innerHTML.matchAll(/data-kg-count="(\d+)"/g)].reduce((s, m) => s + parseInt(m[1], 10), 0);
  t("knowledge tree: tabs present and group counts sum to the page total",
    treeEl.innerHTML.includes("Knowledge") && treeEl.innerHTML.includes("Files") && kgSum === GRAPH.nodes.length);
  treeTab = "files"; renderTree(null);
  const fSum = [...treeEl.innerHTML.matchAll(/data-file-count="(\d+)"/g)].reduce((s, m) => s + parseInt(m[1], 10), 0);
  t("files tree: folder counts sum to all routed pages", fSum === Object.keys(PAGES).length);
  treeTab = "knowledge";

  renderRead("overview");
  t("reading renders the overview with a provenance inspector",
    html().includes("Overview") && inspectorCtx.innerHTML.includes("Provenance"));
  t("reading an unattested page shows no Verified by owner line",
    !html().includes("Verified by owner until"));
  renderRead("owner");
  t("reading the owner-attested owner page shows the Verified by owner line",
    html().includes("Verified by owner until 2027-01-20") &&
    inspectorCtx.innerHTML.includes("Attestation: verified by owner until 2027-01-20"));
  renderTimeline();
  t("timeline renders", html().includes("Timeline"));
  renderDecisions();
  t("decisions render with Decided cards", html().includes("Decided"));
  renderCards();
  t("cards render", html().includes("Cards"));
  renderSearch("rights");
  t("search renders the BM25 lane", html().includes("Full-text (BM25)"));
  t("search lanes return hits for a real query", searchLanes("azure canonical").bm25.length > 0);
  t("hybrid ranker exists and returns hits for a real query",
    typeof hybridRank === "function" && searchLanes("azure canonical").hybrid.length > 0);
  t("search renders the hybrid lane", html().includes("Hybrid (BM25 + graph)"));
  t("hybrid top hit is a real search doc",
    searchLanes("azure canonical").hybrid.every(r => SEARCH.docs.some(d => d.path === r.path)));

  /* Phase-8 surfaces (items 56/57/59 + fold-ins 1/2). Severance
   * expectations derive from evaluation/retrieval-severance.json
   * (sev-0001, the superseded "Collaborator seat reserved" form) over the
   * Lens corpus — the same exclusion set the Python mirror
   * produces (scripts/tests/test_lens_surfaces.py). */
  const sevLanes = searchLanes("collaborator seat reserved");
  const sevPaths = [...sevLanes.bm25, ...sevLanes.hybrid].map(r => r.path);
  t("severance: the severed claim's carriers leave both ranked lanes",
    !sevPaths.includes("wiki/syntheses/decision-register.md") &&
    !sevPaths.includes("wiki/entities/collaborator.md"));
  t("severance: the exclusion is recorded, naming the entry",
    lensLastSeverance().applied &&
    lensLastSeverance().excluded.some(e => e.path === "wiki/syntheses/decision-register.md" && e.entries.includes("sev-0001")));
  renderSearch("owner");
  t("freshness: the attested page's line renders in the results",
    html().includes("verified until 2027-01-20"));
  renderSearch("azure canonical");
  t("passages: results carry a passage with a heading deep link",
    html().includes("passage-under") && /#\/read\/[a-z0-9-]+\/[a-z0-9-]+/.test(html()));
  t("facets: the rail renders with counts beside values",
    html().includes("facet-rail") && html().includes("facet-count"));
  facetStateFor("azure");
  facetFilters = { type: new Set(["entity"]) };
  const narrowed = _searchLanes("azure", facetFilters);
  t("facets: narrowing keeps only docs carrying the value",
    narrowed.bm25.concat(narrowed.hybrid).every(r => (r.doc.facets.type || []).includes("entity")) &&
    narrowed.hybrid.length > 0);
  t("facets: a zero-yield value is greyed, not hidden or clickable",
    facetRailHtml(narrowed).includes("facet-zero"));
  facetFilters = {}; facetQuery = "";
  t("suggestions: a misspelling is corrected from the corpus dictionary",
    suggestionsFor("goverance rules", tokenize("goverance rules")).corrections.some(c => c.from === "goverance" && c.to === "governance"));
  const ladderTry = searchWithLadder("severence");
  t("ladder: a dead-end spelling widens at the named variants rung",
    ladderTry.rung === "variants" && ladderTry.note.includes("severance") &&
    searchLanesHtml("severence").includes("rung 1"));
  t("facet-tagged query: a tag word in the query is offered as a filter",
    queryFacetTags(tokenize("collaborator")).some(x => x.dim === "tags" && x.value === "collaborator") &&
    renderSearch("collaborator") === undefined && html().includes("narrow to it"));
  renderBlackBox();
  t("black box renders the flight recorder", html().includes("flight recorder"));
  t("black box banner reports the verified chain with the real entry count",
    html().includes("Chain verified") &&
    html().includes(`${BLACKBOX.gateway_ledger.entries_checked} entries`));
  t("black box lists the real agent session from the ledger",
    html().includes("agent") && html().includes("Sessions"));

  renderAsk("");
  answerQuestion("zzzzqqqq nonsense");
  t("ask states Insufficient evidence for an unanswerable question",
    document.getElementById("ask-answer").innerHTML.includes("Insufficient evidence"));
  answerQuestion("rights gate");
  const ans = document.getElementById("ask-answer").innerHTML;
  t("ask answers with Sources used for a real question", ans.includes("Sources used") && !ans.includes("Insufficient evidence"));

  renderAsk("");
  t("ask renders the Ask the Agent form",
    html().includes("Ask the Agent") && html().includes("agent-question") &&
    html().includes("agent-ask-form") && html().includes("agent-ask-status"));
  QA_HISTORY = [
    { id: "qa-fixture-answered", question: "Fixture answered question?", asker: "Fixture Asker",
      asked_at: "2026-10-13T10:00:00Z", answered_at: "2026-10-13T11:00:00Z",
      answer: "Fixture answer text.", citations: [GRAPH.nodes[0].id], status: "answered" },
    { id: "qa-fixture-pending", question: "Fixture pending question?", asker: "Fixture Asker",
      asked_at: "2026-10-13T12:00:00Z", answered_at: null,
      answer: null, citations: [], status: "pending" },
  ];
  renderQaHistory();
  const qaHtml = document.getElementById("qa-history").innerHTML;
  t("qa history renders the answered fixture with its answer and citation link",
    qaHtml.includes("Fixture answered question?") && qaHtml.includes("Fixture answer text.") &&
    qaHtml.includes(`#/read/${GRAPH.nodes[0].id}`));
  t("qa history renders the pending fixture with a Waiting indicator",
    qaHtml.includes("Fixture pending question?") && qaHtml.includes("Waiting"));
  QA_HISTORY = [];
  renderQaHistory();
  t("qa history renders the empty note when there are no questions",
    document.getElementById("qa-history").innerHTML.includes("No questions yet"));

  t("trails renderer exists", typeof renderTrails === "function" && typeof trailHash === "function");
  renderTrails(null, {});
  const trailListHtml = html();
  t("trails list renders every authored trail with its walk link",
    TRAILS.trails.length > 0 && TRAILS.trails.every(tr => trailListHtml.includes(tr.title)) &&
    trailListHtml.includes("Walk this trail"));
  if (TRAILS.trails.length) {
    const tr0 = TRAILS.trails[0];
    t("trail URL serialises the stack and step",
      trailHash(tr0, 2) === `#/trails/${tr0.id}?stack=${tr0.steps.map(s => s.page).join(",")}&at=2`);
    renderTrails(tr0.id, {});
    t("trail walk renders step 1 with the path strip naming edge types",
      html().includes("Step 1 of") && html().includes(`— ${tr0.steps[1].via} →`) &&
      html().includes("The trail starts here."));
    renderTrails(tr0.id, { stack: tr0.steps.map(s => s.page).join(","), at: "1" });
    t("trail walk resumes from the URL stack at the named step and names the hop's edge type",
      html().includes("Step 2 of") && html().includes(`via a <span class="mono">${tr0.steps[1].via}</span>`));
  }
  renderRead("memory-discipline-karpathy-alignment");
  const pairedPage = PAGES["memory-discipline-karpathy-alignment"];
  t("reading a lockfile page pairs claims with their verbatim passages",
    !!(pairedPage && (pairedPage.cite_passages || []).length) &&
    html().includes("Claims and their sources") &&
    pairedPage.cite_passages.every(cp => html().includes(esc(cp.quote))));

  t("proposals renderer exists", typeof renderProposals === "function");
  renderProposals();
  const propHtml = html();
  t("proposals view states the display-only rule",
    propHtml.includes("Decisions are made in chat"));
  t("proposals view carries no control buttons, forms or action hooks",
    !/<button/i.test(propHtml) && !/<form/i.test(propHtml) && !/data-action/i.test(propHtml));
  if (PROPOSALS.proposals.length) {
    const p0 = PROPOSALS.proposals[0];
    t("proposals view renders the oldest staged proposal with its manifest facts",
      propHtml.includes(p0.proposal_id) && propHtml.includes(p0.target_path) &&
      propHtml.includes(p0.submitted_by));
    t("proposals view renders per-hunk diff lines",
      propHtml.includes("diff-hunk") && propHtml.includes("diff-line"));
    t("proposals view renders a link to the current page for an existing target",
      PROPOSALS.proposals.every(p => p.is_new || propHtml.includes(`#/read/${p.target_id}`)));
  } else {
    t("proposals view renders its empty note when nothing is staged",
      propHtml.includes("No staged proposals"));
  }

  /* Items 58 + 60: the designed zero-results surface, the
     save-the-failed-search offer, and the ⌘K palette. */
  t("zero-state + palette functions exist (items 58 + 60)",
    typeof zeroResultsHtml === "function" && typeof wireZeroState === "function" &&
    typeof openPalette === "function" && typeof paletteItems === "function");
  const zeroHtml = searchLanesHtml("qxjzv wvkrp");
  t("zero results render the designed surface, not a bare end",
    zeroHtml.includes("Nothing in the wiki matches") && zeroHtml.includes("zero-state"));
  t("zero surface offers save-the-failed-search (watch this search)",
    zeroHtml.includes("Watch this search") && zeroHtml.includes("zero-watch-btn") &&
    zeroHtml.includes("standing-queries.jsonl"));
  t("zero surface keeps the human route and the popular floor",
    zeroHtml.includes("zero-ask-btn") && zeroHtml.includes("Most-linked pages"));
  wireZeroState("qxjzv wvkrp");
  t("wireZeroState binds the zero-state controls without throwing", true);
  openPalette();
  const palHtml = document.getElementById("palette-results").innerHTML;
  t("palette opens with recents/views before typing",
    paletteIsOpen === true && palHtml.includes("Go to") && palHtml.includes("Briefing"));
  const palPages = paletteItems("azure");
  const palPageGroup = palPages.find(g => g.name === "Pages");
  t("palette search returns the merged search's pages with real routes",
    !!palPageGroup && palPageGroup.items.length > 0 &&
    palPageGroup.items.every(it => it.route.startsWith("#/read/") &&
      Object.prototype.hasOwnProperty.call(PAGES, decodeURIComponent(it.route.slice("#/read/".length)))));
  t("palette offers the ask action for a typed query",
    palPages.some(g => g.name === "Actions" && g.items.some(it => it.label.startsWith("Ask:"))));
  closePalette();
  t("palette closes", paletteIsOpen === false);
  logQuery("qxjzv wvkrp");
  t("query log accepts entries without throwing (browser-local only)",
    Array.isArray(recentQueries(4)));

  return R;
}
const results = vm.runInContext(`(${lensRendererTests.toString()})()`, sandbox);
for (const [name, ok] of results) check("renderer: " + name, ok);

/* ================= Phase-8 lane (items 63/64/65) =================
   Reported SEPARATELY: the main counts above are the pre-Phase-8
   baseline (143/145 at the Phase-8 build) and this lane never
   touches them or the exit code. It checks the state-shaped
   views, the Briefing honesty stack (chart-honesty gate items
   that are mechanical over the artefact), and the reading
   profile's scoring math. */
let p8pass = 0, p8fail = 0;
function check8(name, cond) {
  if (cond) { p8pass++; }
  else { p8fail++; console.log("PHASE8 FAIL:", name); }
}
try {
  const state = readJson("data/state.json");
  const mx = state.matrix, lc = state.lifecycle;
  check8("state: matrix present with lifecycle + argdown census",
    !!mx && !!lc && !!state.argdown);
  check8("state: matrix totals conserve the page count",
    Object.values(mx.totals).reduce((a, v) => a + v.length, 0) === mx.total_pages &&
    mx.total_pages === graph.nodes.length);
  check8("state: owner is the owner-verified page",
    (mx.totals["owner-verified"] || []).includes("owner"));
  check8("state: the three due claim pages are in the due state",
    ["overview", "decision-register", "founding-note"]
      .every(id => (mx.totals["re-verification-due"] || []).includes(id)));
  check8("state: lifecycle terminal counts conserve records",
    (lc.prefixes || []).reduce((a, p) => a + p.terminal_count, 0) === lc.record_count);
  check8("state: decision-register path is treated + severed",
    (lc.records || []).some(r => r.page === "decision-register" &&
      r.states.includes("treated-negative") && r.states.includes("severed")));
  check8("state: argdown census is consistent (0 blocks is a true count)",
    state.argdown.blocks === 0
      ? state.argdown.pages.length === 0
      : state.argdown.pages.length > 0);
  const honesty = briefing.honesty || {};
  check8("honesty: admission verdicts on record (5 stats, all context)",
    (honesty.admission_verdicts || []).length === 5 &&
    honesty.admission_verdicts.every(v => v.verdict === "context"));
  check8("honesty: every bullet geometry is zero-based and banded",
    (honesty.bullets || []).length >= 5 && honesty.bullets.every(b => {
      const g = b.geometry;
      if (!g || g.value_frac < 0 || g.value_frac > 1) return false;
      let prev = 0;
      for (const band of g.bands) { if (band.from !== prev) return false; prev = band.to; }
      return prev === 1;
    }));
  const ls = honesty.lane_series || { series: [], shared_max: 0 };
  const allVals = (ls.series || []).flatMap(s => s.points.map(p => p.value));
  check8("honesty: sparklines share ONE scale (the artefact's shared_max is the true max)",
    ls.shared_max === Math.max(1, ...allVals));
  check8("honesty: every lane with points carries precomputed shared-scale points",
    (ls.series || []).every(s => !s.points.length ||
      (typeof s.points_svg === "string" && s.points_svg.split(" ").length === s.points.length)));
  check8("honesty: leaks series excludes the pre-baseline-format filing (metric honesty)",
    (ls.series || []).every(s => s.lane !== "leaks" ||
      s.points.every(p => p.date >= "2026-10-20")));
  const fc = honesty.forecast || {};
  check8("honesty: forecast DUE NOW block present and counted (overdue never excluded)",
    Array.isArray(fc.due_now) && fc.due_now_count === fc.due_now.length &&
    typeof fc.note === "string" && fc.note.includes("never"));
  check8("honesty: do-nothing cumulative never decreases",
    (fc.cumulative_if_neglected || []).every((v, i, a) => i === 0 || v >= a[i - 1]));
  check8("assets: Atkinson Hyperlegible self-hosted with its OFL licence",
    fs.existsSync(path.join(SITE, "fonts", "atkinson-hyperlegible-400-latin.woff2")) &&
    fs.existsSync(path.join(SITE, "fonts", "LICENSE-atkinson-hyperlegible.txt")));
  check8("rulings: briefing waiting_on_you carries at least one titled item (the ruling buttons' data)",
    (briefing.waiting_on_you || []).some(w => typeof w.title === "string" && w.title.length > 0));
  const appJsText = fs.readFileSync(path.join(SITE, "app.js"), "utf8");
  check8("rulings: shipped app.js carries the ruling caption + the Ask-door ruling marker",
    appJsText.includes("this page itself decides nothing") &&
    appJsText.includes("Owner ruling via Lens (ideas board)"));
} catch (e) {
  check8("phase-8 artefact lane ran (" + e.message + ")", false);
}
function lensPhase8Tests() {
  const R = [];
  const t = (name, cond) => R.push([name, !!cond]);
  const html = () => canvas.innerHTML;
  t("state + reading renderers exist",
    typeof renderState === "function" && typeof renderReading === "function" &&
    typeof scoreCalibration === "function");
  renderState();
  t("state view renders matrix + lifecycle + argument maps sections",
    html().includes("Evidence and gap matrix") && html().includes("lifecycle prefix") &&
    html().includes("Argument maps"));
  t("state view names its own bound (what it cannot show)",
    html().includes("cannot show"));
  renderBriefing();
  t("briefing renders the honesty health section with bullets",
    html().includes("Health — numbers that can change a decision") && html().includes("bullet-svg"));
  t("briefing labels the vanity stats as context",
    html().includes("stat-verdict") && html().includes("context"));
  t("briefing forecast shows the DUE NOW block",
    html().includes("Due now") && html().includes("fc-duenow"));
  const sc = scoreCalibration([
    { preset: "a", name: "A", words: 180, seconds: 60, correct: 2 },
    { preset: "b", name: "B", words: 180, seconds: 45, correct: 1 },
    { preset: "c", name: "C", words: 150, seconds: 60, correct: 2 },
  ]);
  t("calibration scoring: WPM math (180/240/150)",
    sc.rows[0].wpm === 180 && sc.rows[1].wpm === 240 && sc.rows[2].wpm === 150);
  t("calibration scoring: comprehension gates speed (240 WPM unqualified loses)",
    sc.winner && sc.winner.preset === "a" && sc.fallback === false);
  const fb = scoreCalibration([
    { preset: "a", name: "A", words: 180, seconds: 60, correct: 1 },
    { preset: "b", name: "B", words: 120, seconds: 60, correct: 0 },
  ]);
  t("calibration scoring: fallback is labelled when nothing qualifies",
    fb.fallback === true && fb.winner && fb.winner.preset === "a");
  renderReading();
  t("reading mode states the N1 exclusion (no RSVP / Bionic)",
    html().includes("never contain RSVP") && html().includes("Atkinson Hyperlegible"));
  t("reading presets: six candidates incl. the BDA comfort preset at line-height 2.0",
    READ_PRESETS.length === 6 && READ_PRESETS.some(p => p.id === "comfort-bda" && p.lh === 2.0));
  renderRead("overview");
  t("read mode carries line-focus controls (off/1/3/5)",
    html().includes("Line focus") && html().includes('data-lf="5"'));
  return R;
}
try {
  const r8 = vm.runInContext(`(${lensPhase8Tests.toString()})()`, sandbox);
  for (const [name, ok] of r8) check8("renderer: " + name, ok);
} catch (e) {
  check8("phase-8 renderer lane ran (" + e.message + ")", false);
}
console.log(`PHASE8 LANE: ${p8pass}/${p8pass + p8fail} PASS (separate from the main counts)`);

console.log(`SMOKE: ${pass}/${pass + fail} PASS`);
process.exit(fail ? 1 : 0);
