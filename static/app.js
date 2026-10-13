const $ = s => document.querySelector(s);
let STATE = { moments: [], meta: {}, upload_id: "", url: "", edits: {} };
let OPTIONS = {
  qualities: {"1080":"1080p · best quality","720":"720p · balanced (recommended)","480":"480p · small file, fast upload"},
  caption_styles: {"none":"🚫 No burned-in captions","hormozi":"🟨 Hormozi — bold, word-by-word yellow highlight","mrbeast":"🔥 MrBeast — huge centred pop captions","karaoke":"🎤 Karaoke — word-by-word cyan sweep","neon":"💜 Neon Pop — magenta glow, centre screen","minimal":"⬜ Minimal — clean small white, bottom","cinematic":"🎬 Cinematic — elegant lower-third"}
};
let LIBRARY = JSON.parse(localStorage.getItem("clipppers_library_v1") || "[]");

const fmt = s => { s = Math.max(0, Math.round(s)); return `${String(Math.floor(s/60)).padStart(2,"0")}:${String(s%60).padStart(2,"0")}`; };
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function toast(msg){ const t=$("#toast"); t.textContent=msg; t.classList.remove("hidden"); setTimeout(()=>t.classList.add("hidden"), 3400); }
function showError(m){ const e=$("#error"); e.textContent="⚠ "+m; e.classList.remove("hidden"); }

/* ---------------------------------------------------------- persistence */
function getEdit(i){
  const x = STATE.moments[i];
  return STATE.edits[i] || (STATE.edits[i] = {
    start: x.start, end: x.end, title: x.title, caption: x.caption,
    caption_style: "hormozi", quality: "720", vertical: true, download: "", file: "" });
}
let saveTimer;
function autosave(msg="💾 All edits saved"){
  clearTimeout(saveTimer);
  saveTimer = setTimeout(()=>{
    localStorage.setItem("clipppers_session_v1", JSON.stringify(STATE));
    $("#saveStatus").textContent = msg + " · " + new Date().toLocaleTimeString();
  }, 250);
}
function persistLibrary(){
  localStorage.setItem("clipppers_library_v1", JSON.stringify(LIBRARY));
}
async function syncLibrary(){
  try{
    const r = await fetch("/api/projects"); const d = await r.json();
    const byId = Object.fromEntries(LIBRARY.map(p=>[p.id,p]));
    (d.projects||[]).forEach(p=>{ if(!byId[p.id] || (p.updated||0) > (byId[p.id].updated||0)) byId[p.id]=p; });
    LIBRARY = Object.values(byId).sort((a,b)=>(b.updated||0)-(a.updated||0));
    persistLibrary();
  }catch(e){ /* offline: localStorage copy still works */ }
  renderLibrary();
}

/* ------------------------------------------------------------- analyse */
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
function setResult(data, url){
  STATE = { moments: data.moments||[], meta: data.meta||{}, upload_id: data.upload_id||"", url: url||"", edits: {} };
  STATE.moments.forEach((_,i)=>getEdit(i));
  render(data); autosave("💾 Analysis saved");
  if(data.warning) toast("⚠ " + data.warning);
}
async function analyze(){
  const btn=$("#analyzeBtn"); btn.disabled=true; btn.textContent="⏳ Analyzing…";
  $("#error").classList.add("hidden");
  try{
    const data = await runProgress(postJSON("/api/analyze", {
      url: $("#url").value.trim(), transcript: $("#transcript").value,
      target_len: +$("#targetLen").value }));
    setResult(data, $("#url").value.trim());
  }catch(e){ showError(e.message); }
  finally{ btn.disabled=false; btn.textContent="⚡ Analyze video"; }
}
async function demo(){
  const data = await runProgress(fetch("/api/demo").then(r=>r.json()));
  setResult(data, ""); toast("Demo loaded — edit a clip below, it auto-saves to your library");
}
async function uploadFile(file){
  const fd = new FormData(); fd.append("file", file); fd.append("transcript", $("#transcript").value);
  toast("⬆ Uploading " + file.name + "…");
  const r = await fetch("/api/upload", {method:"POST", body:fd});
  const data = await r.json().catch(()=>({error:"Upload failed"}));
  if(data.error) return showError(data.error);
  setResult(data, "");
}

