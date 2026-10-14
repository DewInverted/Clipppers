const $ = s => document.querySelector(s);
let STATE = { moments: [], meta: {}, upload_id: "", url: "", edits: {} };
let OPTIONS = {
  qualities: {"1080":"1080p · best quality","720":"720p · balanced (recommended)","480":"480p · small file, fast upload"},
  caption_styles: {"none":"🚫 No burned-in captions","hormozi":"🟨 Hormozi — bold, word-by-word yellow highlight","mrbeast":"🔥 MrBeast — huge centred pop captions","karaoke":"🎤 Karaoke — word-by-word cyan sweep","neon":"💜 Neon Pop — magenta glow, centre screen","minimal":"⬜ Minimal — clean small white, bottom","cinematic":"🎬 Cinematic — elegant lower-third"}
};
let LIBRARY = JSON.parse(localStorage.getItem("clipppers_library_v1") || "[]");

const fmt = s => { s = Math.max(0, Math.round(s)); return `${String(Math.floor(s/60)).padStart(2,"0")}:${String(s%60).padStart(2,"0")}`; };
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function toast(msg){ const t=$("#toast"); t.textContent=msg; t.classList.remove("hidden"); setTimeout(()=>t.classList.add("hidden"), 3400); }
function showError(m){ const e=$("#error"); e.textContent="⚠ "+m; e.classList.remove("hidden"); }

/* ------------------------------------------------------- youtube helpers */
function youtubeIdFromUrl(url){
  if(!url) return null;
  const m = url.match(/(?:v=|youtu\.be\/|shorts\/|embed\/)([\w-]{6,})/);
  return m ? m[1] : null;
}
function youtubeTimestampUrl(url, start){
  const yid = youtubeIdFromUrl(url);
  if(!yid) return url || "";
  return `https://www.youtube.com/watch?v=${yid}&t=${Math.floor(start||0)}s`;
}
function youtubeThumbUrl(url){
  const yid = youtubeIdFromUrl(url);
  return yid ? `https://i.ytimg.com/vi/${yid}/hqdefault.jpg` : "";
}
function thumbForEdit(e, meta){
  // Priority: exported clip thumbnail > source (youtube) thumbnail > nothing
  if(e && e.thumbnail) return e.thumbnail;
  if(meta && meta.thumbnail) return meta.thumbnail;
  const srcUrl = (STATE && (STATE.url || (STATE.meta && STATE.meta.url))) || "";
  if(srcUrl){ const t = youtubeThumbUrl(srcUrl); if(t) return t; }
  return "";
}
function portraitThumb(src, alt){
  if(!src) return `<div class="thumb-placeholder" aria-hidden="true"><span>▶</span></div>`;
  // contained portrait thumb: use object-fit:cover in a 9:16 frame, background falls back
  return `<div class="thumb-frame"><img src="${esc(src)}" alt="${esc(alt||"")}" loading="lazy"
            onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'thumb-placeholder',innerHTML:'<span>▶</span>'}))"></div>`;
}

