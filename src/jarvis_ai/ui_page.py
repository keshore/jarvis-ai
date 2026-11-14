"""The window, as one self-contained page: no files, fonts or scripts are loaded from anywhere else, so it works offline.
The one expressive element is the voice line under the title; everything else stays quiet. Text from conversations is
always inserted as text, never as markup."""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jarvis</title>
<style>
:root {
  --paper: #f2f4f7; --panel: #ffffff; --ink: #17212b; --quiet: #5d6b79; --rule: #d6dce3; --wash: #e7ebf0;
  --signal: #3a4fd8; --hear: #0c8f8f; --think: #b5770f; --warn: #b3261e;
  --ui: "Avenir Next", "Segoe UI Variable Text", "Segoe UI", "Helvetica Neue", system-ui, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root { --paper: #141a22; --panel: #1b232d; --ink: #e6ebf1; --quiet: #93a1b0; --rule: #2c3743; --wash: #222c38;
          --signal: #9aa8ff; --hear: #4fd0cc; --think: #e6b455; --warn: #ff8a80; }
}
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body { background: var(--paper); color: var(--ink); font: 16px/1.5 var(--ui); display: grid; grid-template-columns: 272px 1fr; }
button, input, select, textarea { font: inherit; color: inherit; }
button { cursor: pointer; }
:focus-visible { outline: 2px solid var(--signal); outline-offset: 2px; }
[hidden] { display: none !important; }

/* ---- the list of conversations ---- */
#rail { background: var(--panel); border-right: 1px solid var(--rule); display: flex; flex-direction: column; min-height: 0; height: 100vh; }
#rail .head { padding: 16px 14px 10px; display: grid; gap: 10px; }
#new { padding: 9px 12px; border-radius: 8px; border: 1px solid var(--signal); background: var(--signal); color: var(--paper); font-weight: 600; text-align: left; }
#find { padding: 8px 10px; border: 1px solid var(--rule); border-radius: 8px; background: var(--paper); width: 100%; }
#list { flex: 1; overflow-y: auto; padding: 0 8px 8px; }
#list h2 { font-size: 13px; font-weight: 600; color: var(--quiet); margin: 14px 8px 4px; }
.item { display: block; width: 100%; text-align: left; background: none; border: 0; padding: 7px 8px; border-radius: 6px; }
.item:hover { background: var(--wash); }
.item[aria-current="true"] { background: var(--wash); box-shadow: inset 2px 0 0 var(--signal); }
.item .t { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 15px; }
.item .d { display: block; font-size: 13px; color: var(--quiet); }
#none { color: var(--quiet); font-size: 14px; padding: 10px 8px; }
#rail .foot { border-top: 1px solid var(--rule); padding: 10px 14px 14px; font-size: 13px; color: var(--quiet); display: grid; gap: 8px; }
#open { text-align: left; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--rule); background: none; font-size: 15px; }
#open:hover { border-color: var(--quiet); }

/* ---- the conversation ---- */
#stage { display: flex; flex-direction: column; min-width: 0; height: 100vh; }
header { display: flex; align-items: baseline; gap: 12px; padding: 16px 22px 4px; }
#menu { display: none; }
#title { font-size: 20px; font-weight: 600; letter-spacing: -0.01em; margin: 0; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
         background: none; border: 0; padding: 2px 4px; margin-left: -4px; border-radius: 6px; text-align: left; flex: 0 1 auto; }
input#title-edit { font-size: 20px; font-weight: 600; flex: 1; min-width: 0; padding: 2px 6px; border: 1px solid var(--signal); border-radius: 6px; background: var(--panel); }
#state { color: var(--quiet); font-size: 15px; white-space: nowrap; }
#state[data-s="hearing"] { color: var(--hear); }
#state[data-s="thinking"] { color: var(--think); }
#state[data-s="speaking"] { color: var(--signal); }
header .spacer { flex: 1; }
.plain { background: none; border: 0; padding: 5px 8px; border-radius: 6px; color: var(--quiet); font-size: 14px; white-space: nowrap; }
.plain:hover { color: var(--ink); background: var(--wash); }
.plain.danger:hover { color: var(--warn); }
#where { font-size: 13px; padding: 3px 9px; border-radius: 999px; border: 1px solid var(--rule); color: var(--quiet); white-space: nowrap; }
#where[data-cloud="true"] { border-color: var(--think); color: var(--think); }
#line { display: block; width: 100%; height: 64px; flex: none; }

