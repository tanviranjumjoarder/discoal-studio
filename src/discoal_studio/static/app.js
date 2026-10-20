// discoal Studio front end: plain JS, no build step.
// Copyright (C) 2026 Tanvir Anjum Joarder. GPL-3.0-or-later; see NOTICE for the attribution terms.
"use strict";

const TOKEN = new URLSearchParams(location.search).get("t") || "";
const $ = (s) => document.querySelector(s);
let INFO = null, spec = null, outTouched = false, poll = null;

async function api(path, body) {
  const r = await fetch("/api" + path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", "X-Token": TOKEN },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "class") e.className = v;
    else if (k === "style") e.style.cssText = v;
    else if (k === "checked" || k === "value") e[k] = v;
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k.nodeType ? k : String(k));
  return e;
}

const fmtNum = (x) => typeof x === "number" ? (Math.abs(x) >= 1e5 || (x !== 0 && Math.abs(x) < 1e-3) ? x.toExponential(3) : +x.toPrecision(6)) : x;
const fmtTime = (s) => s == null ? "–" : s < 1 ? `${Math.round(s * 1000)} ms` : s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`;
const fmtBytes = (b) => b < 1e6 ? `${(b / 1e3).toFixed(0)} kB` : b < 1e9 ? `${(b / 1e6).toFixed(1)} MB` : `${(b / 1e9).toFixed(2)} GB`;
const parseVal = (s) => { const t = String(s).trim(); return t !== "" && !isNaN(+t) ? +t : t; };
const flag = (f) => el("span", { class: "flag", title: "discoal option" }, f);
const COLORS = ["--c0", "--c1", "--c2", "--c3", "--c4", "--c5"];

function toast(msg) {
  const t = el("div", { class: "toast" }, msg);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), 2600);
}

// ---------- prior editor ----------------------------------------------------------
const DISTS = {
  fixed: ["value"], uniform: ["low", "high"], uniform_int: ["low", "high"],
  loguniform: ["low", "high"], truncated_exponential: ["mean", "upper"],
};
const DIST_LABEL = { fixed: "Fixed", uniform: "Uniform", uniform_int: "Uniform (whole numbers)",
  loguniform: "Log-uniform", truncated_exponential: "Exponential, capped" };
const fixedP = (v) => ({ dist: "fixed", value: v });

// A quick preview of a prior's shape (Math.random, not the reproducible per-file draws).
function sampleOnce(p) {
  const a = +p.low, b = +p.high;
  switch (p.dist) {
    case "fixed": return +p.value;
    case "uniform": return a + Math.random() * (b - a);
    case "uniform_int": return Math.floor(a + Math.random() * (b - a + 1));
    case "loguniform": return Math.exp(Math.log(a) + Math.random() * (Math.log(b) - Math.log(a)));
    default: { let x; do { x = -Math.log(1 - Math.random()) * +p.mean; } while (x > +p.upper); return x; }
  }
}

function spark(p) {
  const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 92 28"); svg.setAttribute("class", "spark-h");
  const fields = DISTS[p.dist].map((f) => p[f]);
  const text = (t) => { const x = document.createElementNS(ns, "text"); x.setAttribute("x", 2); x.setAttribute("y", 17); x.textContent = t; svg.append(x); return svg; };
  if (fields.some((v) => v === "" || v == null || isNaN(+v))) return text(fields.some((v) => typeof v === "string" && v) ? "depends on draws" : "");
  if (p.dist === "fixed") return text(`= ${fmtNum(+p.value)}`);
  if (p.dist === "loguniform" && (+p.low <= 0 || +p.high <= 0)) return text("bounds must be > 0");
  if (p.dist !== "truncated_exponential" && +p.high < +p.low) return text("high < low");
  const xs = Array.from({ length: 600 }, () => sampleOnce(p));
  const log = p.dist === "loguniform", tf = (v) => log ? Math.log(v) : v;
  let lo = Math.min(...xs.map(tf)), hi = Math.max(...xs.map(tf)); if (hi === lo) hi = lo + 1;
  const B = 20, h = new Array(B).fill(0);
  for (const x of xs) h[Math.min(B - 1, Math.floor((tf(x) - lo) / (hi - lo) * B))]++;
  const m = Math.max(...h);
  let d = "M0,28";
  h.forEach((c, i) => { const y = 28 - (c / m) * 24; d += ` L${(i / B) * 92},${y} L${((i + 1) / B) * 92},${y}`; });
  const path = document.createElementNS(ns, "path"); path.setAttribute("d", d + " L92,28 Z"); svg.append(path);
  return svg;
}

function priorRow(label, hint, holder, key, flagName) {
  const vals = el("div", { class: "vals" }), sp = el("div");
  const redraw = () => sp.replaceChildren(spark(holder[key]));
  const drawVals = () => {
    vals.replaceChildren();
    const p = holder[key];
    for (const f of DISTS[p.dist]) {
      vals.append(el("input", { value: p[f] ?? "", placeholder: f, title: f, "aria-label": `${label} ${f}`,
        oninput: (e) => { p[f] = parseVal(e.target.value); redraw(); changed(); } }));
    }
    redraw();
  };
  const sel = el("select", { "aria-label": `${label} distribution`, onchange: (e) => {
    const old = holder[key], d = e.target.value, n = { dist: d };
    const first = old.value ?? old.low ?? old.mean ?? 0;
    for (const f of DISTS[d]) n[f] = old[f] ?? (f === "value" ? first : f === "upper" ? (old.high ?? first) : (old.low ?? first));
    holder[key] = n; drawVals(); changed();
  } }, Object.keys(DISTS).map((d) => el("option", { value: d, selected: holder[key].dist === d }, DIST_LABEL[d])));
  drawVals();
  return el("div", { class: "prior" },
    el("div", { class: "lbl" }, el("b", {}, label), flagName ? flag(flagName) : null, el("small", {}, hint)), sel, vals, sp);
}

// A switch that adds or removes an optional field; `body` draws the field's editor.
function optional(label, hint, holder, key, def, body, flagName) {
  const box = el("div");
  const draw = () => {
    box.replaceChildren(el("label", { class: "switch" },
      el("input", { type: "checkbox", checked: holder[key] != null && holder[key] !== false, onchange: (e) => {
        if (e.target.checked) holder[key] = structuredClone(def); else delete holder[key];
        draw(); changed();
      } }), el("span", {}, label), flagName ? flag(flagName) : null, hint ? el("small", { class: "muted" }, hint) : null));
    if (holder[key] != null && holder[key] !== false && body) box.append(el("div", { class: "opt-body" }, body()));
  };
  draw();
  return box;
}
const optionalPrior = (label, hint, holder, key, def, flagName) =>
  optional(label, "", holder, key, def, () => priorRow(label, hint, holder, key), flagName);

const numField = (label, obj, key, attrs = {}, flagName) => el("label", { class: "field" },
  el("span", {}, label, flagName ? " " : null, flagName ? flag(flagName) : null),
  el("input", { type: "number", value: obj[key] ?? "", ...attrs, oninput: (e) => {
    if (e.target.value === "" && attrs.optional) delete obj[key]; else obj[key] = +e.target.value; changed(); } }));
const textField = (label, obj, key, after, attrs = {}) => el("label", { class: "field" }, el("span", {}, label),
  el("input", { value: obj[key] ?? "", spellcheck: "false", ...attrs, oninput: (e) => {
    if (e.target.value === "" && attrs.optional) delete obj[key]; else obj[key] = e.target.value;
    after && after(); changed(); } }));
const toggle = (label, obj, key, flagName, hint) => el("label", { class: "switch" },
  el("input", { type: "checkbox", checked: !!obj[key], onchange: (e) => { if (e.target.checked) obj[key] = true; else delete obj[key]; changed(); } }),
  el("span", {}, label), flagName ? flag(flagName) : null, hint ? el("small", { class: "muted" }, hint) : null);
const popSelect = (label, obj, key, allowAll) => {
  const n = Math.max(1, (spec.populations || []).length);
  const opts = [];
  if (allowAll) opts.push(el("option", { value: "", selected: obj[key] == null }, "all pairs"));
  for (let i = 0; i < n; i++) opts.push(el("option", { value: i, selected: obj[key] === i }, popName(i)));
  return el("label", { class: "field" }, el("span", {}, label), el("select", { onchange: (e) => {
    if (e.target.value === "") delete obj[key]; else obj[key] = +e.target.value; changed(); } }, opts));
};
const popName = (i) => `${i} · ${(spec.populations || [])[i]?.name || (i === 0 ? "main" : "pop" + i)}`;

function card(title, hint, jump, ...body) {
  return el("div", { class: "card", "data-jump": jump, id: "sec-" + jump.toLowerCase() },
    el("h3", {}, title), hint ? el("p", { class: "hint" }, hint) : null, ...body);
}

// A list of objects with an "add" button; row(item) draws one item's fields.
function listEditor(arr, addLabel, make, row) {
  const box = el("div");
  arr.forEach((item, k) => box.append(el("div", { class: "listrow" }, row(item, k),
    el("button", { class: "x", title: "Remove", onclick: () => { arr.splice(k, 1); render(); changed(); } }, "×"))));
  box.append(el("button", { class: "link", onclick: () => { arr.push(make()); render(); changed(); } }, "+ " + addLabel));
  return box;
}

// ---------- class templates ---------------------------------------------------------
const baseSweep = () => ({ mode: "stochastic", s: { dist: "loguniform", low: 0.005, high: 0.1 },
  f0: fixedP(0), tau: fixedP(0), position: fixedP(0.5) });
const TEMPLATES = [
  { id: "neutral", title: "Neutral", hint: "No selection", make: () => ({}) },
  { id: "hard", title: "Hard sweep", hint: "New mutation, f₀ = 0", make: () => ({ sweep: baseSweep() }) },
  { id: "soft", title: "Soft sweep", hint: "Standing variation, f₀ > 0", make: () => ({ sweep: { ...baseSweep(), f0: { dist: "loguniform", low: 0.01, high: 0.2 } } }) },
  { id: "partial", title: "Partial sweep", hint: "Stops at frequency c (-c)", make: () => ({ sweep: { ...baseSweep(), partial_final_freq: { dist: "uniform", low: 0.5, high: 0.9 } } }) },
  { id: "old", title: "Old sweep", hint: "Ended τ generations ago", make: () => ({ sweep: { ...baseSweep(), tau: { dist: "uniform", low: 0, high: 2000 } } }) },
  { id: "linked", title: "Linked sweep", hint: "Outside the window (-ls)", make: () => ({ sweep: { ...baseSweep(), location: "left_of_window", left_distance_bp: { dist: "loguniform", low: 1000, high: 100000 } } }) },
  { id: "rhh", title: "Recurrent hitchhiking", hint: "Repeated sweeps (-R/-L)", make: () => ({ sweep: { ...baseSweep(), recurrent_rate: fixedP(0.05), effective_size: fixedP("N") } }) },
  { id: "drift", title: "Neutral fixation", hint: "Allele fixes by drift (-wn)", make: () => ({ sweep: { ...baseSweep(), mode: "neutral" } }) },
];

function kindOf(c) {
  const sw = c.sweep;
  if (!sw) return "Neutral";
  if (sw.recurrent_rate) return "Recurrent hitchhiking";
  if (sw.location === "left_of_window") return "Linked sweep";
  if (sw.partial_final_freq) return "Partial sweep";
  if (sw.mode === "neutral") return "Neutral fixation";
  const soft = !(sw.f0?.dist === "fixed" && +sw.f0.value === 0);
  return (soft ? "Soft" : "Hard") + " sweep" + (sw.mode === "deterministic" ? " (deterministic)" : "");
}

function uniqueName(base) {
  const taken = new Set(spec.classes.map((c) => c.name));
  if (!taken.has(base)) return base;
  for (let i = 2; ; i++) if (!taken.has(base + i)) return base + i;
}

function addClass(t) {
  const name = uniqueName(t.id === "custom" ? "class" : t.id);
  spec.classes.push({ name, count: spec.classes[0]?.count || 100, ...t.make() });
  render(); changed();
  toast(`Added class “${name}”`);
  setTimeout(() => document.querySelectorAll(".cls")[spec.classes.length - 1]?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
}

// ---------- form ------------------------------------------------------------------
function render() {
  const f = $("#form");
  const y = window.scrollY;
  f.replaceChildren();

  const presetSel = el("select", { "aria-label": "Preset", onchange: (e) => {
    if (e.target.value) loadSpec(structuredClone(INFO.presets[e.target.value].spec));
  } }, el("option", { value: "" }, "Choose a preset…"),
    Object.keys(INFO.presets).map((k) => el("option", { value: k, selected: spec.name === k }, k)));
  const fileIn = el("input", { type: "file", accept: ".json", hidden: true, onchange: async (e) => {
    const file = e.target.files[0]; if (!file) return;
    try { loadSpec(JSON.parse(await file.text())); toast("Spec loaded"); } catch (err) { alert("Not a valid spec file: " + err.message); }
  } });
  f.append(card("Start from", INFO.presets[spec.name]?.description || "Your own settings. Save them as a JSON file to reuse or share.", "Start",
    el("div", { class: "row gap wrap" }, el("div", { style: "flex:1;min-width:200px" }, presetSel),
      el("button", { class: "ghost", onclick: () => fileIn.click() }, "Open spec…"),
      el("button", { class: "ghost", onclick: saveSpec }, "Save spec"), fileIn)));

  f.append(card("Dataset", "Each file gets its own random values, seeded from “seed-class-number”, so the same settings always give the same files.", "Basics",
    el("div", { class: "grid2" },
      textField("Name", spec, "name", () => { if (!outTouched) $("#out").value = defaultOut(); }),
      textField("Seed", spec, "seed"),
      numField("Haplotypes per replicate (individuals × 2)", spec, "sample_size", { min: 2 }),
      numField("Region length (bp)", spec, "sites", { min: 1 }),
      numField("Replicates per file", spec, "replicates_per_file", { min: 1 })),
    el("div", { class: "row gap wrap" },
      toggle("One folder per class", spec, "folder_per_class", null, "Neutral/neutral_1.ms"),
      toggle("Output trees instead of haplotypes", spec, "tree_output", "-T", "QC and ML export need haplotypes"))));
  if (spec.folder_per_class === undefined) spec.folder_per_class = true;

  f.append(card("Population", "Physical units; the app works out θ = 4NμL and ρ = 4NrL for discoal. Bounds can use N, mu, r, L, n, e.g. 1/(2*N). The small chart previews each distribution.", "Population",
    priorRow("N", "population size (diploid)", spec, "N"),
    priorRow("μ", "mutation rate / bp / gen", spec, "mu", "-t"),
    priorRow("r", "recombination / bp / gen", spec, "r", "-r")));

  // demography and structure
  spec.demography ||= []; spec.populations ||= []; spec.splits ||= []; spec.admixture ||= [];
  spec.migration ||= []; spec.ancient_samples ||= [];
  const multi = spec.populations.length >= 2;
  const sizeChanges = listEditor(spec.demography, "Add a size change",
    () => ({ generations_ago: fixedP(2000), size: fixedP(5000) }),
    (ev) => el("div", {}, priorRow("When", "generations ago", ev, "generations_ago", "-en"),
      priorRow("New size", "individuals (back in time)", ev, "size"), multi ? popSelect("Population", ev, "population") : null));
  f.append(card("Demography", "Instantaneous size changes going back in time. Leave empty for a constant size.", "Demography", sizeChanges));

  const popSum = spec.populations.reduce((a, p) => a + (+p.sample_size || 0), 0);
  const structure = el("div", {},
    el("div", { class: "sub" }, "Sampled populations ", flag("-p")),
    el("p", { class: "hint" }, "Two or more populations make a structured model. Sweeps happen in population 0. ",
      multi ? el("b", { style: popSum === spec.sample_size ? "" : "color:var(--err)" }, `Samples add up to ${popSum} of ${spec.sample_size}.`) : null),
    listEditor(spec.populations, "Add a population",
      () => ({ name: spec.populations.length ? `pop${spec.populations.length}` : "main", sample_size: spec.populations.length ? 0 : spec.sample_size }),
      (p, k) => el("div", { class: "mini" }, el("b", { class: "small muted", style: "align-self:center" }, `#${k}`),
        textField("Name", p, "name"), numField("Haplotypes sampled", p, "sample_size", { min: 0 }))));
  if (multi) {
    structure.append(
      el("div", { class: "sub" }, "Migration ", flag("-M"), " ", flag("-m")),
      listEditor(spec.migration, "Add migration", () => ({ rate: fixedP(1e-4) }),
        (m) => el("div", {}, priorRow("Rate", "fraction of migrants / gen (app passes 4Nm)", m, "rate"),
          el("div", { class: "mini" }, popSelect("From", m, "from_pop", true), popSelect("To", m, "to_pop", true)))),
      el("div", { class: "sub" }, "Population splits ", flag("-ed")),
      listEditor(spec.splits, "Add a split", () => ({ generations_ago: fixedP(10000), population: 1, into: 0 }),
        (sp) => el("div", {}, priorRow("When", "generations ago", sp, "generations_ago"),
          el("div", { class: "mini" }, popSelect("Population", sp, "population"), popSelect("Joins", sp, "into")))),
      el("div", { class: "sub" }, "Admixture ", flag("-ea")),
      listEditor(spec.admixture, "Add an admixture event",
        () => ({ generations_ago: fixedP(500), daughter: 0, founder1: 1, founder2: Math.min(2, spec.populations.length - 1), proportion: fixedP(0.5) }),
        (a) => el("div", {}, priorRow("When", "generations ago", a, "generations_ago"),
          priorRow("Proportion", "share from founder 1", a, "proportion"),
          el("div", { class: "mini" }, popSelect("Admixed", a, "daughter"), popSelect("Founder 1", a, "founder1"), popSelect("Founder 2", a, "founder2")))));
  }
  structure.append(el("div", { class: "sub" }, "Ancient samples ", flag("-A")),
    el("p", { class: "hint" }, "Part of the haplotypes are sampled in the past instead of today."),
    listEditor(spec.ancient_samples, "Add ancient samples", () => ({ size: 2, population: 0, generations_ago: fixedP(1000) }),
      (a) => el("div", {}, el("div", { class: "mini" }, numField("Haplotypes", a, "size", { min: 1 }), multi ? popSelect("Population", a, "population") : null),
        priorRow("When", "generations ago", a, "generations_ago"))));
  f.append(card("Population structure (optional)", "Several populations, migration, splits, admixture and ancient samples.", "Structure", structure));

  // classes
  const classes = el("div");
  spec.classes.forEach((c, k) => classes.append(classCard(c, k)));
  const gallery = el("div", { class: "gallery" },
    [...TEMPLATES, { id: "custom", title: "Custom…", hint: "Neutral class to edit", make: () => ({}) }]
      .map((t) => el("button", { class: "tpl", onclick: () => addClass(t) }, el("b", {}, "+ " + t.title), el("small", {}, t.hint))));
  f.append(card("Classes (labels)", "One class per kind of file, each with its own name, file count and folder. Give two classes the same ML label to merge them for training.", "Classes",
    classes, el("div", { class: "sub" }, "Add a class"), gallery));

  // advanced
  const gcBody = () => {
    const gc = spec.gene_conversion, byRatio = gc.conversion_to_crossover_ratio != null;
    return el("div", {},
      el("div", { class: "row gap wrap" }, el("label", { class: "switch" },
        el("input", { type: "checkbox", checked: !byRatio, onchange: (e) => {
          if (e.target.checked) { delete gc.conversion_to_crossover_ratio; gc.rate_per_bp = 1e-8; } else { delete gc.rate_per_bp; gc.conversion_to_crossover_ratio = 1; }
          render(); changed(); } }), el("span", {}, "Give an absolute rate instead of a ratio"), flag(byRatio ? "-gr" : "-g"))),
      el("div", { class: "grid2" },
        byRatio ? numField("Conversion : crossover ratio", gc, "conversion_to_crossover_ratio", { step: "any" })
          : numField("Initiation rate / bp / gen", gc, "rate_per_bp", { step: "any" }),
        numField("Mean tract length (bp)", gc, "mean_tract_length")));
  };
  f.append(card("Advanced (optional)", "Rarely needed discoal options. Everything here is off unless you switch it on.", "Advanced",
    optional("Gene conversion", "", spec, "gene_conversion", { conversion_to_crossover_ratio: 1, mean_tract_length: 300 }, gcBody, "-gr / -g"),
    optional("Only mutations younger than", "", spec, "mutations_until", fixedP(1000),
      () => priorRow("Age limit", "generations", spec, "mutations_until"), "-U")));

  window.scrollTo(0, y);
  buildJump();
}