/* -------------------------------------------------------------- render */
function styleOpts(sel){ return Object.entries(OPTIONS.caption_styles).map(([k,v])=>`<option value="${k}" ${k===sel?"selected":""}>${esc(v)}</option>`).join(""); }
function qualityOpts(sel){ return Object.entries(OPTIONS.qualities).map(([k,v])=>`<option value="${k}" ${k===sel?"selected":""}>${esc(v)}</option>`).join(""); }

function render(data){
  $("#results").classList.remove("hidden");
  const m = data.meta||{};
  $("#videoCard").innerHTML = `
    ${m.thumbnail?`<img src="${esc(m.thumbnail)}" alt="">`:""}
    <div><h3 style="margin:0 0 6px">${esc(m.title||"Untitled video")}</h3>
    <p class="muted" style="margin:0">${esc(m.uploader||"")} ${m.platform?"· "+esc(m.platform):""} ${m.duration?"· "+fmt(m.duration):""}
    ${m.view_count?"· "+Number(m.view_count).toLocaleString()+" views":""}<br>
    Source: <b>${esc(data.source||"transcript")}</b> · analysed ${new Date().toLocaleString()}</p>
    ${m.url?`<p><a class="dl" href="${esc(m.url)}" target="_blank" rel="noopener">Open original ↗</a></p>`:""}</div>`;

  const h = data.opening_hook;
  $("#hookReport").innerHTML = h ? `<div class="hook-report">
    <div style="display:flex;gap:22px;flex-wrap:wrap;align-items:center">
      <div><div class="gauge" style="color:${h.score>=70?"var(--good)":h.score>=45?"var(--acc2)":"var(--acc)"}">${h.score}<small style="font-size:16px">/100</small></div>
      <div class="muted">Opening hook grade <b style="color:#fff">${h.grade}</b></div></div>
      <div style="flex:1;min-width:260px"><b>🎣 Your video's actual first seconds:</b>
      <div class="hookbox">“${esc(h.text)}…”</div>
      ${h.strengths.length?`<ul class="why">${h.strengths.map(s=>`<li>${esc(s)}</li>`).join("")}</ul>`:`<p class="muted">No recognised hook pattern — the openings below would fix that:</p>`}
      <b>✍️ Stronger opening hooks for this video:</b>
      <ol class="rewrites">${h.rewrites.map(r=>`<li>${esc(r)}</li>`).join("")}</ol></div>
    </div></div>` : "";

  const dur = Math.max(m.duration||0, ...STATE.moments.map(x=>x.end), 1);
  $("#timeline").innerHTML = STATE.moments.map((x,i)=>
    `<div class="tick" title="#${x.rank} ${esc(x.title)} (${x.score})"
       style="left:${x.start/dur*100}%;width:${Math.max(1.2,(x.end-x.start)/dur*100)}%;background:${x.score>=85?"#ff4d6d":x.score>=65?"#ffb347":"#7a7aff"}"
       onclick="document.getElementById('moment-${i}').scrollIntoView({behavior:'smooth'})"><span>${x.score}</span></div>`).join("");

  const labels=[...new Set(STATE.moments.map(x=>x.label))];
  $("#filterLabel").innerHTML = `<option value="">All types</option>` + labels.map(l=>`<option>${esc(l)}</option>`).join("");
  $("#momentCount").textContent = `— ${STATE.moments.length} found · edits auto-save 💾`;
  renderMoments();
}