/* ---------------------------------------------------------- persistence */
function getEdit(i){
  const x = STATE.moments[i];
  return STATE.edits[i] || (STATE.edits[i] = {
    start: x.start, end: x.end, title: x.title, caption: x.caption,
    caption_style: "hormozi", quality: "720", vertical: true,
    crop_mode: "blur",
    caption_text_override: "",  // when set, burns THIS text instead of auto transcript
    font_size: 0, margin_v: 0,  // 0 = default per style
    download: "", file: "", thumbnail: "", youtube_url: "" });
}
function capTextFor(e, x){ return (e.caption_text_override && e.caption_text_override.trim()) ? e.caption_text_override.trim() : (x.transcript||""); }
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
    const r = await fetch("/api/projects");
    if(!r.ok){
      // Always parse JSON to surface real errors, even on non-2xx
      const err = await r.json().catch(()=>({error:`Server returned ${r.status}`}));
      console.warn("syncLibrary:", err.error);
    } else {
      const d = await r.json();
      const byId = Object.fromEntries(LIBRARY.map(p=>[p.id,p]));
      (d.projects||[]).forEach(p=>{ if(!byId[p.id] || (p.updated||0) > (byId[p.id].updated||0)) byId[p.id]=p; });
      LIBRARY = Object.values(byId).sort((a,b)=>(b.updated||0)-(a.updated||0));
      persistLibrary();
    }
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
  let r, data;
  try{
    r = await fetch(path, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  }catch(netErr){
    throw new Error("Network error — is the server still running? (" + netErr.message + ")");
  }
  // Always try to parse JSON, whether response was ok or not — so we surface the real error message
  const text = await r.text().catch(()=>"");
  try{ data = text ? JSON.parse(text) : {error:`Empty response (status ${r.status})`}; }
  catch(e){ data = {error: (text.slice(0,300) || `Server returned status ${r.status} with non-JSON response`)}; }
  if(!r.ok || data.error) throw new Error(data.error || `Request failed with status ${r.status}`);
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
  try{
    const data = await runProgress(fetch("/api/demo").then(async r=>{
      const j = await r.json().catch(()=>({error:"Demo endpoint failed"}));
      if(!r.ok) throw new Error(j.error||"Demo failed");
      return j;
    }));
    setResult(data, ""); toast("Demo loaded — edit a clip below, it auto-saves to your library");
  }catch(e){ showError(e.message); }
}
async function uploadFile(file){
  const fd = new FormData(); fd.append("file", file); fd.append("transcript", $("#transcript").value);
  toast("⬆ Uploading " + file.name + "…");
  const r = await fetch("/api/upload", {method:"POST", body:fd}).catch(e=>({ok:false, json:async()=>({error:"Network error: "+e.message})}));
  let data;
  try{ data = await r.json(); }catch(e){ data = {error:"Upload failed — bad server response"}; }
  if(data.error) return showError(data.error);
  setResult(data, "");
}

/* -------------------------------------------------------------- render */
function styleOpts(sel){ return Object.entries(OPTIONS.caption_styles).map(([k,v])=>`<option value="${k}" ${k===sel?"selected":""}>${esc(v)}</option>`).join(""); }
function qualityOpts(sel){ return Object.entries(OPTIONS.qualities).map(([k,v])=>`<option value="${k}" ${k===sel?"selected":""}>${esc(v)}</option>`).join(""); }