function classCard(c, k) {
  const body = el("div");
  const sw = c.sweep;
  if (sw) {
    for (const [key, def] of [["f0", fixedP(0)], ["tau", fixedP(0)], ["position", fixedP(0.5)]]) sw[key] = sw[key] || def;
    const where = el("label", { class: "field" }, el("span", {}, "Where is the selected site?"),
      el("select", { onchange: (e) => {
        delete sw.recurrent_rate; sw.location = "in_window";
        if (e.target.value === "left") { sw.location = "left_of_window"; sw.left_distance_bp ||= { dist: "loguniform", low: 1000, high: 100000 }; }
        if (e.target.value === "rhh" || e.target.value === "rhhL") { sw.recurrent_rate = fixedP(0.05); sw.effective_size ||= fixedP("N"); sw.recurrent_side = e.target.value === "rhhL"; }
        render(); changed();
      } }, [["in", "In the window (-ws/-wd/-wn)"], ["left", "Left of the window (-ls/-ld/-ln)"],
        ["rhh", "Recurrent sweeps at the locus (-R)"], ["rhhL", "Recurrent sweeps to the side (-L)"]]
        .map(([v, t]) => el("option", { value: v, selected: (sw.recurrent_rate ? (sw.recurrent_side ? "rhhL" : "rhh") : sw.location === "left_of_window" ? "left" : "in") === v }, t))));
    body.append(...[
      el("div", { class: "grid2", style: "margin-top:10px" },
        el("label", { class: "field" }, el("span", {}, "Trajectory"),
          el("select", { onchange: (e) => { sw.mode = e.target.value; render(); changed(); } },
            [["stochastic", "Stochastic (-ws)"], ["deterministic", "Deterministic (-wd)"], ["neutral", "Neutral fixation (-wn)"]]
              .map(([v, t]) => el("option", { value: v, selected: sw.mode === v }, t)))), where),
      priorRow("s", "selection coefficient (app passes α = 2Ns)", sw, "s", "-a"),
      priorRow("f₀", "start frequency: 0 = hard, > 0 = soft", sw, "f0", "-f"),
      sw.recurrent_rate ? priorRow("Sweep rate", "per 2N individuals / gen", sw, "recurrent_rate", sw.recurrent_side ? "-L" : "-R") : null,
      !sw.recurrent_rate ? priorRow("τ", "generations since the sweep ended", sw, "tau") : null,
      sw.location === "left_of_window" && !sw.recurrent_rate ? priorRow("Distance", "bp to the left of the window", sw, "left_distance_bp") : null,
      sw.location !== "left_of_window" && !sw.recurrent_rate ? priorRow("Position", "selected site, 0–1 along the region", sw, "position", "-x") : null,
      optionalPrior("Partial sweep", "final frequency", sw, "partial_final_freq", { dist: "uniform", low: 0.5, high: 0.9 }, "-c"),
      el("details", { class: "adv" }, el("summary", {}, "More sweep options"),
        optionalPrior("Recurrent beneficial mutation", "θ_A = 4N·u_A", sw, "recurrent_theta_a", fixedP(0.1), "-uA"),
        optionalPrior("Sweep population size", "N used for the trajectory; N = same as above", sw, "effective_size", fixedP("N"), "-N"),
        numField("Time step scalar (default 400)", sw, "time_step", { min: 1, optional: true, placeholder: "400" }, "-i"),
        sw.partial_final_freq ? toggle("Hide the selected SNP", sw, "hide_selected_snp", "-h") : null,
        optional("Require recombination during the sweep", "", sw, "recombination_during_sweep",
          { left_site: Math.round(spec.sites * 0.25), right_site: Math.round(spec.sites * 0.75) },
          () => el("div", { class: "grid2" }, numField("From site", sw.recombination_during_sweep, "left_site", { min: 0 }),
            numField("To site", sw.recombination_during_sweep, "right_site", { min: 1 })), "-C"))].filter(Boolean));
  }
  body.append(el("details", { class: "adv" }, el("summary", {}, "discoal's own per-replicate priors"),
    el("p", { class: "hint" }, "The app draws values per file. To vary values between replicates inside one file, add discoal’s ",
      flag("-Pt"), " ", flag("-Pr"), " ", flag("-Pre"), " ", flag("-Pa"), " ", flag("-Pu"), " ", flag("-PuA"), " ", flag("-Px"), " ",
      flag("-Pf"), " ", flag("-Pc"), " ", flag("-Pe1"), " ", flag("-Pe2"), " flags here, in discoal’s scaled units."),
    textField("Extra discoal arguments", c, "extra_args", null, { placeholder: "e.g. -Pa 100 1000", optional: true })));

  const kind = kindOf(c), color = COLORS[k % COLORS.length];
  return el("div", { class: "cls", style: `--cc: var(${color})` }, el("div", { class: "bar-top" }),
    el("div", { class: "inner" },
      el("div", { class: "row between", style: "margin-bottom:8px" }, el("span", { class: "kind" }, kind),
        el("div", { class: "cls-tools" },
          el("button", { class: "x", title: "Duplicate class", onclick: () => {
            const copy = structuredClone(c); copy.name = uniqueName(c.name);
            spec.classes.splice(k + 1, 0, copy); render(); changed(); toast(`Duplicated as “${copy.name}”`); } }, "⧉"),
          el("button", { class: "x", title: "Move up", disabled: k === 0, onclick: () => {
            [spec.classes[k - 1], spec.classes[k]] = [spec.classes[k], spec.classes[k - 1]]; render(); changed(); } }, "↑"),
          el("button", { class: "x", title: "Remove class", disabled: spec.classes.length < 2,
            onclick: () => { spec.classes.splice(k, 1); render(); changed(); } }, "×"))),
      el("div", { class: "head" },
        textField("Class name (folder)", c, "name"),
        textField("ML label", c, "label", null, { placeholder: c.name, optional: true }),
        numField("Files", c, "count", { min: 1 }),
        el("label", { class: "field" }, el("span", {}, "Type"),
          el("select", { onchange: (e) => { if (e.target.value === "sweep") c.sweep = baseSweep(); else delete c.sweep; render(); changed(); } },
            el("option", { value: "neutral", selected: !c.sweep }, "Neutral"), el("option", { value: "sweep", selected: !!c.sweep }, "Selection")))),
      body));
}