function renderMoments(){
  let list=[...STATE.moments];
  const f=$("#filterLabel").value; if(f) list=list.filter(x=>x.label===f);
  const s=$("#sortBy").value;
  list.sort((a,b)=> s==="rank"? b.score-a.score : s==="hook"? b.hook.score-a.hook.score : a.start-b.start);
  $("#moments").innerHTML = list.length ? list.map(x=>{
    const i = STATE.moments.indexOf(x), e = getEdit(i);
    return `<article class="moment ${x.rank===1?"top":""}" id="moment-${i}">
    <div class="m-head"><div><span class="tag">${x.rank===1?"👑 #1 · ":"#"+x.rank+" · "}${esc(x.label)}</span>
      <div class="score" style="color:${x.score>=85?"#ff4d6d":x.score>=65?"#ffb347":"#9a9aff"};float:right">${x.score}<small>virality</small></div>
      <input class="title-edit" value="${esc(e.title)}" onchange="editField(${i},'title',this.value)" aria-label="Clip title">
      <span class="time">⏱ original ${fmt(x.start)} → ${fmt(x.end)} · ${x.wpm} wpm · hook ${x.hook.score}/100 (${x.hook.grade})</span></div></div>
    <div class="hookbox"><b>Hook:</b> “${esc(x.hook.text)}…”
      ${x.hook.strengths.length?`<br><span class="muted">${x.hook.strengths.map(esc).join(" · ")}</span>`:""}</div>
    ${x.why.length?`<ul class="why">${x.why.map(w=>`<li>${esc(w)}</li>`).join("")}</ul>`:""}

    <div class="editbox">
      <b>✏️ Your edit <span class="muted">(saved automatically)</span></b>
      <div class="row">
        <label>Start (s) <input type="number" step="0.1" min="0" value="${e.start}" onchange="editField(${i},'start',+this.value)"></label>
        <label>End (s) <input type="number" step="0.1" min="0" value="${e.end}" onchange="editField(${i},'end',+this.value)"></label>
        <label class="check"><input type="checkbox" ${e.vertical?"checked":""} onchange="editField(${i},'vertical',this.checked)"> 9:16 vertical</label>
      </div>
      <div class="row">
        <label>🎨 Caption style <select onchange="editField(${i},'caption_style',this.value)">${styleOpts(e.caption_style)}</select></label>
        <label>📦 Export quality <select onchange="editField(${i},'quality',this.value)">${qualityOpts(e.quality)}</select></label>
      </div>
      <label class="caplabel">Caption / post text
        <textarea rows="2" onchange="editField(${i},'caption',this.value)">${esc(e.caption)}</textarea></label>
    </div>

    <details><summary class="muted">✍️ Hook rewrites</summary><ol class="rewrites">${x.hook.rewrites.map(r=>`<li>${esc(r)}</li>`).join("")}</ol></details>
    <details class="transcript"><summary class="muted">📝 Transcript (used for burned-in captions)</summary><p>${esc(x.transcript)}</p></details>
    <div class="m-actions">
      <button onclick="preview(${i})">▶ Preview</button>
      <button class="primary" onclick="makeClip(${i}, this)">✂️ Export clip</button>
      <button onclick="saveToLibrary(${i})">💾 Save to library</button>
      <button onclick="copyCaption(${i})">📋 Copy caption</button>
    </div><p class="clip-out" id="clipout-${i}">${e.download?downloadHtml(e):""}</p></article>`;
  }).join("") : `<p class="muted">No moments matched. (Need a transcript? Paste one above, or upload a .srt file.)</p>`;
}
function downloadHtml(e){
  return `✅ <a class="dl" href="${e.download}" download>⬇ Download ${esc(e.file)}</a> <span class="muted">${esc(e.quality)}p · ${esc(e.caption_style)} captions</span><video src="${e.download}" controls style="width:100%;margin-top:8px;border-radius:10px"></video>`;
}
function editField(i, key, val){ getEdit(i)[key]=val; autosave(); }