main { flex: 1; overflow-y: auto; padding: 4px 22px 20px; }
#talk { max-width: 68ch; margin: 0 auto; }
.you { color: var(--quiet); font-size: 15px; margin: 22px 0 4px; padding-left: 12px; border-left: 2px solid var(--rule); white-space: pre-wrap; }
.turn { margin: 0 0 4px; }
.jarvis { font-size: 19px; line-height: 1.45; margin: 0; white-space: pre-wrap; }
.jarvis.live { color: color-mix(in srgb, var(--ink) 72%, transparent); }
.tools { display: flex; gap: 2px; margin: 2px 0 0 -8px; opacity: 0; transition: opacity .12s; }
.turn:hover .tools, .turn:focus-within .tools { opacity: 1; }
.tools .when { font-size: 13px; color: var(--quiet); padding: 5px 8px; }
.day { text-align: center; font-size: 13px; color: var(--quiet); margin: 22px 0 0; }
.problem { color: var(--warn); font-size: 15px; margin: 6px 0; }
#empty { color: var(--quiet); margin-top: 14vh; text-align: center; }
#empty strong { color: var(--ink); font-weight: 600; display: block; font-size: 21px; margin-bottom: 6px; }
#ideas { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 18px; }
#ideas button { padding: 7px 12px; border-radius: 999px; border: 1px solid var(--rule); background: var(--panel); font-size: 14px; }
#ideas button:hover { border-color: var(--signal); }

footer { border-top: 1px solid var(--rule); background: var(--panel); padding: 12px 22px; }
#bar { max-width: 68ch; margin: 0 auto; display: flex; gap: 8px; align-items: flex-end; }
#text { flex: 1; min-width: 0; padding: 10px 12px; border: 1px solid var(--rule); border-radius: 8px; background: var(--paper); resize: none; max-height: 160px; line-height: 1.4; }
.btn { padding: 10px 14px; border-radius: 8px; border: 1px solid var(--rule); background: var(--panel); white-space: nowrap; }
.btn:hover { border-color: var(--quiet); }
.btn.main { background: var(--signal); border-color: var(--signal); color: var(--paper); font-weight: 600; }
.btn.danger { color: var(--warn); border-color: var(--warn); }
#mic[aria-pressed="false"] { color: var(--warn); border-color: var(--warn); }
#hint { max-width: 68ch; margin: 6px auto 0; font-size: 13px; color: var(--quiet); }

/* ---- settings ---- */
dialog { border: 0; padding: 0; margin: 0 0 0 auto; height: 100%; max-height: 100%; width: min(460px, 100%); background: var(--panel); color: var(--ink);
         box-shadow: -18px 0 40px rgba(10, 20, 35, .18); }
dialog::backdrop { background: rgba(10, 16, 24, .35); }
.sheet { padding: 20px 22px 28px; overflow-y: auto; height: 100%; }
.sheet h2 { font-size: 18px; margin: 0; font-weight: 600; }
.sheet h3 { font-size: 15px; margin: 28px 0 4px; font-weight: 600; padding-top: 18px; border-top: 1px solid var(--rule); }
.sheet h3.first { border-top: 0; padding-top: 0; margin-top: 18px; }
.sheet p { margin: 4px 0 10px; color: var(--quiet); font-size: 14px; }
.top { display: flex; align-items: center; justify-content: space-between; }
label { display: block; font-size: 14px; margin: 12px 0 4px; }
label.check { display: flex; gap: 8px; align-items: center; font-size: 15px; }
.field { width: 100%; padding: 9px 10px; border: 1px solid var(--rule); border-radius: 8px; background: var(--paper); }
.row { display: flex; gap: 8px; align-items: center; }
.row .field { flex: 1; min-width: 0; }
.saved { font-size: 14px; color: var(--hear); }
#using { padding: 10px 12px; border-left: 3px solid var(--signal); background: color-mix(in srgb, var(--signal) 8%, transparent); border-radius: 0 8px 8px 0; font-size: 15px; }
#note { color: var(--warn); font-size: 14px; min-height: 1.4em; margin-top: 10px; }
input[type="range"] { width: 100%; accent-color: var(--signal); }