function buildJump() {
  $("#jump").replaceChildren(...[...document.querySelectorAll("[data-jump]")].map((s) => {
    if (!s.id) s.id = "sec-" + s.dataset.jump.toLowerCase();
    return el("a", { href: "#" + s.id }, s.dataset.jump);
  }));
}

// ---------- plan ------------------------------------------------------------------
let checkTimer = null;
function changed() { clearTimeout(checkTimer); checkTimer = setTimeout(checkSpec, 250); }

function clean(s) {
  // Drop empty optional lists/fields so saved specs stay short.
  const o = structuredClone(s);
  for (const k of ["demography", "populations", "splits", "admixture", "migration", "ancient_samples"]) if (o[k] && !o[k].length) delete o[k];
  for (const c of o.classes || []) { if (!c.label) delete c.label; if (!c.extra_args) delete c.extra_args; }
  return o;
}

async function checkSpec() {
  try {
    const r = await api("/check", { spec: clean(spec) });
    $("#total").textContent = r.total_files.toLocaleString();
    const tot = spec.classes.reduce((a, c) => a + (+c.count || 0), 0) || 1;
    $("#dist").replaceChildren(...spec.classes.map((c, k) => el("i", { title: `${c.name}: ${c.count}`,
      style: `width:${100 * c.count / tot}%;background:var(${COLORS[k % COLORS.length]})` })));
    $("#warnings").replaceChildren(el("div", { class: "legend2" }, spec.classes.map((c, k) =>
      el("span", { style: `--cc:var(${COLORS[k % COLORS.length]})` }, `${c.name} ${(+c.count).toLocaleString()}` + (c.label && c.label !== c.name ? ` → ${c.label}` : "")))),
      ...r.warnings.map((w) => el("div", { class: "warn" }, w)));
    $("#examples").replaceChildren(...r.examples.map((x) =>
      el("div", { class: "cmd" }, el("span", { class: "f" }, x.file), x.command,
        el("button", { class: "copy ghost", onclick: () => navigator.clipboard?.writeText(x.command).then(() => toast("Command copied")) }, "Copy"))));
    $("#run").disabled = false;
  } catch (e) {
    $("#warnings").replaceChildren(el("div", { class: "warn" }, e.message));
    $("#examples").replaceChildren();
    $("#run").disabled = true;
  }
}