function render(data){
  $("#results").classList.remove("hidden");
  const m = data.meta||{};
  const srcUrl = STATE.url || m.url || "";
  const yid = youtubeIdFromUrl(srcUrl);
  const srcThumb = m.thumbnail || (yid ? youtubeThumbUrl(srcUrl) : "");
  $("#videoCard").innerHTML = `
    ${srcThumb ? `<div class="video-card-thumb"><img src="${esc(srcThumb)}" alt="" loading="lazy"></div>` : ""}
    <div class="video-card-body"><h3 style="margin:0 0 6px">${esc(m.title||"Untitled video")}</h3>
    <p class="muted" style="margin:0">${esc(m.uploader||"")} ${m.platform?"· "+esc(m.platform):""} ${m.duration?"· "+fmt(m.duration):""}
    ${m.view_count?"· "+Number(m.view_count).toLocaleString()+" views":""}<br>
    Source: <b>${esc(data.source||"transcript")}</b> · analysed ${new Date().toLocaleString()}</p>
    ${srcUrl?`<p class="video-card-links">
        <a class="dl" href="${esc(srcUrl)}" target="_blank" rel="noopener">Open original ↗</a>
        ${yid?`<span class="muted"> · timestamped previews open in a new tab, clipped MP4s play right here.</span>`:""}
      </p>`:""}</div>`;

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
    const srcUrl = STATE.url || STATE.meta.url || "";
    const yid = youtubeIdFromUrl(srcUrl);
    const thumb = thumbForEdit(e, STATE.meta);
    return `<article class="moment ${x.rank===1?"top":""}" id="moment-${i}">
    <div class="moment-top">
      <div class="moment-thumb">${portraitThumb(thumb, e.title || x.title)}</div>
      <div class="moment-body">
        <div class="m-head">
          <div>
            <span class="tag">${x.rank===1?"👑 #1 · ":"#"+x.rank+" · "}${esc(x.label)}</span>
            <div class="score" style="color:${x.score>=85?"#ff4d6d":x.score>=65?"#ffb347":"#9a9aff"};float:right">${x.score}<small>virality</small></div>
            <input class="title-edit" value="${esc(e.title)}" onchange="editField(${i},'title',this.value)" aria-label="Clip title">
            <span class="time">⏱ original ${fmt(x.start)} → ${fmt(x.end)} · ${x.wpm} wpm · hook ${x.hook.score}/100 (${x.hook.grade})</span>
          </div>
        </div>
        <div class="hookbox"><b>Hook:</b> “${esc(x.hook.text)}…”
          ${x.hook.strengths.length?`<br><span class="muted">${x.hook.strengths.map(esc).join(" · ")}</span>`:""}</div>
      </div>
    </div>
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
        <label>📐 Framing
          <select onchange="editField(${i},'crop_mode',this.value)">
            <option value="blur"${e.crop_mode==='blur'?' selected':''}>🫧 Blurred background</option>
            <option value="crop"${e.crop_mode==='crop'?' selected':''}>🔍 Center-crop</option>
          </select>
        </label>
      </div>
      <label class="caplabel">Caption text (burned into video — edit to reword/remove words)
        <textarea rows="2" oninput="editField(${i},'caption_text_override',this.value)" placeholder="${esc(x.transcript?x.transcript.slice(0,160)+(x.transcript.length>160?'…':''):'(leave blank to use auto transcript)')}">${esc(e.caption_text_override||"")}</textarea>
      </label>
      <div class="row">
        <label>🔠 Text size
          <input type="range" min="24" max="90" step="2" value="${e.font_size||52}"
            oninput="editField(${i},'font_size',+this.value);this.nextElementSibling.textContent=this.value+'px'">
          <span class="muted" style="min-width:42px;display:inline-block;text-align:right">${e.font_size?e.font_size+'px':'auto'}</span>
        </label>
        <label>⬇ Position
          <input type="range" min="40" max="400" step="10" value="${e.margin_v||220}"
            oninput="editField(${i},'margin_v',+this.value);this.nextElementSibling.textContent=this.value+'px'">
          <span class="muted" style="min-width:42px;display:inline-block;text-align:right">${e.margin_v?e.margin_v+'px':'auto'}</span>
        </label>
        <label><button type="button" class="ghost" onclick="editField(${i},'font_size',0);editField(${i},'margin_v',0);renderMoments()">↺ Reset size/position</button></label>
      </div>
      <label class="caplabel">Post caption (for TikTok/Shorts description — not burned in)
        <textarea rows="2" onchange="editField(${i},'caption',this.value)">${esc(e.caption)}</textarea>
      </label>
    </div>

    ${x.recipe?recipeHtml(x.recipe):""}
    <details><summary class="muted">✍️ Hook rewrites</summary><ol class="rewrites">${(x.hook?.rewrites||x.recipe?.hook_rewrites||[]).map(r=>`<li>${esc(r)}</li>`).join("")}</ol></details>
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
  const dl = `<a class="dl" href="${esc(e.download)}" download>⬇ Download ${esc(e.file)}</a>`;
  const ytLink = e.youtube_url ? `<a class="dl dl-alt" href="${esc(e.youtube_url)}" target="_blank" rel="noopener">🔗 Open at timestamp ↗</a>` : "";
  const cutInfo = (e.fillers_removed && e.fillers_removed>0) ? ` · ✂ cut ${e.fillers_removed.toFixed(1)}s fillers` : "";
  const meta = `<span class="muted">${esc(e.quality)}p · ${esc(e.caption_style)} · ${e.size_kb} KB${cutInfo}</span>`;
  const player = `<div class="clip-player"><video src="${esc(e.download)}" controls preload="metadata" playsinline style="width:100%;border-radius:12px;background:#000"></video></div>`;
  return `<div class="clip-ready">
    <div class="clip-ready-head">✅ Clip ready — ${dl}${ytLink?" · "+ytLink:""}<br>${meta}</div>
    ${e.thumbnail ? `<div class="clip-ready-thumb"><img src="${esc(e.thumbnail)}" alt="clip preview" loading="lazy"></div>` : ""}
    ${player}
  </div>`;
}
function editField(i, key, val){ getEdit(i)[key]=val; autosave(); }

/* ----------------------------------------------------- preview (no iframe) */
function preview(i){
  const x=STATE.moments[i], e=getEdit(i);
  $("#modalTitle").textContent = `${e.title} (${fmt(e.start)} → ${fmt(e.end)})`;

  // Build preview: exported MP4 if available, otherwise source thumbnail + timestamped link
  const srcUrl = STATE.url || STATE.meta.url || "";
  const ytUrl = youtubeTimestampUrl(srcUrl, e.start);
  const isYt = !!youtubeIdFromUrl(srcUrl);
  const thumb = e.thumbnail || thumbForEdit(e, STATE.meta);

  let body = "";
  if(e.download){
    // Already exported — play the actual captioned MP4 in our own player
    body = `<div class="modal-player">
      <div class="player-label" style="background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;font-weight:800">✅ FINAL EDITED CLIP — vertical, captions burned in${e.fillers_removed?`, fillers removed (-${e.fillers_removed}s)`:""}</div>
      <video id="modalVideo" src="${esc(e.download)}" controls autoplay playsinline style="width:100%;border-radius:12px;background:#000;max-height:70vh"></video>
      <p style="margin-top:10px;font-weight:700">This is your edited MP4 — ready to post to TikTok / Reels / Shorts.</p>
      <p class="muted">${e.vertical?"📱 9:16 vertical":"16:9"} · ${esc(e.quality)}p · 🎨 ${esc(e.caption_style)}${e.fillers_removed?` · ✂ ${e.fillers_removed}s of fillers cut`:""}</p>
      <p>
        <a class="dl primary" href="${esc(e.download)}" download style="background:linear-gradient(90deg,#22c55e,#16a34a);color:#fff;text-decoration:none;padding:10px 18px;border-radius:10px;font-weight:700;display:inline-block">⬇ Download MP4</a>
        ${isYt?` <a class="dl dl-alt" href="${esc(ytUrl)}" target="_blank" rel="noopener" style="color:var(--muted);margin-left:10px">🔗 Source on YouTube ↗</a>`:""}
      </p>
      <p class="muted" style="font-size:12px;margin-top:8px">Not happy with it? Change caption style / framing / start/end in the clip card below and click ✂️ Export clip again — new render, new file.</p>
    </div>`;
  } else if(isYt){
    // Pre-export: embed YouTube player that autoplays the exact range, plus transcript
    const yEmbed = `https://www.youtube-nocookie.com/embed/${youtubeIdFromUrl(srcUrl)}?start=${Math.floor(e.start)}&end=${Math.ceil(e.end)}&autoplay=1&rel=0&modestbranding=1&playsinline=1`;
    body = `<div class="modal-player modal-placeholder">
      <div class="player-label" style="background:linear-gradient(90deg,#ffb800,#ff7a00);color:#1a0c00;font-weight:800">
        ⚠ RAW SOURCE PREVIEW — this is YouTube, NOT your edited clip. Click the big ✂️ Export button below to render the final video (cropped 9:16 + captions burned in + fillers removed).
      </div>
      <div class="modal-preview-wrap">
        <div class="modal-yt-frame">
          <iframe id="modalYt" src="${esc(yEmbed)}"
            title="${esc(e.title)}"
            allow="autoplay; encrypted-media; picture-in-picture"
            allowfullscreen
            referrerpolicy="no-referrer-when-downgrade"
            loading="lazy"></iframe>
        </div>
        <div class="modal-preview-meta">
          <p class="muted" style="margin:0 0 6px">Clip range</p>
          <p style="margin:0 0 6px;font-weight:700;font-size:18px">${fmt(e.start)} → ${fmt(e.end)} (${Math.round(e.end-e.start)}s)</p>
          <p class="muted" style="font-size:13px;margin:0 0 10px">
            ${e.vertical?"📱 9:16 vertical (Shorts/TikTok)":(e.quality?"16:9 landscape":"")} · ${esc(e.quality)}p · 🎨 ${esc(e.caption_style)}
          </p>
          <p class="muted" style="font-size:12px;margin:0 0 10px;line-height:1.4">
            Export renders: vertical framing (${esc(e.crop_mode||"blur")} mode) + burned-in captions (${esc(e.caption_style)}) + ${document.getElementById("fillersToggle")?.checked?"filler-word removal ON":"fillers OFF"}.
          </p>
          <div class="row" style="margin-top:6px">
            <button class="primary" style="background:linear-gradient(90deg,#ff3c6e,#ff7a00);font-size:16px;padding:12px 22px" onclick="(this.disabled=true);this.textContent='⏳ Rendering… (download source + ffmpeg captions crop filler-removal)';makeClip(${i},this)">✂️ EXPORT EDITED CLIP</button>
            <a class="ghost" href="${esc(ytUrl)}" target="_blank" rel="noopener" style="text-decoration:none;color:var(--txt);display:inline-flex;align-items:center;gap:6px">🔗 Open on YouTube ↗</a>
          </div>
        </div>
      </div>
      <div class="hookbox transcript-preview" style="margin-top:14px">
        <b>📝 Captions that will be burned in:</b>
        <p style="margin:6px 0 0;line-height:1.5">${esc(x.transcript)}</p>
      </div>
    </div>`;
  } else {
    // No export yet + non-YouTube source (upload)
    body = `<div class="modal-player modal-placeholder">
      <div class="modal-preview-wrap">
        <div class="modal-thumb-box">
          ${thumb ? `<img src="${esc(thumb)}" alt="" class="modal-source-thumb" loading="lazy">` : `<div class="thumb-placeholder big"><span>▶</span></div>`}
        </div>
        <div class="modal-preview-meta">
          <p class="muted" style="margin:0 0 6px">Clip range</p>
          <p style="margin:0 0 10px;font-weight:700;font-size:18px">${fmt(e.start)} → ${fmt(e.end)} (${Math.round(e.end-e.start)}s)</p>
          <p class="muted">In-browser playback requires exporting the clip — click <b>✂️ Export clip</b> to cut the MP4 and watch it here with captions.</p>
          <div class="row" style="margin-top:10px">
            <button class="primary" onclick="(this.disabled=true);this.textContent='⏳ Exporting…';makeClip(${i},this)">✂️ Export clip now</button>
          </div>
        </div>
      </div>
      <div class="hookbox transcript-preview" style="margin-top:14px">
        <b>📝 Transcript that will be burned as captions:</b>
        <p style="margin:6px 0 0;line-height:1.5">${esc(x.transcript)}</p>
      </div>
    </div>`;
  }
  $("#modalBody").innerHTML = body;
  $("#modal").classList.remove("hidden");
}