@media (max-width: 760px) {
  body { grid-template-columns: 1fr; }
  #rail { position: fixed; inset: 0 auto 0 0; width: min(300px, 86vw); z-index: 5; transform: translateX(-102%); transition: transform .18s; box-shadow: 18px 0 40px rgba(10, 20, 35, .18); }
  body.rail #rail { transform: none; }
  #menu { display: inline-block; }
  header, main, footer { padding-left: 16px; padding-right: 16px; }
  #stop, #export { display: none; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
</head>
<body>
<nav id="rail" aria-label="Conversations">
  <div class="head">
    <button id="new">New conversation</button>
    <input id="find" type="search" placeholder="Search conversations" aria-label="Search conversations">
  </div>
  <div id="list"></div>
  <div class="foot">
    <span id="keeps"></span>
    <button id="open">Settings</button>
  </div>
</nav>

<div id="stage">
  <header>
    <button class="plain" id="menu" aria-label="Show conversations">Conversations</button>
    <button id="title" title="Rename this conversation">New conversation</button>
    <span id="state" role="status" aria-live="polite">Starting</span>
    <span class="spacer"></span>
    <span id="where"></span>
    <button class="plain" id="export" hidden>Export</button>
    <button class="plain danger" id="delete" hidden>Delete</button>
  </header>
  <canvas id="line" aria-hidden="true"></canvas>
  <main><div id="talk"></div></main>
  <footer>
    <form id="bar">
      <textarea id="text" rows="1" placeholder="Type instead of speaking" aria-label="Type instead of speaking"></textarea>
      <button class="btn main" type="submit">Send</button>
      <button class="btn" type="button" id="stop">Stop talking</button>
      <button class="btn" type="button" id="mic" aria-pressed="true">Microphone on</button>
    </form>
    <div id="hint">Enter sends, Shift+Enter adds a line, Esc stops the voice.</div>
  </footer>
</div>

<dialog id="settings" aria-labelledby="st">
  <div class="sheet">
    <div class="top"><h2 id="st">Settings</h2><button class="plain" id="close">Close</button></div>

    <h3 class="first">Where answers come from</h3>
    <div id="using"></div>
    <p>Your voice is always turned into text on this computer. With Claude or OpenAI, that text is sent to the company to get an answer. With the local model nothing leaves this computer.</p>
    <label for="brain">Use</label>
    <select class="field" id="brain" data-setting>
      <option value="auto">Automatic: a cloud key if I have one, otherwise the local model</option>
      <option value="claude">Claude</option>
      <option value="openai">OpenAI</option>
      <option value="local">Local model only</option>
    </select>
    <label for="k-anthropic">Claude API key, from platform.claude.com <span class="saved" id="s-anthropic"></span></label>
    <div class="row"><input class="field" id="k-anthropic" type="password" autocomplete="off" placeholder="Paste your key">
      <button class="btn" data-save="anthropic">Save key</button><button class="btn" data-remove="anthropic">Remove</button></div>
    <label for="claude_model">Claude model</label>
    <input class="field" id="claude_model" data-setting>
    <label for="k-openai">OpenAI API key, from platform.openai.com <span class="saved" id="s-openai"></span></label>
    <div class="row"><input class="field" id="k-openai" type="password" autocomplete="off" placeholder="Paste your key">
      <button class="btn" data-save="openai">Save key</button><button class="btn" data-remove="openai">Remove</button></div>
    <label for="openai_model">OpenAI model</label>
    <input class="field" id="openai_model" data-setting placeholder="The model name your account offers">

    <h3>Voice</h3>
    <label class="check"><input type="checkbox" id="speak_answers" data-setting> Speak answers aloud</label>
    <label for="voice">Voice</label>
    <div class="row"><select class="field" id="voice" data-setting></select><button class="btn" id="hear">Hear it</button></div>
    <label for="speed">Speed <span id="speed-n"></span></label>
    <input type="range" id="speed" data-setting min="0.7" max="1.5" step="0.05">
    <p>A new speed applies the next time Jarvis starts.</p>

    <h3>You and Jarvis</h3>
    <label for="name-field">Name it answers to</label>
    <input class="field" id="name-field" data-setting="name">
    <label for="call_me">What it calls you</label>
    <input class="field" id="call_me" data-setting placeholder="Leave empty for nothing">
    <label for="persona">Its character, in a sentence</label>
    <input class="field" id="persona" data-setting placeholder="For example: cheerful and brief">

    <h3>History</h3>
    <p>Conversations are kept in a file on this computer that only you can read. They are never uploaded.</p>
    <label for="retention_days">Keep conversations</label>
    <select class="field" id="retention_days" data-setting>
      <option value="-1">Don't save them</option>
      <option value="1">For 1 day</option>
      <option value="7">For 7 days</option>
      <option value="30">For 30 days</option>
      <option value="90">For 90 days</option>
      <option value="365">For 1 year</option>
      <option value="0">Until I delete them</option>
    </select>
    <div class="row" style="margin-top:14px"><button class="btn danger" id="wipe">Delete all conversations</button></div>
    <div id="note" role="alert"></div>
  </div>
</dialog>

<script>
const $ = (id) => document.getElementById(id);
const WORDS = { starting: "Starting", listening: "Listening", hearing: "Hearing you", thinking: "Thinking", speaking: "Speaking", paused: "Microphone off" };
const IDEAS = ["Tell me something interesting", "Help me think through a decision", "Explain how tides work", "What can you do?"];
let status = "starting", last = 0, conv = { id: "", title: "", saved: false }, live = null, lastDay = "", S = null;

async function get(path) { const r = await fetch(path); if (!r.ok) throw new Error("That did not work."); return r.json(); }
async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-Jarvis": "1" }, body: JSON.stringify(body || {}) });
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || "That did not work.");
  return d;
}
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
function dayName(t) {
  const d = new Date(t * 1000), now = new Date(), mid = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((mid(now) - mid(d)) / 864e5);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return "Earlier this week";
  if (days < 31) return "Earlier this month";
  return d.toLocaleDateString([], { month: "long", year: "numeric" });
}