function loadSpec(s) {
  spec = s; outTouched = false;
  render(); $("#out").value = defaultOut(); $("#h-folder").value = defaultOut() + "_hpc"; checkSpec();
}
const defaultOut = () => `${INFO.data_root}/${spec.name}`;

function saveSpec() {
  const blob = new Blob([JSON.stringify(clean(spec), null, 2)], { type: "application/json" });
  const a = el("a", { href: URL.createObjectURL(blob), download: `${spec.name}.json` });
  document.body.append(a); a.click(); a.remove();
}

// ---------- describe it (assistant) -----------------------------------------------
const EXAMPLES = [
  "3000 neutral and 3000 soft sweeps, 99 CEU individuals, 1.1 Mb, N uniform 5k-30k",
  "hard, soft and neutral, 500 files each, 50 individuals, 200 kb",
  "add a bottleneck to 2,000 individuals 1,000 generations ago",
  "two populations of 20 haplotypes each that split 10,000 generations ago",
];

async function ask() {
  const box = $("#ask-in"), prompt = box.value.trim();
  if (!prompt) return;
  const chat = $("#chat");
  chat.append(el("div", { class: "bubble you" }, prompt));
  const wait = el("div", { class: "bubble bot muted" }, "Drafting a spec…");
  chat.append(wait); chat.scrollTop = chat.scrollHeight;
  $("#ask-go").disabled = true;
  try {
    const before = structuredClone(spec);
    const r = await api("/assistant", { prompt, spec: clean(spec) });
    box.value = "";
    loadSpec(r.spec);
    const undo = el("button", { class: "link", onclick: () => { loadSpec(before); undo.disabled = true; undo.textContent = "Restored"; } }, "Undo");
    wait.replaceWith(el("div", { class: "bubble bot" }, r.summary || "Here is a spec.",
      el("ul", {}, r.outline.map((x) => el("li", {}, x))),
      r.warnings.length ? r.warnings.map((w) => el("div", { class: "warn" }, w)) : null,
      el("div", { class: "acts small muted" }, "Loaded into the form below. Check it, then Generate in step 2. ", undo)));
    tab("plan");
  } catch (e) {
    wait.replaceWith(el("div", { class: "bubble bot err" }, e.message));
  } finally { $("#ask-go").disabled = !!INFO.assistant_unavailable; chat.scrollTop = chat.scrollHeight; }
}