/* --------------------------------------------------------------- clips */
function preview(i){
  const x=STATE.moments[i], e=getEdit(i), m=STATE.meta;
  $("#modalTitle").textContent = `${e.title} (${fmt(e.start)} → ${fmt(e.end)})`;
  $("#modalBody").innerHTML = m.youtube_id
    ? `<iframe src="https://www.youtube.com/embed/${m.youtube_id}?start=${Math.floor(e.start)}&end=${Math.ceil(e.end)}&autoplay=1" allow="autoplay; encrypted-media" allowfullscreen></iframe>
       <p class="muted">Playing your edited range. Happy? Close this and hit “✂️ Export clip”.</p>`
    : `<div class="hookbox">“${esc(x.transcript)}”</div><p class="muted">In-page preview is available for YouTube links. Use “✂️ Export clip” to watch the actual MP4.</p>`;
  $("#modal").classList.remove("hidden");
}
async function cutClip(payload, btn, outEl){
  const old=btn.textContent; btn.disabled=true; btn.textContent="⏳ Exporting… (download + ffmpeg + captions)";
  try{
    const data = await postJSON("/api/clip", payload);
    outEl.innerHTML = `✅ <a class="dl" href="${data.download}" download>⬇ Download ${esc(data.file)}</a> <span class="muted">${data.quality}p · ${esc(data.caption_style)} · ${data.size_kb} KB</span><video src="${data.download}" controls style="width:100%;margin-top:8px;border-radius:10px"></video>`;
    toast("Clip exported 🎬 " + data.quality + "p");
    return data;
  }catch(e){ outEl.innerHTML = `<span style="color:#ff8080">⚠ ${esc(e.message)}</span>`; return null; }
  finally{ btn.disabled=false; btn.textContent=old; }
}
async function makeClip(i, btn){
  const e=getEdit(i), x=STATE.moments[i];
  const data = await cutClip({ url: STATE.url || STATE.meta.url || "", upload_id: STATE.upload_id,
    start:+e.start, end:+e.end, vertical:!!e.vertical, quality:e.quality,
    caption_style:e.caption_style, caption_text:x.transcript }, btn, $("#clipout-"+i));
  if(data){ Object.assign(e, {download:data.download, file:data.file}); autosave(); saveToLibrary(i, true); }
}
function copyCaption(i){
  const e=getEdit(i);
  navigator.clipboard.writeText(`${e.title}\n\n${e.caption}`).then(()=>toast("Caption + hashtags copied 📋"));
}

/* ------------------------------------------------------------- library */
function saveToLibrary(i, quiet=false){
  const e = {...getEdit(i)}, x = STATE.moments[i];
  const name = STATE.meta.title || "Untitled video";
  let proj = LIBRARY.find(p=>p.name===name && (p.source?.url||"")===(STATE.url||""));
  const editRec = { ...e, moment: x };
  if(!proj){
    proj = { id: Math.random().toString(16).slice(2,14), name,
             source:{ url: STATE.url||STATE.meta.url||"", upload_id: STATE.upload_id, meta: STATE.meta },
             created: Date.now(), edits: [] };
    LIBRARY.unshift(proj);
  }
  const key = r => `${r.start}-${r.end}-${r.title}`;
  proj.edits = [editRec, ...proj.edits.filter(r=>key(r)!==key(editRec))];
  proj.updated = Date.now();
  persistLibrary(); renderLibrary(); autosave();
  fetch("/api/projects", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(proj)}).catch(()=>{});
  if(!quiet) toast("Saved to library 💾 — find it under “My library” anytime");
}
async function saveProject(){
  if(!STATE.moments.length) return toast("Analyse a video first, then save 💡");
  STATE.moments.forEach((_,i)=>saveToLibrary(i, true));
  toast("Whole project saved to your library 💾");
}
function renderLibrary(){
  $("#projectList").innerHTML = LIBRARY.length ? LIBRARY.map(p=>`
    <article class="moment">
      <div class="m-head"><div><h3 style="margin:0">${esc(p.name)}</h3>
      <span class="muted">${p.edits.length} saved edit(s) · ${new Date(p.updated||p.created).toLocaleString()}</span></div></div>
      ${p.edits.map((e,j)=>`<div class="libedit">
        <b>${esc(e.title)}</b><br><span class="time">⏱ ${fmt(e.start)} → ${fmt(e.end)}</span>
        <span class="muted">· ${e.vertical?"9:16":"16:9"} · ${esc(e.quality)}p · 🎨 ${esc(e.caption_style)}</span><br>
        ${e.download?`<a class="dl" href="${e.download}" download>⬇ ${esc(e.file||"Download MP4")}</a> · `:""}
        <a href="#" onclick="loadProject('${p.id}',${j});return false">↩ Load this edit</a> ·
        <a href="#" onclick="deleteEdit('${p.id}',${j});return false">🗑 Delete</a></div>`).join("")}
      <div class="m-actions"><button onclick="loadProject('${p.id}')">↩ Open project</button>
      <button onclick="deleteProject('${p.id}')">🗑 Delete project</button></div>
    </article>`).join("")
    : `<p class="muted">Nothing saved yet. Analyse a video → tweak a clip's trim, title, caption style &amp; quality → it auto-saves here (this browser + the server).</p>`;
}
function loadProject(pid, editIdx){
  const p = LIBRARY.find(x=>x.id===pid); if(!p) return;
  STATE = { moments: p.edits.map(e=>e.moment), meta: p.source.meta||{}, upload_id: p.source.upload_id||"",
            url: p.source.url||"", edits: {} };
  p.edits.forEach((e,i)=>{ STATE.edits[i]=e; });
  render({meta: STATE.meta, opening_hook: null, source:"library"});
  toast("Project loaded ↩ — your previous edits are restored");
  window.scrollTo({top: $("#results").offsetTop, behavior:"smooth"});
}
async function deleteProject(pid){
  LIBRARY = LIBRARY.filter(p=>p.id!==pid); persistLibrary(); renderLibrary();
  fetch("/api/projects/"+pid, {method:"DELETE"}).catch(()=>{});
  toast("Project deleted");
}
function deleteEdit(pid, j){
  const p = LIBRARY.find(x=>x.id===pid); if(!p) return;
  p.edits.splice(j,1); p.updated = Date.now();
  if(!p.edits.length) return deleteProject(pid);
  persistLibrary(); renderLibrary();
  fetch("/api/projects", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(p)}).catch(()=>{});
}
function exportLibrary(){
  const blob = new Blob([JSON.stringify(LIBRARY, null, 1)], {type:"application/json"});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = "clipppers-library.json"; a.click(); toast("Library exported ⬇");
}
async function importLibrary(file){
  try{
    const items = JSON.parse(await file.text());
    const byId = Object.fromEntries(LIBRARY.map(p=>[p.id,p]));
    items.forEach(p=>byId[p.id]=p); LIBRARY = Object.values(byId);
    persistLibrary(); renderLibrary();
    for(const p of items) fetch("/api/projects", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(p)}).catch(()=>{});
    toast("Library imported 📥");
  }catch(e){ toast("⚠ That file isn't a Clipppers library"); }
}

