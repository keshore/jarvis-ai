"""The window, as one self-contained page: no files, fonts or scripts are loaded from anywhere else, so it works offline.
The one expressive element is the voice line under the title; everything else stays quiet. Text from the conversation is
always inserted as text, never as markup."""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jarvis</title>
<style>
:root {
  --paper: #f2f4f7; --panel: #ffffff; --ink: #17212b; --quiet: #5d6b79; --rule: #d6dce3;
  --signal: #3a4fd8; --hear: #0c8f8f; --think: #b5770f; --warn: #b3261e;
  --ui: "Avenir Next", "Segoe UI Variable Text", "Segoe UI", "Helvetica Neue", system-ui, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root { --paper: #141a22; --panel: #1b232d; --ink: #e6ebf1; --quiet: #93a1b0; --rule: #2c3743;
          --signal: #9aa8ff; --hear: #4fd0cc; --think: #e6b455; --warn: #ff8a80; }
}
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body { background: var(--paper); color: var(--ink); font: 16px/1.5 var(--ui); display: flex; flex-direction: column; }
button, input, select, textarea { font: inherit; color: inherit; }
:focus-visible { outline: 2px solid var(--signal); outline-offset: 2px; }

header { display: flex; align-items: baseline; gap: 14px; padding: 18px 22px 6px; }
h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.01em; margin: 0; }
#state { color: var(--quiet); font-size: 15px; }
#state[data-s="hearing"] { color: var(--hear); }
#state[data-s="thinking"] { color: var(--think); }
#state[data-s="speaking"] { color: var(--signal); }
header .spacer { flex: 1; }
.plain { background: none; border: 0; padding: 6px 8px; border-radius: 6px; color: var(--quiet); cursor: pointer; }
.plain:hover { color: var(--ink); background: color-mix(in srgb, var(--ink) 7%, transparent); }

#line { display: block; width: 100%; height: 72px; }

main { flex: 1; overflow-y: auto; padding: 8px 22px 20px; }
#talk { max-width: 68ch; margin: 0 auto; }
.you { color: var(--quiet); font-size: 15px; margin: 22px 0 4px; padding-left: 12px; border-left: 2px solid var(--rule); }
.jarvis { font-size: 19px; line-height: 1.45; margin: 0 0 6px; white-space: pre-wrap; }
.jarvis.cut::after { content: " (interrupted)"; color: var(--quiet); font-size: 14px; }
.problem { color: var(--warn); font-size: 15px; margin: 6px 0; }
#empty { color: var(--quiet); margin-top: 12vh; text-align: center; }
#empty strong { color: var(--ink); font-weight: 600; display: block; font-size: 19px; margin-bottom: 6px; }

footer { border-top: 1px solid var(--rule); background: var(--panel); padding: 12px 22px; }
#bar { max-width: 68ch; margin: 0 auto; display: flex; gap: 8px; }
#text { flex: 1; min-width: 0; padding: 10px 12px; border: 1px solid var(--rule); border-radius: 8px; background: var(--paper); }
.btn { padding: 10px 14px; border-radius: 8px; border: 1px solid var(--rule); background: var(--panel); cursor: pointer; white-space: nowrap; }
.btn:hover { border-color: var(--quiet); }
.btn.main { background: var(--signal); border-color: var(--signal); color: var(--paper); font-weight: 600; }
#mic[aria-pressed="false"] { color: var(--warn); border-color: var(--warn); }

dialog { border: 0; padding: 0; margin: 0 0 0 auto; height: 100%; max-height: 100%; width: min(440px, 100%); background: var(--panel); color: var(--ink);
         box-shadow: -18px 0 40px rgba(10, 20, 35, .18); }