// ---------- about & cite ----------------------------------------------------------
const FLAG_MAP = [
  ["sampleSize numReplicates nSites", "Dataset: haplotypes, replicates per file, region length"],
  ["-t theta", "Population: μ (app passes 4NμL)"], ["-r rho", "Population: r (4NrL)"],
  ["-g / -gr", "Advanced: gene conversion, by rate or by ratio"], ["-p npops sizes…", "Population structure: sampled populations"],
  ["-en time pop size", "Demography: size changes (per population)"], ["-ed time pop1 pop2", "Population structure: splits"],
  ["-ea time d f1 f2 prop", "Population structure: admixture"], ["-M / -m", "Population structure: migration (4Nm)"],
  ["-A size pop time", "Population structure: ancient samples"],
  ["-ws / -wd / -wn tau", "Class: trajectory (stochastic, deterministic, neutral) and τ"],
  ["-ls / -ld / -ln tau leftRho", "Class: selected site left of the window, distance in bp (4Nr·d)"],
  ["-a alpha", "Class: s (2Ns)"], ["-x site", "Class: position"], ["-f F0", "Class: f₀ (soft sweeps)"],
  ["-c freq", "Class: partial sweep"], ["-h", "Class › More: hide the selected SNP"], ["-uA rate", "Class › More: recurrent beneficial mutation"],
  ["-N size", "Class › More: sweep population size"], ["-i dt", "Class › More: time step scalar"],
  ["-R / -L rate", "Class: recurrent sweeps at the locus / to the side"], ["-C left right", "Class › More: require recombination during the sweep"],
  ["-U time", "Advanced: only mutations younger than"], ["-T", "Dataset: output trees"],
  ["-d seed1 seed2", "Set by the app for every file (reproducible)"],
  ["-Pt -Pr -Pre -Pa -Pu -PuA -Px -Pf -Pc -Pe1 -Pe2", "Class › discoal's own per-replicate priors (the app's per-file priors cover the same parameters in physical units)"],
];