/* ---- status ---- */
function setStatus(s) {
  status = s;
  $("state").textContent = WORDS[s] || s;
  $("state").dataset.s = s;
  const on = s !== "paused";
  $("mic").setAttribute("aria-pressed", on);
  $("mic").textContent = on ? "Microphone on" : "Microphone off";
}

/* ---- the conversation on screen ---- */
function bottom() { document.querySelector("main").scrollTop = 1e9; }
function emptyState() {
  const box = el("div"); box.id = "empty";
  box.append(el("strong", "", "Say something."), document.createTextNode(status === "paused" ? "The microphone is off. Type below, or turn it on." : "The microphone is on. You can also type below."));
  const ideas = el("div"); ideas.id = "ideas";
  for (const i of IDEAS) { const b = el("button", "", i); b.onclick = () => send(i); ideas.append(b); }
  box.append(ideas);
  $("talk").append(box);
}
function line(m) {
  const e = $("empty"); if (e) e.remove();
  const day = dayName(m.t);
  if (day !== lastDay && (lastDay || day !== "Today")) $("talk").append(el("p", "day", day));
  lastDay = day;
  if (m.role === "user") { $("talk").append(el("p", "you", m.text)); return; }
  const turn = el("div", "turn"), tools = el("div", "tools");
  const copy = el("button", "plain", "Copy"), again = el("button", "plain", "Say again");
  copy.onclick = async () => { try { await navigator.clipboard.writeText(m.text); copy.textContent = "Copied"; } catch (e) { copy.textContent = "Could not copy"; } setTimeout(() => copy.textContent = "Copy", 1500); };
  again.onclick = () => act(() => post("/again", { text: m.text }));
  tools.append(copy, again, el("span", "when", clock(m.t) + (m.brain ? ", " + ({ claude: "Claude", openai: "OpenAI", local: "local model" }[m.brain] || m.brain) : "")));
  turn.append(el("p", "jarvis", m.text), tools);
  $("talk").append(turn);
}
async function load() {
  const c = await get("/conversation");
  conv = { id: c.id, title: c.title, saved: c.saved };
  $("talk").textContent = ""; live = null; lastDay = "";
  for (const m of c.messages) line(m);
  if (!c.messages.length) emptyState();
  header(); bottom(); mark();
}
function header() {
  $("title").textContent = conv.title || "New conversation";
  $("export").hidden = $("delete").hidden = !conv.saved;
  document.title = (conv.title ? conv.title + " - " : "") + ($("name-field").value || "Jarvis").replace(/^./, (c) => c.toUpperCase());
}