dialog::backdrop { background: rgba(10, 16, 24, .35); }
.sheet { padding: 20px 22px 28px; overflow-y: auto; height: 100%; }
.sheet h2 { font-size: 18px; margin: 0; font-weight: 600; }
.sheet h3 { font-size: 15px; margin: 26px 0 4px; font-weight: 600; }
.sheet p { margin: 4px 0 10px; color: var(--quiet); font-size: 14px; }
.top { display: flex; align-items: center; justify-content: space-between; }
label { display: block; font-size: 14px; margin: 12px 0 4px; }
.field { width: 100%; padding: 9px 10px; border: 1px solid var(--rule); border-radius: 8px; background: var(--paper); }
.row { display: flex; gap: 8px; align-items: center; }
.row .field { flex: 1; min-width: 0; }
.saved { font-size: 14px; color: var(--hear); }
#using { padding: 10px 12px; border-left: 3px solid var(--signal); background: color-mix(in srgb, var(--signal) 8%, transparent); border-radius: 0 8px 8px 0; font-size: 15px; }
#note { color: var(--warn); font-size: 14px; min-height: 1.4em; margin-top: 10px; }
@media (max-width: 520px) { header, main, footer { padding-left: 16px; padding-right: 16px; } #stop { display: none; } }
</style>
</head>
<body>
<header>
  <h1 id="name">Jarvis</h1>
  <span id="state" role="status" aria-live="polite">Starting</span>
  <span class="spacer"></span>
  <button class="plain" id="clear">New conversation</button>
  <button class="plain" id="open">Settings</button>
</header>
<canvas id="line" aria-hidden="true"></canvas>
<main><div id="talk"><div id="empty"><strong>Say something.</strong>The microphone is on. You can also type below.</div></div></main>
<footer>
  <form id="bar">
    <input id="text" autocomplete="off" placeholder="Type instead of speaking" aria-label="Type instead of speaking">
    <button class="btn main" type="submit">Send</button>
    <button class="btn" type="button" id="stop">Stop talking</button>
    <button class="btn" type="button" id="mic" aria-pressed="true">Microphone on</button>
  </form>
</footer>

<dialog id="settings" aria-labelledby="st">
  <div class="sheet">
    <div class="top"><h2 id="st">Settings</h2><button class="plain" id="close">Close</button></div>

    <h3>Where answers come from</h3>
    <div id="using"></div>
    <p>With Claude or OpenAI, what you say is sent to that company to get an answer. With the local model nothing leaves this computer.</p>
    <label for="brain">Use</label>
    <select class="field" id="brain">
      <option value="auto">Automatic: a cloud key if I have one, otherwise the local model</option>
      <option value="claude">Claude</option>
      <option value="openai">OpenAI</option>
      <option value="local">Local model only</option>
    </select>

    <h3>Claude</h3>
    <label for="k-anthropic">API key <span class="saved" id="s-anthropic"></span></label>
    <div class="row"><input class="field" id="k-anthropic" type="password" autocomplete="off" placeholder="Paste a key from platform.claude.com">
      <button class="btn" data-save="anthropic">Save key</button><button class="btn" data-remove="anthropic">Remove</button></div>
    <label for="claude_model">Model</label>
    <input class="field" id="claude_model" data-setting>

    <h3>OpenAI</h3>
    <label for="k-openai">API key <span class="saved" id="s-openai"></span></label>
    <div class="row"><input class="field" id="k-openai" type="password" autocomplete="off" placeholder="Paste a key from platform.openai.com">
      <button class="btn" data-save="openai">Save key</button><button class="btn" data-remove="openai">Remove</button></div>
    <label for="openai_model">Model</label>
    <input class="field" id="openai_model" data-setting placeholder="The model name your account offers">

    <h3>Voice and name</h3>
    <label for="voice">Voice</label>
    <select class="field" id="voice" data-setting></select>
    <label for="name-field">Name it answers to</label>
    <input class="field" id="name-field" data-setting="name">
    <label for="call_me">What it calls you</label>
    <input class="field" id="call_me" data-setting placeholder="Leave empty for nothing">
    <div id="note" role="alert"></div>
  </div>
</dialog>

<script>
const $ = (id) => document.getElementById(id);
const WORDS = { starting: "Starting", listening: "Listening", hearing: "Hearing you", thinking: "Thinking", speaking: "Speaking", paused: "Microphone off" };
let status = "starting", last = 0, lines = {};

async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-Jarvis": "1" }, body: JSON.stringify(body || {}) });
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || "That did not work.");
  return d;
}