/* --------------------------------------------------------------- clips */
async function cutClip(payload, btn, outEl){
  const old=btn.textContent; btn.disabled=true; btn.textContent="⏳ Exporting… (download + ffmpeg + captions)";
  try{
    const data = await postJSON("/api/clip", payload);
    outEl.innerHTML = downloadHtml(data);
    toast("Clip exported 🎬 " + data.quality + "p");
    return data;
  }catch(e){
    // Show REAL error message, never the generic "Bad response from server"
    outEl.innerHTML = `<div class="clip-error"><span style="color:#ff8080">⚠ ${esc(e.message)}</span></div>`;
    toast("⚠ " + e.message.slice(0,120));
    return null;
  }finally{ btn.disabled=false; btn.textContent=old; }
}
async function makeClip(i, btn){
  const e=getEdit(i), x=STATE.moments[i];
  const fillers = !!(document.getElementById("fillersToggle")?.checked);
  const data = await cutClip({ url: STATE.url || STATE.meta.url || "", upload_id: STATE.upload_id,
    start:+e.start, end:+e.end, vertical:!!e.vertical, quality:e.quality,
    caption_style:e.caption_style, caption_text: capTextFor(e, x),
    remove_fillers: fillers, crop_mode: e.crop_mode || "blur",
    font_size: e.font_size||0, margin_v: e.margin_v||0 }, btn, $("#clipout-"+i));
  if(data){
    Object.assign(e, {download:data.download, file:data.file,
                      thumbnail:data.thumbnail||"", youtube_url:data.youtube_url||"",
                      fillers_removed:data.fillers_removed||0, duration:data.duration});
    autosave();
    saveToLibrary(i, true);
    renderMoments();
    // Auto-open the modal to SHOW the exported edited MP4 so you don't keep
    // looking at the source YouTube preview thinking nothing happened.
    openPreview(i);
    toast(`✅ Exported — ${data.duration}s edited clip with captions burned in`);
  }
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
    <article class="moment lib-card">
      <div class="m-head lib-card-head">
        <h3 class="lib-title" style="margin:0">${esc(p.name)}</h3>
        <span class="muted">${p.edits.length} saved edit(s) · ${new Date(p.updated||p.created).toLocaleString()}</span>
      </div>
      <div class="lib-edits">
        ${p.edits.map((e,j)=>{
          // Thumbnail priority: clip thumb → source meta thumbnail → youtube hqdefault
          const srcMeta = (p.source && p.source.meta) || {};
          const srcUrl = (p.source && p.source.url) || "";
          const thumb = e.thumbnail || srcMeta.thumbnail || (youtubeIdFromUrl(srcUrl) ? youtubeThumbUrl(srcUrl) : "");
          return `<div class="libedit">
            <div class="libedit-thumb">${portraitThumb(thumb, e.title)}</div>
            <div class="libedit-body">
              <b>${esc(e.title)}</b>
              <div class="time">⏱ ${fmt(e.start)} → ${fmt(e.end)}</div>
              <div class="muted">${e.vertical?"9:16":"16:9"} · ${esc(e.quality)}p · 🎨 ${esc(e.caption_style)}</div>
              <div class="libedit-links">
                ${e.download?`<a class="dl" href="${esc(e.download)}" download>⬇ MP4</a>`:""}
                ${e.download?" · ":""}<a href="#" onclick="loadProject('${p.id}',${j});return false">↩ Load</a> ·
                <a href="#" onclick="deleteEdit('${p.id}',${j});return false">🗑</a>
              </div>
            </div>
          </div>`;
        }).join("")}
      </div>
      <div class="m-actions">
        <button onclick="loadProject('${p.id}')">↩ Open project</button>
        <button onclick="deleteProject('${p.id}')">🗑 Delete project</button>
      </div>
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
  window.scrollTo({top: $("#results").offsetTop - 70, behavior:"smooth"});
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

/* ------------------------------------------------------- niche discover */
const NICHE_LABELS = {
  "finance":"💰 Finance","fitness":"💪 Fitness","business":"🚀 Business","tech":"🤖 Tech",
  "motivation":"🔥 Motivation","gaming":"🎮 Gaming","cooking":"🍳 Cooking","crypto":"₿ Crypto",
  "self-improvement":"🧠 Self-Improvement","relationship":"💬 Relationships","trending":"📈 Trending"
};
let DISCOVER = { videos: [], activeNiche: "trending" };

function renderNicheChips(){
  const row = $("#nicheRow");
  const keys = Object.keys(NICHE_LABELS);
  row.innerHTML = keys.map(k=>`<button class="niche-chip ${k===DISCOVER.activeNiche?"active":""}" data-niche="${k}" onclick="doDiscover('${k}','')">${NICHE_LABELS[k]}</button>`).join("");
}

async function doDiscover(niche, q){
  DISCOVER.activeNiche = niche || "";
  renderNicheChips();
  const list = $("#discoverList");
  list.innerHTML = `<div class="muted" style="padding:14px">🔎 Searching ${esc(niche?NICHE_LABELS[niche]:q||"")}…</div>`;
  const params = new URLSearchParams();
  if(niche) params.set("niche", niche);
  if(q) params.set("q", q);
  params.set("count", "10");
  try{
    const r = await fetch("/api/discover?"+params.toString());
    const d = await r.json().catch(()=>({error:"Bad response"}));
    if(d.error) return list.innerHTML = `<div class="muted" style="padding:14px;color:#ff8080">⚠ ${esc(d.error)}</div>`;
    DISCOVER.videos = d.videos || [];
    if(!DISCOVER.videos.length){ list.innerHTML = `<div class="muted" style="padding:14px">No videos found — try another niche or query.</div>`; return; }
    list.innerHTML = DISCOVER.videos.map((v,idx)=>`
      <article class="discover-card" data-idx="${idx}">
        <div class="discover-thumb">
          <img src="${esc(v.thumbnail)}" alt="${esc(v.title)}" loading="lazy"
               onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
          <div class="thumb-placeholder" style="display:none;aspect-ratio:16/9"><span>▶</span></div>
          ${v.duration?`<span class="disc-dur">${fmt(v.duration)}</span>`:""}
        </div>
        <div class="disc-body">
          <div class="disc-title">${esc(v.title||"(untitled)")}</div>
          <div class="muted disc-sub">${esc(v.channel||"")}${v.views?" · "+Number(v.views).toLocaleString()+" views":""}</div>
          <div class="disc-actions">
            <button class="primary" onclick="analyseDiscovered(${idx}, this)">⚡ Analyse & clip</button>
            <a class="ghost" href="${esc(v.url)}" target="_blank" rel="noopener" style="text-decoration:none;color:var(--txt);display:inline-flex;align-items:center;padding:8px 12px;border-radius:8px;border:1px solid var(--line);font-size:13px">↗ Open</a>
          </div>
        </div>
      </article>`).join("");
  }catch(e){ list.innerHTML = `<div class="muted" style="padding:14px;color:#ff8080">⚠ ${esc(e.message)}</div>`; }
}

async function analyseDiscovered(idx, btn){
  const v = DISCOVER.videos[idx]; if(!v) return;
  btn.disabled = true; btn.textContent = "⏳ Analysing…";
  $("#error").classList.add("hidden");
  $("#url").value = v.url;
  try{
    const data = await runProgress(postJSON("/api/analyze", {
      url: v.url, transcript: "", target_len: +$("#targetLen").value }));
    setResult(data, v.url);
    toast(`Loaded "${v.title?.slice(0,50)||'video'}" — ${(data.moments||[]).length} moments found`);
    window.scrollTo({top: $("#results").offsetTop - 70, behavior:"smooth"});
  }catch(e){ showError(e.message); }
  finally{ btn.disabled=false; btn.textContent="⚡ Analyse & clip"; }
}

async function batchExportTop(n=3, btn){
  if(!STATE.moments.length){ toast("Analyse a video first"); return; }
  if(btn){ btn.disabled=true; btn.textContent="⏳ Rendering "+n+" clips…"; }
  $("#batchStatus").textContent = "Downloading source, cutting, burning captions, removing fillers…";
  // Take top N by rank (already sorted by score descending)
  const sorted = [...STATE.moments].map((x,i)=>({x,i})).sort((a,b)=>a.x.rank-b.x.rank).slice(0, n);
  const fillers = !!(document.getElementById("fillersToggle")?.checked);
  const cropMode = (document.getElementById("cropMode")?.value) || "blur";
  const payload = {
    url: STATE.url || STATE.meta.url || "",
    upload_id: STATE.upload_id,
    quality: "720", caption_style: "hormozi",
    vertical: true, remove_fillers: fillers, crop_mode: cropMode,
    font_size: 0, margin_v: 0,
    clips: sorted.map(({x,i:idx})=>{
      const ed = getEdit(idx);
      return {start:+ed.start, end:+ed.end, caption_text: capTextFor(ed, x), title:ed.title||x.title,
              caption_style:ed.caption_style, quality:ed.quality, vertical:!!ed.vertical,
              crop_mode:ed.crop_mode||cropMode, remove_fillers:fillers,
              font_size:ed.font_size||0, margin_v:ed.margin_v||0};
    })
  };
  try{
    const r = await fetch("/api/clip/batch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    const d = await r.json();
    if(!r.ok) throw new Error(d.error||"Batch export failed");
    // Stitch responses back into STATE.edits
    for(const c of d.clips||[]){
      if(c.error || c.index===undefined) continue;
      const orig = sorted[c.index];
      if(!orig) continue;
      const idx = orig.i;
      const e = getEdit(idx);
      Object.assign(e, {download:c.download, file:c.file, thumbnail:c.thumbnail||"",
                        youtube_url:c.youtube_url||"", fillers_removed:c.fillers_removed||0,
                        duration:c.duration});
    }
    renderMoments();
    autosave();
    $("#batchStatus").innerHTML = `✅ <b>${d.ok}</b> clip${d.ok===1?"":"s"} ready${d.errors?` (${d.errors} failed)`:""} — see below, click ▶ Preview to watch`;
    toast(`✅ Exported ${d.ok} clip${d.ok===1?"":"s"}`);
    // Open first successful clip preview
    const first = (d.clips||[]).find(c=>!c.error);
    if(first && sorted[first.index]) preview(sorted[first.index].i);
  }catch(e){
    $("#batchStatus").textContent = "⚠ " + e.message;
    showError(e.message);
  }finally{
    if(btn){ btn.disabled=false; btn.textContent="✂️ Export top 3 (auto-edited)"; }
  }
}

function recipeHtml(r){
  if(!r) return "";
  const sfxList = (r.sfx||[]).map(s=>`<li><b>${s.type.toUpperCase()}</b> — ${esc(s.note)}</li>`).join("");
  const stepList = (r.steps||[]).map(s=>`<li>${esc(s)}</li>`).join("");
  const fxList = (r.effects||[]).map(f=>`<li>${esc(f)}</li>`).join("");
  const txtList = (r.text_overlays||[]).map(t=>`<li>${esc(t)}</li>`).join("");
  return `<details class="recipe" open>
    <summary><span class="recipe-badge">🎬 EDIT RECIPE</span> <span class="muted">exact SFX, zooms, text overlays, BGM</span></summary>
    <div class="recipe-grid">
      <div class="recipe-col">
        <h4>🎵 BGM</h4><p class="recipe-p">${esc(r.bgm||"")}</p>
        <h4>🔊 SFX timeline</h4><ul class="recipe-list">${sfxList}</ul>
      </div>
      <div class="recipe-col">
        <h4>✏️ Step-by-step cuts</h4><ol class="recipe-list">${stepList}</ol>
      </div>
      <div class="recipe-col">
        <h4>🎨 Visual effects</h4><ul class="recipe-list">${fxList}</ul>
        <h4>💬 On-screen text</h4><ul class="recipe-list">${txtList}</ul>
      </div>
    </div>
  </details>`;
}

/* ---------------------------------------------------------------- wire */
$("#analyzeBtn").onclick = analyze;
$("#demoBtn").onclick = demo;
$("#url").addEventListener("keydown", e=>{ if(e.key==="Enter") analyze(); });
$("#fileInput").onchange = e=>{ if(e.target.files[0]) uploadFile(e.target.files[0]); };
$("#sortBy").onchange = renderMoments;
$("#filterLabel").onchange = renderMoments;
// Discover
renderNicheChips();
$("#discoverBtn").onclick = ()=>doDiscover("", $("#discoverQ").value.trim());
$("#batchExportBtn").onclick = (e)=>batchExportTop(3, e.target);
$("#discoverQ").addEventListener("keydown", e=>{ if(e.key==="Enter") doDiscover("", $("#discoverQ").value.trim()); });
$("#discoverList").innerHTML = `<div class="muted" style="padding:14px">Pick a niche above or type a topic + click 🔍 Find videos to load popular clips from that space.</div>`;
$("#modalClose").onclick = closeModal;
function closeModal(){
  // Pause any playing video/iframe before closing
  const v = $("#modalBody video");
  if(v){ v.pause(); v.removeAttribute("src"); v.load(); }
  // YouTube iframe: set src to '' to stop playback (otherwise audio keeps going)
  const f = $("#modalBody iframe");
  if(f){ f.src = "about:blank"; }
  $("#modal").classList.add("hidden");
  $("#modalBody").innerHTML="";
}
$("#modal").addEventListener("click", e=>{ if(e.target.id==="modal") closeModal(); });
// Close modal on Escape
document.addEventListener("keydown", e=>{ if(e.key==="Escape" && !$("#modal").classList.contains("hidden")) closeModal(); });
$("#saveProjectBtn").onclick = saveProject;
$("#exportLibBtn").onclick = exportLibrary;
$("#importLib").onchange = e=>{ if(e.target.files[0]) importLibrary(e.target.files[0]); };

// Manual cutter — inline quality/style/caption controls since static HTML has no IDs for them
function buildManualControls(){
  const wrap = $("#manualQualityWrap");
  wrap.style.display = "flex";
  wrap.innerHTML = `
    <label>🎨 Captions <select id="mStyle">${styleOpts("hormozi")}</select></label>
    <label>📦 Quality <select id="mQuality">${qualityOpts("720")}</select></label>
    <label class="caplabel" style="flex:1;min-width:220px">Caption text
      <input id="mCaptionText" type="text" placeholder="(auto-uses first transcript text if blank)" style="width:100%;margin-top:4px">
    </label>`;
}
buildManualControls();
$("#manualBtn").onclick = e=>cutClip({
  url: STATE.url || STATE.meta.url || "",
  upload_id: STATE.upload_id,
  start:+$("#mStart").value, end:+$("#mEnd").value,
  vertical:$("#mVertical").checked,
  quality:$("#mQuality")?.value||"720",
  caption_style:$("#mStyle")?.value||"hormozi",
  caption_text:($("#mCaptionText")?.value||"") || (STATE.moments[0]?.transcript||""),
  remove_fillers: !!(document.getElementById("fillersToggle")?.checked),
  crop_mode: (document.getElementById("cropMode")?.value) || "blur"
}, e.target, $("#manualOut"));

(async function init(){
  try{
    const r = await fetch("/api/options");
    if(r.ok){
      const j = await r.json().catch(()=>null);
      if(j) OPTIONS = j;
    }
  }catch(e){}
  await syncLibrary();
  const last = localStorage.getItem("clipppers_session_v1");
  if(last){
    try{
      STATE = JSON.parse(last);
      if(STATE.moments?.length){ render({meta:STATE.meta, source:"last session"}); toast("↩ Restored your last session — all edits intact"); }
    }catch(e){}
  }
})();