/* ---- the list ---- */
function mark() { for (const b of document.querySelectorAll(".item")) b.setAttribute("aria-current", b.dataset.id === conv.id); }
async function list() {
  const rows = await get("/conversations?q=" + encodeURIComponent($("find").value));
  const box = $("list"); box.textContent = "";
  if (!rows.length) { const n = el("div", "", $("find").value ? "Nothing matches." : "Conversations you have will appear here."); n.id = "none"; box.append(n); return; }
  let group = "";
  for (const r of rows) {
    const g = dayName(r.updated);
    if (g !== group) { box.append(el("h2", "", g)); group = g; }
    const b = el("button", "item"); b.dataset.id = r.id;
    b.append(el("span", "t", r.title), el("span", "d", clock(r.updated) + ", " + Math.ceil(r.n / 2) + (Math.ceil(r.n / 2) === 1 ? " exchange" : " exchanges")));
    b.onclick = () => { document.body.classList.remove("rail"); act(() => post("/open", { id: r.id })); };
    box.append(b);
  }
  mark();
}

/* ---- live events ---- */
function show(ev) {
  if (ev.type === "status") setStatus(ev.status);
  else if (ev.type === "opened") load();
  else if (ev.type === "history") { list(); get("/state").then((s) => { conv.saved = s.conversation.saved; conv.id = s.conversation.id; conv.title = s.conversation.title; header(); mark(); }); }
  else if (ev.type === "problem") { $("talk").append(el("p", "problem", ev.text)); bottom(); }
  else if (ev.type === "writing") {
    if (!live) { const e = $("empty"); if (e) e.remove(); live = el("p", "jarvis live", ""); $("talk").append(live); }
    live.textContent = ev.text; bottom();
  }
  else if (ev.type === "written") { if (live) { live.remove(); live = null; } }
  else if (ev.type === "message") {
    if (live && ev.role === "assistant") { live.remove(); live = null; }
    line({ role: ev.role, text: ev.text, t: ev.t, brain: ev.brain }); bottom();
    if (ev.conv && ev.conv !== conv.id) { conv.id = ev.conv; conv.saved = true; }
    if (ev.role === "assistant") list();
  }
}
async function follow() {
  for (;;) {
    try {
      const r = await fetch("/events?last=" + last);
      if (!r.ok) throw new Error();
      for (const ev of await r.json()) { last = Math.max(last, ev.id); show(ev); }
    } catch (e) {
      $("state").textContent = "Jarvis is not running"; $("state").dataset.s = "";
      await new Promise((ok) => setTimeout(ok, 2000));
    }
  }
}