function about() {
  const b = $("#about-body");
  b.replaceChildren(
    el("p", {}, el("b", {}, "discoal Studio"), ` ${INFO.version} — designed and written by `, el("b", {}, "Tanvir Anjum Joarder"),
      " (Florida Atlantic University). It builds and runs discoal commands; the simulations themselves are discoal’s."),
    el("p", { class: "small muted" }, "© 2026 Tanvir Anjum Joarder. Free software under the GNU GPL v3 or later (required because it ships discoal, which is GPL-3.0). " +
      "Anyone may use, study, change and share it under that license; redistributed or modified versions must keep the author attribution (see NOTICE). " +
      "discoal © Andrew D. Kern and Daniel R. Schrider."),
    el("h4", {}, "Please cite both"),
    el("pre", {}, INFO.cite),
    el("pre", {}, `@software{joarder_discoal_studio_2026,
  author  = {Joarder, Tanvir Anjum},
  title   = {discoal Studio: reproducible discoal selective-sweep datasets on your own computer},
  year    = {2026},
  version = {${INFO.version}},
  license = {GPL-3.0-or-later}
}
@article{kern_schrider_discoal_2016,
  author  = {Kern, Andrew D. and Schrider, Daniel R.},
  title   = {Discoal: flexible coalescent simulations with selection},
  journal = {Bioinformatics}, volume = {32}, number = {24}, pages = {3839--3841}, year = {2016},
  doi     = {10.1093/bioinformatics/btw556}
}`),
    el("button", { class: "ghost sm", onclick: () => navigator.clipboard?.writeText(INFO.cite).then(() => toast("Citation copied")) }, "Copy citation"),
    el("h4", {}, "Every discoal option, and where to set it"),
    el("table", { class: "flags" }, FLAG_MAP.map(([f, w]) => el("tr", {}, el("td", {}, flag(f)), el("td", {}, w)))));
  $("#about").showModal();
}

