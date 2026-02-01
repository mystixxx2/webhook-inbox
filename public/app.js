const $ = (sel) => document.querySelector(sel);

const endpoint = `${location.origin}/api/webhook`;
$("#endpointUrl").textContent = endpoint;
$("#endpointUrlInline").textContent = endpoint;

let paused = false;
let lastBytes = 0;
let toastTimer = null;

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 1200);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied ✨");
  } catch {
    toast("Copy blocked by browser");
  }
}

document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-copy]");
  if (!btn) return;
  const target = btn.getAttribute("data-copy");
  const el = document.querySelector(target);
  if (!el) return;
  await copyText(el.textContent.trim());
});

$("#btnPause").addEventListener("click", () => {
  paused = !paused;
  $("#btnPause").textContent = paused ? "Resume" : "Pause";
  $("#livePill").textContent = paused ? "PAUSED" : "LIVE";
  $("#livePill").classList.toggle("pill-paused", paused);
  toast(paused ? "Paused" : "Live");
});

$("#btnClearView").addEventListener("click", () => {
  $("#feed").innerHTML = "";
  $("#empty").style.display = "block";
  $("#statCount").textContent = "0";
  $("#statBytes").textContent = "—";
  toast("Cleared view");
});

$("#btnCopyCurl").addEventListener("click", async () => {
  const curl = `curl -X POST "${endpoint}" -H "Content-Type: application/json" -d '{ "hello": "world" }'`;
  await copyText(curl);
});

$("#btnPretty").addEventListener("click", () => {
  const ta = $("#testJson");
  try {
    const parsed = JSON.parse(ta.value);
    ta.value = JSON.stringify(parsed, null, 2);
    toast("Prettified");
  } catch {
    toast("Not valid JSON");
  }
});

async function sendPayload(payloadObj) {
  const res = await fetch("/api/webhook", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payloadObj),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || "Request failed");
  return data;
}

$("#btnSendSample").addEventListener("click", async () => {
  try {
    const data = await sendPayload({ sample: true, time: new Date().toISOString(), vibe: "purple" });
    toast(`Sent (${data.id || "ok"})`);
  } catch (err) {
    toast(err.message);
  }
});

$("#btnSendCustom").addEventListener("click", async () => {
  const out = $("#testResult");
  out.textContent = "";
  try {
    const text = $("#testJson").value;
    const parsed = JSON.parse(text);
    const data = await sendPayload(parsed);
    out.textContent = `Sent ✅ id=${data.id || "ok"}`;
    toast("Sent");
  } catch (err) {
    out.textContent = `Error: ${err.message}`;
    toast("Failed");
  }
});

function matchesSearch(ev, q) {
  if (!q) return true;
  const s = (q || "").toLowerCase();
  const blob = JSON.stringify(ev).toLowerCase();
  return blob.includes(s);
}

function render(events) {
  const q = $("#search").value.trim();
  const filtered = events.filter(ev => matchesSearch(ev, q));

  $("#statCount").textContent = String(filtered.length);
  $("#statBytes").textContent = String(lastBytes || "—");
  $("#empty").style.display = filtered.length ? "none" : "block";

  const feed = $("#feed");
  feed.innerHTML = "";

  for (const ev of filtered) {
    const card = document.createElement("article");
    card.className = "hook";

    const top = document.createElement("div");
    top.className = "hook-top";

    const left = document.createElement("div");
    const when = new Date(ev.received_at).toLocaleString();
    left.innerHTML = `
      <div class="badges">
        <span class="badge">${when}</span>
        <span class="badge badge-ct">${(ev.content_type || "unknown").slice(0, 48)}</span>
        <span class="badge">ip: ${(ev.ip || "unknown").slice(0, 42)}</span>
        ${ev.truncated ? `<span class="badge badge-warn">TRUNCATED</span>` : ""}
      </div>
    `;

    const actions = document.createElement("div");
    actions.className = "hook-actions";

    const b1 = document.createElement("button");
    b1.className = "btn btn-ghost";
    b1.textContent = "Copy JSON";

    const b2 = document.createElement("button");
    b2.className = "btn btn-ghost";
    b2.textContent = "Copy cURL";

    b1.addEventListener("click", () => copyText(ev.body_pretty || ""));
    b2.addEventListener("click", () => {
      const curl = `curl -X POST "${endpoint}" -H "Content-Type: application/json" -d '${(ev.body_pretty || "").replaceAll("'", "\\'")}'`;
      copyText(curl);
    });

    actions.append(b1, b2);
    top.append(left, actions);

    const pre = document.createElement("pre");
    pre.className = "code";
    const code = document.createElement("code");
    code.textContent = ev.body_pretty || "";
    pre.appendChild(code);

    card.append(top, pre);
    feed.appendChild(card);
  }
}

async function refresh() {
  if (paused) return;
  try {
    const info = await fetch("/api/info", { cache: "no-store" }).then(r => r.json());
    $("#storageMini").textContent = `storage: ${info.storage}${info.token_required ? " · token" : ""}`;

    const res = await fetch("/api/events?limit=50", { cache: "no-store" });
    const data = await res.json();
    const events = data.events || [];

    lastBytes = events?.[0]?.bytes || 0;
    $("#statUpdated").textContent = new Date().toLocaleTimeString();

    render(events);
  } catch (e) {
    // Keep quiet; dashboard should stay pretty even if a request fails
  }
}

setInterval(refresh, 1400);
refresh();