/* ---- settings ---- */
function fill(st) {
  S = st;
  setStatus(st.paused ? "paused" : st.status);
  const s = st.settings;
  $("using").textContent = st.brain ? "In use now: " + st.brain_text + "." : "Nothing can answer yet. Add a key below, or set up the local model.";
  $("where").textContent = st.brain ? (st.cloud ? "Text goes to " + (st.brain === "claude" ? "Claude" : "OpenAI") : "Stays on this computer") : "No brain yet";
  $("where").dataset.cloud = st.cloud;
  for (const n of ["anthropic", "openai"]) $("s-" + n).textContent = st.keys[n] ? "saved" : "";
  const v = $("voice");
  if (!v.options.length) for (const o of st.voices) v.add(new Option(o.label, o.id));
  for (const f of document.querySelectorAll("[data-setting]")) {
    const k = f.dataset.setting || f.id;
    if (document.activeElement === f) continue;
    if (f.type === "checkbox") f.checked = !!s[k]; else f.value = s[k] ?? "";
  }
  $("speed-n").textContent = "(" + Number(s.speed).toFixed(2) + ")";
  const d = s.retention_days;
  $("keeps").textContent = d < 0 ? "Conversations are not saved." : d === 0 ? "Conversations are kept on this computer until you delete them."
    : "Conversations are kept on this computer for " + (d === 1 ? "1 day." : d + " days.");
  conv.saved = st.conversation.saved; conv.id = st.conversation.id; conv.title = st.conversation.title || conv.title;
  header();
}
async function act(fn) {
  $("note").textContent = "";
  try { fill(await fn()); } catch (e) { $("note").textContent = e.message; if (!$("settings").open) { $("talk").append(el("p", "problem", e.message)); bottom(); } }
}
function send(t) { t = t.trim(); if (t) act(() => post("/say", { text: t })); }

/* ---- wiring ---- */
const text = $("text");
$("bar").addEventListener("submit", (e) => { e.preventDefault(); send(text.value); text.value = ""; text.style.height = ""; });
text.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("bar").requestSubmit(); } });
text.addEventListener("input", () => { text.style.height = ""; text.style.height = Math.min(text.scrollHeight + 2, 160) + "px"; });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("settings").open) { document.body.classList.remove("rail"); act(() => post("/stop")); }
  if (e.key === "/" && document.activeElement === document.body) { e.preventDefault(); text.focus(); }
});
$("stop").onclick = () => act(() => post("/stop"));
$("new").onclick = () => { document.body.classList.remove("rail"); act(() => post("/new")); text.focus(); };
$("mic").onclick = () => act(() => post("/mic", { on: status === "paused" }));
$("menu").onclick = () => document.body.classList.toggle("rail");
$("stage").addEventListener("click", (e) => { if (e.target.id !== "menu") document.body.classList.remove("rail"); });
$("open").onclick = () => { $("settings").showModal(); document.querySelector(".sheet").scrollTop = 0; act(() => get("/state")); };
$("close").onclick = () => $("settings").close();
let timer; $("find").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(list, 200); });
$("export").onclick = () => { const a = el("a"); a.href = "/export?id=" + encodeURIComponent(conv.id); a.download = "jarvis-conversation.md"; document.body.append(a); a.click(); a.remove(); };

function twoStep(btn, label, sure, run) {                    /* a destructive button asks once more, in place */
  let armed = 0;
  btn.onclick = () => {
    if (Date.now() < armed) { armed = 0; btn.textContent = label; run(); return; }
    armed = Date.now() + 4000; btn.textContent = sure;
    setTimeout(() => { if (armed && Date.now() >= armed) { armed = 0; btn.textContent = label; } }, 4100);
  };
}
twoStep($("delete"), "Delete", "Really delete?", () => act(() => post("/delete", { id: conv.id })));
twoStep($("wipe"), "Delete all conversations", "Really delete everything?", () => act(() => post("/delete_all")));