function setStatus(s) {
  status = s;
  $("state").textContent = WORDS[s] || s;
  $("state").dataset.s = s;
  const on = s !== "paused";
  $("mic").setAttribute("aria-pressed", on);
  $("mic").textContent = on ? "Microphone on" : "Microphone off";
}

function add(cls, text) {
  const e = $("empty"); if (e) e.remove();
  const p = document.createElement("p");
  p.className = cls; p.textContent = text;
  $("talk").appendChild(p);
  document.querySelector("main").scrollTop = 1e9;
  return p;
}

function show(ev) {
  if (ev.type === "status") setStatus(ev.status);
  else if (ev.type === "you") add("you", ev.text);
  else if (ev.type === "error") add("problem", ev.text);
  else if (ev.type === "cleared") { $("talk").textContent = ""; lines = {}; add("you", "New conversation."); }
  else if (ev.type === "jarvis") {
    if (!ev.text && ev.done) return;
    const p = lines[ev.turn] || (lines[ev.turn] = add("jarvis", ""));
    p.textContent = ev.text;
    if (ev.done && ev.cut) p.classList.add("cut");
    document.querySelector("main").scrollTop = 1e9;
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

function fill(st) {
  setStatus(st.paused ? "paused" : st.status);
  $("name").textContent = (st.settings.name || "Jarvis").replace(/^./, (c) => c.toUpperCase());
  document.title = $("name").textContent;
  $("using").textContent = st.brain ? "In use now: " + st.brain_text + "." : "Nothing can answer yet. Add a key below, or set up the local model.";
  for (const n of ["anthropic", "openai"]) $("s-" + n).textContent = st.keys[n] ? "saved" : "";
  $("brain").value = st.settings.brain;
  const v = $("voice");
  if (!v.options.length) for (const name of st.voices) v.add(new Option(name, name));
  for (const el of document.querySelectorAll("[data-setting]")) {
    const k = el.dataset.setting || el.id;
    if (document.activeElement !== el) el.value = st.settings[k] ?? "";
  }
}

async function act(fn) {
  $("note").textContent = "";
  try { fill(await fn()); } catch (e) { $("note").textContent = e.message; }
}

$("bar").addEventListener("submit", (e) => {
  e.preventDefault();
  const t = $("text").value.trim();
  if (t) { $("text").value = ""; act(() => post("/say", { text: t })); }
});
$("stop").onclick = () => act(() => post("/stop"));
$("clear").onclick = () => act(() => post("/clear"));
$("mic").onclick = () => act(() => post("/mic", { on: status === "paused" }));
$("open").onclick = () => { $("settings").showModal(); act(() => fetch("/state").then((r) => r.json())); };
$("close").onclick = () => $("settings").close();
$("brain").onchange = () => act(() => post("/settings", { brain: $("brain").value }));
for (const el of document.querySelectorAll("[data-setting]"))
  el.onchange = () => act(() => post("/settings", { [el.dataset.setting || el.id]: el.value }));
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
  if (cv.width !== w * dpr) { cv.width = w * dpr; cv.height = h * dpr; }
  cx.setTransform(dpr, 0, 0, dpr, 0, 0);
  cx.clearRect(0, 0, w, h);
  const css = getComputedStyle(document.documentElement);
  const colour = { hearing: "--hear", thinking: "--think", speaking: "--signal" }[status] || "--rule";
  const want = { hearing: 7, thinking: 10, speaking: 20 }[status] || 0;
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
fetch("/state").then((r) => r.json()).then(fill);
follow();
</script>
</body>
</html>
"""
