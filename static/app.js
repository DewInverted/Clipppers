const $ = s => document.querySelector(s);
let STATE = { moments: [], meta: {}, upload_id: "", url: "" };

const fmt = s => { s = Math.max(0, Math.round(s)); return `${String(Math.floor(s/60)).padStart(2,"0")}:${String(s%60).padStart(2,"0")}`; };
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const scoreClass = s => s >= 85 ? "hot" : s >= 65 ? "good" : "ok";
function toast(msg){ const t=$("#toast"); t.textContent=msg; t.classList.remove("hidden"); setTimeout(()=>t.classList.add("hidden"), 3200); }

function setProgress(n){
  document.querySelectorAll(".step").forEach(el=>{
    const k=+el.dataset.step;
    el.className = "step" + (k<n ? " done" : k===n ? " on" : "");
  });
}

async function runProgress(promise){
  $("#progress").classList.remove("hidden"); setProgress(1);
  const timers=[setTimeout(()=>setProgress(2),700), setTimeout(()=>setProgress(3),1800), setTimeout(()=>setProgress(4),3200)];
  try { return await promise; } finally { timers.forEach(clearTimeout); setProgress(5); }
}

async function postJSON(path, body){
  const r = await fetch(path, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  const data = await r.json().catch(()=>({error:"Bad response from server"}));
  if(!r.ok || data.error) throw new Error(data.error || "Request failed");
  return data;
}

async function analyze(){
  const btn=$("#analyzeBtn"); btn.disabled=true; btn.textContent="⏳ Analyzing…";
  $("#error").classList.add("hidden");
  try{
    const data = await runProgress(postJSON("/api/analyze", {
      url: $("#url").value.trim(), transcript: $("#transcript").value,
      target_len: +$("#targetLen").value }));
    STATE = { moments: data.moments||[], meta: data.meta||{}, upload_id: data.upload_id||"", url: $("#url").value.trim() };
    render(data);
    if(data.warning) toast("⚠ " + data.warning);
  }catch(e){ showError(e.message); }
  finally{ btn.disabled=false; btn.textContent="⚡ Analyze video"; }
}

async function demo(){
  const data = await runProgress(fetch("/api/demo").then(r=>r.json()));
  STATE = { moments:data.moments||[], meta:data.meta||{}, upload_id:"", url:"" };
  render(data); toast("Demo loaded — this is a sample podcast transcript");
}

async function uploadFile(file){
  const fd = new FormData(); fd.append("file", file); fd.append("transcript", $("#transcript").value);
  toast("⬆ Uploading " + file.name + "…");
  const r = await fetch("/api/upload", {method:"POST", body:fd});
  const data = await r.json().catch(()=>({error:"Upload failed"}));
  if(data.error) return showError(data.error);
  STATE = { moments:data.moments||[], meta:data.meta||{}, upload_id:data.upload_id||"", url:"" };
  render(data); if(data.warning) toast("⚠ "+data.warning);
}

function showError(m){ const e=$("#error"); e.textContent="⚠ "+m; e.classList.remove("hidden"); }

function render(data){
  $("#results").classList.remove("hidden");
  const m = data.meta||{};
  $("#videoCard").innerHTML = `
    ${m.thumbnail?`<img src="${esc(m.thumbnail)}" alt="">`:""}
    <div><h3 style="margin:0 0 6px">${esc(m.title||"Untitled video")}</h3>
    <p class="muted" style="margin:0">${esc(m.uploader||"")} ${m.platform?"· "+esc(m.platform):""} ${m.duration?"· "+fmt(m.duration):""}
    ${m.view_count?"· "+Number(m.view_count).toLocaleString()+" views":""}<br>
    Source: <b>${esc(data.source||"transcript")}</b> · ${data.segment_count||STATE.moments.length} transcript segments analysed</p>
    ${m.url?`<p><a class="dl" href="${esc(m.url)}" target="_blank" rel="noopener">Open original ↗</a></p>`:""}</div>`;

  const h = data.opening_hook;
  $("#hookReport").innerHTML = h ? `<div class="hook-report">
    <div style="display:flex;gap:22px;flex-wrap:wrap;align-items:center">
      <div><div class="gauge" style="color:${h.score>=70?"var(--good)":h.score>=45?"var(--acc2)":"var(--acc)"}">${h.score}<small style="font-size:16px">/100</small></div>
      <div class="muted">Opening hook grade <b style="color:#fff">${h.grade}</b></div></div>
      <div style="flex:1;min-width:260px"><b>🎣 Your video's actual first seconds:</b>
      <div class="hookbox">“${esc(h.text)}…”</div>
      ${h.strengths.length?`<ul class="why">${h.strengths.map(s=>`<li>${esc(s)}</li>`).join("")}</ul>`:`<p class="muted">No recognised hook pattern — the opening below would fix that:</p>`}
      <b>✍️ Stronger opening hooks for this video:</b>
      <ol class="rewrites">${h.rewrites.map(r=>`<li>${esc(r)}</li>`).join("")}</ol></div>
    </div></div>` : "";

  // timeline
  const dur = Math.max(m.duration||0, ...STATE.moments.map(x=>x.end), 1);
  $("#timeline").innerHTML = STATE.moments.map((x,i)=>
    `<div class="tick ${scoreClass(x.score)}" title="#${x.rank} ${esc(x.title)} (${x.score})"
       style="left:${x.start/dur*100}%;width:${Math.max(1.2,(x.end-x.start)/dur*100)}%;background:${x.score>=85?"#ff4d6d":x.score>=65?"#ffb347":"#7a7aff"}"
       onclick="document.getElementById('moment-${i}').scrollIntoView({behavior:'smooth'})"><span>${x.score}</span></div>`).join("");

  const labels=[...new Set(STATE.moments.map(x=>x.label))];
  $("#filterLabel").innerHTML = `<option value="">All types</option>` + labels.map(l=>`<option>${esc(l)}</option>`).join("");
  $("#momentCount").textContent = `— ${STATE.moments.length} found`;
  renderMoments();
  $("#results").scrollIntoView({behavior:"smooth"});
}

function renderMoments(){
  let list=[...STATE.moments];
  const f=$("#filterLabel").value; if(f) list=list.filter(x=>x.label===f);
  const s=$("#sortBy").value;
  list.sort((a,b)=> s==="rank"? b.score-a.score : s==="hook"? b.hook.score-a.hook.score : a.start-b.start);
  $("#moments").innerHTML = list.length ? list.map(x=>{
    const i = STATE.moments.indexOf(x);
    return `<article class="moment ${x.rank===1?"top":""}" id="moment-${i}">
    <div class="m-head"><div><span class="tag">${x.rank===1?"👑 #1 · ":"#"+x.rank+" · "}${esc(x.label)}</span>
      <h3 style="margin:8px 0 4px">${esc(x.title)}</h3>
      <span class="time">⏱ ${fmt(x.start)} → ${fmt(x.end)} · ${x.duration}s · ${x.wpm} wpm</span></div>
      <div class="score" style="color:${x.score>=85?"#ff4d6d":x.score>=65?"#ffb347":"#9a9aff"}">${x.score}<small>virality</small></div></div>
    <div class="hookbox"><b>Hook (${x.hook.score}/100 · grade ${x.hook.grade}):</b> “${esc(x.hook.text)}…”
      ${x.hook.strengths.length?`<br><span class="muted">${x.hook.strengths.map(esc).join(" · ")}</span>`:""}</div>
    ${x.why.length?`<ul class="why">${x.why.map(w=>`<li>${esc(w)}</li>`).join("")}</ul>`:""}
    <details><summary class="muted">✍️ Hook rewrites</summary><ol class="rewrites">${x.hook.rewrites.map(r=>`<li>${esc(r)}</li>`).join("")}</ol></details>
    <details class="transcript"><summary class="muted">📝 Transcript</summary><p>${esc(x.transcript)}</p></details>
    <div class="m-actions">
      <button onclick="preview(${i})">▶ Preview</button>
      <button onclick="makeClip(${i}, this)">✂️ Make 9:16 clip</button>
      <button onclick="makeClip(${i}, this, false)">16:9 clip</button>
      <button onclick="copyCaption(${i})">📋 Copy caption</button>
    </div><p class="clip-out" id="clipout-${i}"></p></article>`;
  }).join("") : `<p class="muted">No moments matched. (Need a transcript? Paste one above, or upload a .srt file.)</p>`;
}

function preview(i){
  const x=STATE.moments[i], m=STATE.meta;
  $("#modalTitle").textContent = `#${x.rank} ${x.title}  (${fmt(x.start)} → ${fmt(x.end)})`;
  $("#modalBody").innerHTML = m.youtube_id
    ? `<iframe src="https://www.youtube.com/embed/${m.youtube_id}?start=${Math.floor(x.start)}&end=${Math.ceil(x.end)}&autoplay=1" allow="autoplay; encrypted-media" allowfullscreen></iframe>
       <p class="muted">Playing exactly this moment. Happy with it? Close this and hit “Make 9:16 clip”.</p>`
    : `<div class="hookbox">“${esc(x.transcript)}”</div><p class="muted">In-page preview is available for YouTube links. Use “Make clip” to generate &amp; watch the actual MP4.</p>`;
  $("#modal").classList.remove("hidden");
}

async function makeClip(i, btn, vertical=true){
  const x=STATE.moments[i]; return cutClip(x.start, x.end, vertical, btn, $("#clipout-"+i));
}
async function cutClip(start, end, vertical, btn, outEl){
  const old=btn.textContent; btn.disabled=true; btn.textContent="⏳ Cutting… (download + ffmpeg)";
  try{
    const data = await postJSON("/api/clip", {url: STATE.url || STATE.meta.url || "", upload_id: STATE.upload_id, start, end, vertical});
    outEl.innerHTML = `✅ <a class="dl" href="${data.download}" download>⬇ Download ${esc(data.file)}</a> &nbsp;<video src="${data.download}" controls style="width:100%;margin-top:8px;border-radius:10px"></video>`;
    toast("Clip ready 🎬");
  }catch(e){ outEl.innerHTML = `<span style="color:#ff8080">⚠ ${esc(e.message)}</span>`; }
  finally{ btn.disabled=false; btn.textContent=old; }
}

function copyCaption(i){
  const x=STATE.moments[i];
  navigator.clipboard.writeText(`${x.title}\n\n${x.caption}`).then(()=>toast("Caption + hashtags copied 📋"));
}

$("#analyzeBtn").onclick = analyze;
$("#demoBtn").onclick = demo;
$("#url").addEventListener("keydown", e=>{ if(e.key==="Enter") analyze(); });
$("#fileInput").onchange = e=>{ if(e.target.files[0]) uploadFile(e.target.files[0]); };
$("#sortBy").onchange = renderMoments;
$("#filterLabel").onchange = renderMoments;
$("#modalClose").onclick = ()=>{ $("#modal").classList.add("hidden"); $("#modalBody").innerHTML=""; };
$("#modal").addEventListener("click", e=>{ if(e.target.id==="modal") $("#modalClose").click(); });
$("#manualBtn").onclick = e=>cutClip(+$("#mStart").value, +$("#mEnd").value, $("#mVertical").checked, e.target, $("#manualOut"));