$("title").onclick = () => {
  if (!conv.saved) return;
  const i = el("input"); i.id = "title-edit"; i.value = conv.title; i.setAttribute("aria-label", "Conversation name");
  $("title").replaceWith(i); i.focus(); i.select();
  let done = false;
  const finish = (save) => {
    if (done) return; done = true;
    const t = i.value.trim();
    i.replaceWith(titleBtn);
    if (save && t && t !== conv.title) { conv.title = t; header(); act(() => post("/rename", { id: conv.id, title: t })); }
  };
  i.onblur = () => finish(true);
  i.onkeydown = (e) => { if (e.key === "Enter") finish(true); if (e.key === "Escape") { e.stopPropagation(); finish(false); } };
};
const titleBtn = $("title");

for (const f of document.querySelectorAll("[data-setting]"))
  f.onchange = () => { const k = f.dataset.setting || f.id; act(() => post("/settings", { [k]: f.type === "checkbox" ? f.checked : f.type === "range" || k === "retention_days" ? Number(f.value) : f.value })); };
$("speed").oninput = () => $("speed-n").textContent = "(" + Number($("speed").value).toFixed(2) + ")";
$("hear").onclick = () => act(() => post("/preview", { voice: $("voice").value }));
for (const b of document.querySelectorAll("[data-save]"))
  b.onclick = () => { const i = $("k-" + b.dataset.save); act(async () => { const d = await post("/key", { name: b.dataset.save, value: i.value }); i.value = ""; return d; }); };
for (const b of document.querySelectorAll("[data-remove]"))
  b.onclick = () => act(() => post("/key", { name: b.dataset.remove, value: "" }));

/* The voice line: flat while listening, small quick ripples while hearing you, one slow travelling wave while thinking,
   full waves while speaking, a dashed flat line when the microphone is off. */
const cv = $("line"), cx = cv.getContext("2d");
const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
let amp = 0, t0 = performance.now();
function draw(now) {
  const w = cv.clientWidth, h = cv.clientHeight, dpr = devicePixelRatio || 1;
  if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
  cx.setTransform(dpr, 0, 0, dpr, 0, 0);
  cx.clearRect(0, 0, w, h);
  const css = getComputedStyle(document.documentElement);
  const colour = { hearing: "--hear", thinking: "--think", speaking: "--signal" }[status] || "--rule";
  const want = { hearing: 7, thinking: 10, speaking: 18 }[status] || 0;
  amp += (want - amp) * 0.08;
  const t = still ? 0 : (now - t0) / 1000;
  cx.beginPath();
  cx.lineWidth = 2; cx.lineCap = "round";
  cx.strokeStyle = css.getPropertyValue(colour);
  cx.setLineDash(status === "paused" ? [2, 8] : []);
  for (let x = 0; x <= w; x += 3) {
    const u = x / w, edge = Math.sin(Math.PI * u);
    let y = 0;
    if (status === "thinking") y = Math.exp(-Math.pow((u - ((t * 0.35) % 1.3) + 0.15) * 7, 2)) * Math.sin(u * 40 - t * 6);
    else if (status === "hearing") y = Math.sin(u * 70 + t * 14) * 0.6 + Math.sin(u * 23 - t * 9) * 0.4;
    else y = Math.sin(u * 18 - t * 5) * 0.55 + Math.sin(u * 41 + t * 7.3) * 0.3 + Math.sin(u * 7 - t * 2.1) * 0.15;
    const py = h / 2 + y * amp * edge;
    x ? cx.lineTo(x, py) : cx.moveTo(x, py);
  }
  cx.stroke();
  requestAnimationFrame(draw);
}
requestAnimationFrame(draw);

history.replaceState(null, "", "/");          /* take the secret out of the address bar */
(async () => {
  const st = await get("/state");
  last = st.last_event;                       /* what happened before is loaded from the conversation, not replayed */
  fill(st); await load(); await list(); follow();
})();
</script>
</body>
</html>
"""