/* ---------------------------------------------------------------- wire */
$("#analyzeBtn").onclick = analyze;
$("#demoBtn").onclick = demo;
$("#url").addEventListener("keydown", e=>{ if(e.key==="Enter") analyze(); });
$("#fileInput").onchange = e=>{ if(e.target.files[0]) uploadFile(e.target.files[0]); };
$("#sortBy").onchange = renderMoments;
$("#filterLabel").onchange = renderMoments;
$("#modalClose").onclick = ()=>{ $("#modal").classList.add("hidden"); $("#modalBody").innerHTML=""; };
$("#modal").addEventListener("click", e=>{ if(e.target.id==="modal") $("#modalClose").click(); });
$("#saveProjectBtn").onclick = saveProject;
$("#exportLibBtn").onclick = exportLibrary;
$("#importLib").onchange = e=>{ if(e.target.files[0]) importLibrary(e.target.files[0]); };
$("#manualBtn").onclick = e=>cutClip({ url: STATE.url || STATE.meta.url || "", upload_id: STATE.upload_id,
  start:+$("#mStart").value, end:+$("#mEnd").value, vertical:$("#mVertical").checked,
  quality:$("#mQuality").value, caption_style:$("#mStyle").value,
  caption_text:$("#mCaptionText").value || (STATE.moments[0]?.transcript||"") }, e.target, $("#manualOut"));

(async function init(){
  try{ const r = await fetch("/api/options"); if(r.ok) OPTIONS = await r.json(); }catch(e){}
  document.querySelectorAll(".styleSel").forEach(s=>s.innerHTML = styleOpts("hormozi"));
  document.querySelectorAll(".qualitySel").forEach(s=>s.innerHTML = qualityOpts("720"));
  await syncLibrary();
  const last = localStorage.getItem("clipppers_session_v1");
  if(last){
    try{
      STATE = JSON.parse(last);
      if(STATE.moments?.length){ render({meta:STATE.meta, source:"last session"}); toast("↩ Restored your last session — all edits intact"); }
    }catch(e){}
  }
})();