// ---------- background tasks ------------------------------------------------------
function watch(onDone) {
  clearInterval(poll);
  poll = setInterval(async () => {
    const t = await api("/status").catch(() => null);
    if (!t) return;
    if (t.kind === "run") showRun(t);
    else if (t.total) $("#res-msg").textContent = `Working… ${t.done} / ${t.total}`;
    if (t.state !== "running") { clearInterval(poll); onDone && onDone(t); }
  }, 600);
}

function showRun(t) {
  const p = t.progress || {};
  $("#progress").hidden = false;
  const pct = p.total ? (100 * (p.done + p.failed) / p.total) : 0;
  $("#bar").style.width = pct + "%";
  $("#count").textContent = `${(p.done || 0).toLocaleString()} / ${(p.total || 0).toLocaleString()} files` + (p.failed ? ` · ${p.failed} failed` : "");
  $("#eta").textContent = t.state === "running" ? `about ${fmtTime(p.eta)} left` : `took ${fmtTime(p.elapsed)}`;
  $("#run-msg").textContent = t.message || p.message || "";
  $("#run-msg").className = "msg" + (t.state === "error" ? " err" : t.state === "done" ? " okmsg" : "");
  const running = t.state === "running";
  $("#run").disabled = running; $("#stop").hidden = !running;
  if (t.state === "done") toast("Dataset finished");
}

async function estimate() {
  $("#estimate-out").replaceChildren(el("p", { class: "muted" }, "Running a few test files…"));
  try {
    await api("/pilot", { spec: clean(spec) });
    watch((t) => {
      if (t.state === "error") return $("#estimate-out").replaceChildren(el("div", { class: "warn" }, t.message));
      const r = t.result;
      $("#estimate-out").replaceChildren(el("div", { class: "kv" },
        el("span", {}, "Test files"), el("b", {}, `${r.files_tested}${r.failed ? ` (${r.failed} failed)` : ""}`),
        el("span", {}, "Per file"), el("b", {}, fmtTime(r.seconds_per_file)),
        el("span", {}, `Total on ${r.workers} cores`), el("b", {}, fmtTime(r.estimated_seconds)),
        el("span", {}, "Disk needed"), el("b", {}, fmtBytes(r.estimated_bytes)),
        el("span", {}, "Free disk"), el("b", { style: r.enough_disk ? "" : "color:var(--err)" }, fmtBytes(r.free_bytes))),
        el("p", { class: "small muted" }, "Rough guide: sweep strength and N vary, so real times spread around this."));
    });
  } catch (e) { $("#estimate-out").replaceChildren(el("div", { class: "warn" }, e.message)); }
}

async function run() {
  tab("run");
  try {
    await api("/run", { spec: clean(spec), out: $("#out").value, workers: +$("#workers").value || null });
    showRun({ state: "running", progress: {} });
    watch((t) => { showRun(t); refreshEngine(); });
  } catch (e) { $("#run-msg").textContent = e.message; $("#run-msg").className = "msg err"; }
}

async function qc() {
  $("#res-msg").textContent = "Reading files…"; $("#res-msg").className = "msg";
  try {
    await api("/qc", { out: $("#out").value });
    watch((t) => {
      if (t.state === "error") { $("#res-msg").textContent = t.message; $("#res-msg").className = "msg err"; return; }
      $("#res-msg").textContent = "Saved qc_stats.csv and qc_summary.json in the output folder.";
      $("#res-msg").className = "msg okmsg";
      drawCharts(t.result);
    });
  } catch (e) { $("#res-msg").textContent = e.message; $("#res-msg").className = "msg err"; }
}

async function exportMl() {
  $("#res-msg").textContent = "Building arrays…"; $("#res-msg").className = "msg";
  try {
    await api("/export-ml", { out: $("#out").value, snps: +$("#snps").value });
    watch((t) => {
      $("#res-msg").textContent = t.state === "error" ? t.message : `Saved ${t.result}  (X, positions, y, classes, files)`;
      $("#res-msg").className = "msg " + (t.state === "error" ? "err" : "okmsg");
    });
  } catch (e) { $("#res-msg").textContent = e.message; $("#res-msg").className = "msg err"; }
}

// ---------- charts ----------------------------------------------------------------
const STAT_LABEL = { segsites: "Segregating sites", pi: "π (pairwise differences)", theta_w: "Watterson's θ",
  tajimas_d: "Tajima's D", h12: "H12 (central SNPs)", h2_h1: "H2/H1 (central SNPs)", haplotypes: "Distinct haplotypes (central)" };

function drawCharts(summary) {
  const classes = Object.keys(summary);
  const box = $("#charts"); box.replaceChildren();
  for (const stat of Object.keys(STAT_LABEL)) {
    const all = classes.flatMap((c) => summary[c][stat].values);
    let lo = Math.min(...all), hi = Math.max(...all); if (hi === lo) hi = lo + 1;
    const B = 28, W = 400, H = 110, pad = 18;
    const hist = classes.map((c) => {
      const h = new Array(B).fill(0), v = summary[c][stat].values;
      for (const x of v) h[Math.min(B - 1, Math.floor((x - lo) / (hi - lo) * B))]++;
      return h.map((n) => n / v.length);
    });
    const ymax = Math.max(...hist.flat());
    const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H + pad}`); svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `${STAT_LABEL[stat]} by class`);
    hist.forEach((h, ci) => {
      let d = `M0,${H}`;
      h.forEach((y, b) => { const yy = H - (y / ymax) * (H - 6); d += ` L${(b / B) * W},${yy} L${((b + 1) / B) * W},${yy}`; });
      const path = document.createElementNS(ns, "path");
      path.setAttribute("d", d + ` L${W},${H} Z`);
      path.setAttribute("fill", `var(${COLORS[ci % COLORS.length]})`); path.setAttribute("fill-opacity", "0.28");
      path.setAttribute("stroke", `var(${COLORS[ci % COLORS.length]})`); path.setAttribute("stroke-width", "1.5");
      svg.append(path);
    });
    const axis = document.createElementNS(ns, "line");
    Object.entries({ x1: 0, x2: W, y1: H, y2: H, stroke: "var(--line)" }).forEach(([k, v]) => axis.setAttribute(k, v));
    svg.append(axis);
    for (const [x, t, a] of [[2, fmtNum(+lo.toPrecision(3)), "start"], [W - 2, fmtNum(+hi.toPrecision(3)), "end"]]) {
      const tx = document.createElementNS(ns, "text");
      Object.entries({ x, y: H + 14, "text-anchor": a, "font-size": 11, fill: "var(--muted)" }).forEach(([k, v]) => tx.setAttribute(k, v));
      tx.textContent = t; svg.append(tx);
    }
    const med = classes.map((c, ci) => el("span", {}, el("i", { style: `background:var(${COLORS[ci % COLORS.length]})` }),
      `${c} median ${fmtNum(+summary[c][stat].median.toPrecision(4))}`));
    box.append(el("div", { class: "chart" }, el("h5", {}, STAT_LABEL[stat]), svg, el("div", { class: "legend" }, med)));
  }
}

// ---------- shell -----------------------------------------------------------------
function tab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => p.hidden = p.dataset.panel !== name);
}

async function refreshEngine() {
  INFO = await api("/info");
  const e = $("#engine"); e.replaceChildren();
  if (INFO.engine) {
    e.append(el("span", { class: "chip", title: `${INFO.engine.path}\nbinary ${INFO.engine.sha256_16} · source ${INFO.engine.source_sha256_16}\n${INFO.engine.compiler || ""}` }, "● discoal ready"));
  } else {
    e.append(el("span", { class: "chip bad" }, "discoal not built"),
      el("button", { class: "ghost sm", disabled: !INFO.can_build, title: INFO.can_build ? "" : "Install a C compiler first (see README)",
        onclick: async () => { await api("/engine/build", {}); watch(refreshEngine); } }, "Build now"));
  }
  e.append(el("span", { class: "muted" }, `${INFO.cpus} cores`));
}

function setTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  try { t ? localStorage.setItem("theme", t) : localStorage.removeItem("theme"); } catch (_) { /* storage blocked */ }
}

async function main() {
  try { const t = localStorage.getItem("theme"); if (t) setTheme(t); } catch (_) { /* storage blocked */ }
  await refreshEngine();
  $("#version").textContent = "v" + INFO.version + " · by Tanvir Anjum Joarder";
  $("#workers").value = INFO.default_workers;
  $("#cpu-note").textContent = `(this computer has ${INFO.cpus}; one is left free)`;
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => tab(b.dataset.tab)));
  $("#out").addEventListener("input", () => outTouched = true);
  $("#ask-go").addEventListener("click", ask);
  $("#ask-in").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } });
  $("#ask-examples").replaceChildren(...EXAMPLES.map((x) => el("button", { class: "ghost", onclick: () => { $("#ask-in").value = x; $("#ask-in").focus(); } }, x)));
  if (INFO.assistant_unavailable) { $("#ask-go").disabled = true; $("#ask-note").textContent = INFO.assistant_unavailable; }
  $("#theme").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    setTheme(dark ? "light" : "dark");
  });
  $("#about-open").addEventListener("click", about);
  $("#about-open2").addEventListener("click", about);
  $("#about-close").addEventListener("click", () => $("#about").close());
  $("#estimate").addEventListener("click", estimate);
  $("#to-run").addEventListener("click", () => tab("run"));
  $("#run").addEventListener("click", run);
  $("#stop").addEventListener("click", () => api("/stop", {}));
  $("#open").addEventListener("click", () => api("/open", { out: $("#out").value }).catch((e) => alert(e.message)));
  $("#qc").addEventListener("click", qc);
  $("#ml").addEventListener("click", exportMl);
  $("#hpc").addEventListener("click", async () => {
    try {
      const r = await api("/hpc", { spec: clean(spec), folder: $("#h-folder").value, tasks: +$("#h-tasks").value, cpus: +$("#h-cpus").value,
        mem: $("#h-mem").value, time: $("#h-time").value, partition: $("#h-part").value });
      $("#hpc-msg").textContent = "Wrote " + r.files.join(", "); $("#hpc-msg").className = "msg okmsg";
    } catch (e) { $("#hpc-msg").textContent = e.message; $("#hpc-msg").className = "msg err"; }
  });
  loadSpec(structuredClone(INFO.presets.quick_demo.spec));
  const t = await api("/status");
  if (t.state === "running") { tab(t.kind === "run" ? "run" : "results"); watch((x) => x.kind === "run" && showRun(x)); }
}
main().catch((e) => document.body.prepend(el("div", { class: "warn" }, "Could not start: " + e.message)));
