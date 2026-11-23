import { raDecToHipsTile } from "./healpix.mjs";
const API = "https://open-sky-timelens-api.vercel.app";
const $ = (id) => document.getElementById(id);
const BLANK = new Set([50, 51]);
const PRESETS = { field:[127.69444,-39.1776], wise0855:[133.795,-7.245], barnard:[269.452,4.693], epsilonindi:[330.84,-56.786] };
const state = { query:null, tile:null, wavelengths:null, frames:{A:null,B:null}, mode:"blink", showB:false, playing:false, timer:null, rate:1.5, swipe:50, token:0, reduced:window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false };

const setText=(id,value)=>$(id).textContent=value;
const finite=(v)=>v!==null && v!==undefined && v!=="" && Number.isFinite(Number(v));
const channelLabel=(i)=>"CH "+String(i+1).padStart(3,"0");
const wavelength=(i)=>finite(state.wavelengths?.[i])?Number(state.wavelengths[i]).toFixed(3)+" μm":"Wavelength unavailable";
function status(id,stateName,label){const el=$(id);el.dataset.state=stateName;el.querySelector("span").textContent=label;}
function notice(message){const el=$("frame-error");el.textContent=message||"";el.classList.toggle("hidden",!message);}
async function api(path,options={},timeout=60000){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
 try{
  const response=await fetch(API+path,{...options,signal:controller.signal,headers:{Accept:"application/json",...(options.headers||{})}});
  if(!response.ok){let message="HTTP "+response.status;try{const body=await response.json();message=body.detail||body.error||message;}catch{}const error=new Error(message);error.status=response.status;throw error;}
  return response;
 }catch(e){if(e.name==="AbortError")throw new Error("Request timed out. Try a smaller search radius.");throw e;}
 finally{clearTimeout(timer);}
}
function release(frame){if(frame?.url)URL.revokeObjectURL(frame.url);}
function updateLabels(){
 for(const slot of ["A","B"]){const key=slot.toLowerCase(),i=Number($("channel-"+key).value);
  setText("channel-"+key+"-label",channelLabel(i));setText("wave-"+key,wavelength(i));
  if(state.frames[slot]?.channel!==i)setText("channel-"+key+"-status","Channel changed · load frame to refresh");
 }
 updateCaption();
}
function updateCaption(){
 const a=Number($("channel-a").value),b=Number($("channel-b").value);
 const mode=state.mode==="diff"?"B − A · display values":state.mode==="side"?"A / B · side by side":state.mode==="swipe"?"A / B · swipe":"Blink · "+(state.showB?"Frame B":"Frame A");
 setText("comparison-caption",mode+" · "+channelLabel(a)+" ("+wavelength(a)+") / "+channelLabel(b)+" ("+wavelength(b)+")");
}
function clearFrames(){
 release(state.frames.A);release(state.frames.B);state.frames={A:null,B:null};state.showB=false;
 $("image-a").removeAttribute("src");$("image-b").removeAttribute("src");renderStage();
}
function drawDifference(){
 const a=state.frames.A?.pixels,b=state.frames.B?.pixels,canvas=$("difference-canvas"),ctx=canvas.getContext("2d");
 if(!a||!b||a.width!==b.width||a.height!==b.height){ctx.clearRect(0,0,canvas.width,canvas.height);return;}
 canvas.width=a.width;canvas.height=a.height;const out=ctx.createImageData(a.width,a.height);
 for(let i=0;i<a.data.length;i+=4){
  if(!a.data[i+3]||!b.data[i+3]){out.data[i+3]=0;continue;}
  const la=.299*a.data[i]+.587*a.data[i+1]+.114*a.data[i+2],lb=.299*b.data[i]+.587*b.data[i+1]+.114*b.data[i+2],d=lb-la,t=Math.min(1,Math.abs(d)*2.5/255);
  if(d>=0){out.data[i]=224*t+12*(1-t);out.data[i+1]=42*t+18*(1-t);out.data[i+2]=192*t+28*(1-t);}
  else{out.data[i]=35*t+12*(1-t);out.data[i+1]=205*t+18*(1-t);out.data[i+2]=115*t+28*(1-t);}
  out.data[i+3]=255;
 }
 ctx.putImageData(out,0,0);
}
function renderStage(){
 const stage=$("frame-stage");stage.classList.remove("mode-blink","mode-swipe","mode-side","mode-diff","show-b","has-a","has-b");
 stage.classList.add("mode-"+state.mode);if(state.showB)stage.classList.add("show-b");
 if(state.frames.A)stage.classList.add("has-a");if(state.frames.B)stage.classList.add("has-b");
 $("frame-empty").classList.toggle("hidden",Boolean(state.frames.A||state.frames.B));
 $("layer-b").style.clipPath=state.mode==="swipe"?"inset(0 0 0 "+state.swipe+"%)":"none";
 $("difference-canvas").style.display=state.mode==="diff"&&state.frames.A&&state.frames.B?"block":"none";
 $("swipe-control").classList.toggle("hidden",state.mode!=="swipe");
 $("difference-note").classList.toggle("hidden",state.mode!=="diff");
 $("blink-button").classList.toggle("hidden",state.mode!=="blink");
 if(state.mode==="diff")drawDifference();updateCaption();
}
function stopBlink(){if(state.timer!==null)clearInterval(state.timer);state.timer=null;state.playing=false;$("blink-button").textContent="Play blink";}
function setMode(mode){
 if(!["blink","swipe","side","diff"].includes(mode))return;state.mode=mode;stopBlink();
 document.querySelectorAll(".mode-button").forEach(b=>{const active=b.dataset.mode===mode;b.classList.toggle("is-active",active);b.setAttribute("aria-pressed",String(active));});
 renderStage();
}
function toggleBlink(){
 if(state.mode!=="blink")setMode("blink");
 if(state.playing){stopBlink();return;}
 if(!state.frames.A||!state.frames.B){notice("Load both archive frames before starting blink comparison.");return;}
 if(state.reduced){state.showB=!state.showB;renderStage();notice("Automatic blinking is disabled by the reduced-motion preference. Press again to switch frames.");return;}
 notice("");state.playing=true;$("blink-button").textContent="Pause blink";
 state.timer=setInterval(()=>{state.showB=!state.showB;renderStage();},1000/Math.min(3,Math.max(1,state.rate)));
}
async function loadFrame(slot,token=state.token){
 if(state.tile===null){notice("Load a field before requesting a frame.");return;}
 const key=slot.toLowerCase(),channel=Number($("channel-"+key).value);
 setText("channel-"+key+"-status","Requesting official IRSA frame…");status("viewer-status","loading","LOADING FRAME "+slot);notice("");
 try{
  const response=await api("/api/v1/hips/frame/"+state.tile+"/"+channel,{},30000);
  if(!response.headers.get("content-type")?.toLowerCase().includes("image/png"))throw new Error("IRSA did not return a PNG frame.");
  const bitmap=await createImageBitmap(await response.blob()),canvas=document.createElement("canvas");
  canvas.width=bitmap.width;canvas.height=bitmap.height;
  const ctx=canvas.getContext("2d",{willReadFrequently:true});if(!ctx)throw new Error("Canvas pixel access is unavailable.");
  ctx.drawImage(bitmap,0,0);bitmap.close();
  const pixels=ctx.getImageData(0,0,canvas.width,canvas.height),blob=await new Promise((resolve,reject)=>canvas.toBlob(v=>v?resolve(v):reject(new Error("Could not prepare the archive frame.")),"image/png"));
  const url=URL.createObjectURL(blob);if(token!==state.token){URL.revokeObjectURL(url);return;}
  release(state.frames[slot]);state.frames[slot]={channel,url,pixels};
  const image=$("image-"+key);image.src=url;image.alt="NASA/IPAC IRSA SPHEREx HiPS channel "+(channel+1)+", "+wavelength(channel)+", tile "+state.tile;
  setText("label-"+key,"FRAME "+slot+" · "+channelLabel(channel)+" · "+wavelength(channel));
  setText("channel-"+key+"-status",pixels.width+" × "+pixels.height+" PNG · display only");
  setText("prov-preview","Official IRSA HiPS PNG");setText("stage-tile","NORDER 5 / NPIX "+state.tile);setText("prov-science","Not performed");
  renderStage();const both=Boolean(state.frames.A&&state.frames.B);
  status("viewer-status",both?"ready":"loading",both?"BOTH FRAMES LOADED":"FRAME "+slot+" LOADED");$("blink-button").disabled=!both;
 }catch(error){
  if(token!==state.token)return;
  const blank=BLANK.has(channel)&&error.status===404;
  const message=blank?"Known blank dichroic channel "+(channel+1)+"; IRSA publishes no frame for this position.":error.status===404?"IRSA does not publish this HiPS frame for channel "+(channel+1)+" at this tile.":error.message;
  setText("channel-"+key+"-status",message);notice("Frame "+slot+": "+message+" No substitute image was used.");
  status("viewer-status","error","FRAME "+slot+" UNAVAILABLE");$("blink-button").disabled=true;
 }
}
function validateQuery(){
 const ra=Number($("ra").value),dec=Number($("dec").value),radius=Number($("radius").value);
 if(!Number.isFinite(ra)||ra<0||ra>=360)throw new Error("RA must be from 0 to less than 360 degrees.");
 if(!Number.isFinite(dec)||dec< -90||dec>90)throw new Error("Dec must be between −90 and +90 degrees.");
 if(!Number.isFinite(radius)||radius<=0||radius>1800)throw new Error("Search radius must be positive and no more than 1,800 arcseconds.");
 return{ra_deg:ra,dec_deg:dec,radius_arcsec:radius};
}
function emptyBox(message){const e=document.createElement("div");e.className="record-empty";e.textContent=message;return e;}
function chartEmpty(title,subtitle){
 const box=document.createElement("div");box.className="chart-empty";
 for(const [tag,value] of [["span","TIME-DOMAIN MEASUREMENTS"],["strong",title],["small",subtitle]]){const el=document.createElement(tag);el.textContent=value;box.append(el);}
 return box;
}
function clearResults(){
 setText("cube-count","Searching…");setText("sia-count","Searching…");setText("records-summary","Archive requests running");
 $("cube-products").replaceChildren(emptyBox("Contacting NASA/IPAC IRSA…"));$("sia-records").replaceChildren(emptyBox("Contacting NASA/IPAC IRSA…"));
 setText("prov-fits","Checking archive");setText("prov-preview","Requesting frames");setText("prov-science","Not performed");
 $("neowise-button").disabled=true;$("neowise-rows").replaceChildren();
 const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=5;td.className="table-empty";td.textContent="Run the separate NEOWISE-R query to retrieve dated measurements.";tr.append(td);$("neowise-rows").append(tr);
 setText("neowise-summary","No measurements loaded");$("light-curve").replaceChildren(chartEmpty("Waiting for measurements","NEOWISE-R is queried separately from the SPHEREx cube."));$("light-curve-legend").classList.add("hidden");
}
async function loadMetadata(){
 const response=await api("/api/v1/hips/metadata",{},25000),payload=await response.json();
 if(!Array.isArray(payload.wavelength_um)||payload.wavelength_um.length!==102||payload.wavelength_um.some(v=>!Number.isFinite(Number(v))))throw new Error("IRSA did not return 102 finite wavelengths.");
 state.wavelengths=payload.wavelength_um.map(Number);updateLabels();
}
async function loadField(event){
 event?.preventDefault();let q;
 try{q=validateQuery();}catch(e){notice(e.message);$("ra").focus();return;}
 stopBlink();clearFrames();const token=++state.token;state.query=q;state.tile=raDecToHipsTile(q.ra_deg,q.dec_deg);
 notice("");status("viewer-status","loading","QUERYING NASA/IPAC IRSA");
 setText("tile-value",state.tile+" · NORDER 5");setText("stage-tile","NORDER 5 / NPIX "+state.tile);
 setText("viewer-coordinates","RA "+q.ra_deg.toFixed(5)+"° · Dec "+q.dec_deg.toFixed(5)+"° · "+q.radius_arcsec.toFixed(0)+"″");
 ["channel-a","channel-b","load-a","load-b","swap-channels","reset-channels"].forEach(id=>$(id).disabled=false);clearResults();
 const params=new URLSearchParams({ra_deg:String(q.ra_deg),dec_deg:String(q.dec_deg),radius_arcsec:String(q.radius_arcsec)});
 const archiveRequests=Promise.allSettled([
  api("/api/v1/cube/search?"+params).then(r=>r.json()),
  api("/api/v1/search",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...q,collections:["spherex_dr1","spherex_qr3"]})}).then(r=>r.json())
 ]);
 try{if(!state.wavelengths)await loadMetadata();updateLabels();}catch(e){notice("Wavelength metadata unavailable: "+e.message);}
 const frameRequests=Promise.allSettled([loadFrame("A",token),loadFrame("B",token)]);
 const [cube,sia]=await archiveRequests;if(token!==state.token)return;
 if(cube.status==="fulfilled")renderCubeProducts(cube.value.products||[]);
 else{setText("cube-count","Unavailable");$("cube-products").replaceChildren(emptyBox("DR1 cube discovery failed: "+cube.reason.message));setText("prov-fits","Discovery unavailable");}
 if(sia.status==="fulfilled")renderSiaRecords(sia.value.observations||[]);
 else{setText("sia-count","Unavailable");$("sia-records").replaceChildren(emptyBox("SPHEREx SIA2 search failed: "+sia.reason.message));}
 setText("records-summary","Archive responses · NASA/IPAC IRSA");$("neowise-button").disabled=false;
 await frameRequests;if(token!==state.token)return;
 if(state.frames.A&&state.frames.B){status("viewer-status","ready","ARCHIVE FRAMES READY");setText("prov-preview","Official IRSA HiPS PNG · display only");}
 else if(state.frames.A||state.frames.B)status("viewer-status","error","PARTIAL FRAME LOAD");
}
function renderCubeProducts(products){
 setText("cube-count",products.length+" product"+(products.length===1?"":"s"));$("cube-products").replaceChildren();
 if(!products.length){$("cube-products").append(emptyBox("IRSA returned no DR1 All-Sky Cube FITS product for this search. The all-sky HiPS preview is reported separately."));setText("prov-fits","No product returned");return;}
 setText("prov-fits","Discovered · not validated");
 products.slice(0,8).forEach(p=>{
  const card=document.createElement("article"),details=document.createElement("div");card.className="record-card";
  const title=document.createElement("strong"),meta=document.createElement("small");
  title.textContent=p.observation_id||"SPHEREx DR1 All-Sky Cube";meta.textContent=(p.collection||"spherex_dr1_cube")+" · "+(p.data_product_type||"FITS product")+" · NASA/IPAC IRSA";
  details.append(title,meta);card.append(details);
  if(typeof p.access_url==="string"&&p.access_url.startsWith("https://irsa.ipac.caltech.edu/")){const link=document.createElement("a");link.href=p.access_url;link.target="_blank";link.rel="noopener noreferrer";link.textContent="OPEN FITS ↗";card.append(link);}
  $("cube-products").append(card);
 });
 const note=document.createElement("p");note.className="field-hint";note.textContent="A returned product record confirms discovery only. The FITS file has not been downloaded or scientifically validated in this view.";$("cube-products").append(note);
}
function mjdDate(value){if(!finite(value))return"date unavailable";const d=new Date((Number(value)-40587)*86400000);return Number.isNaN(d.getTime())?"date unavailable":d.toISOString().slice(0,10);}
function renderSiaRecords(items){
 setText("sia-count",items.length+" record"+(items.length===1?"":"s"));$("sia-records").replaceChildren();
 if(!items.length){$("sia-records").append(emptyBox("IRSA returned no SPHEREx spectral-image records for this position."));return;}
 items.slice(0,12).forEach(item=>{
  const card=document.createElement("article"),details=document.createElement("div");card.className="record-card";
  const title=document.createElement("strong"),meta=document.createElement("small");title.textContent=item.observation_id||"SPHEREx observation";
  const date=finite(item.observation_start_mjd)?"MJD "+Number(item.observation_start_mjd).toFixed(2)+" · "+mjdDate(item.observation_start_mjd):"Observation date not supplied";
  const band=item.bandpass_name||item.data_product_type||"spectral image",range=finite(item.wavelength_min)&&finite(item.wavelength_max)?" · "+item.wavelength_min+"–"+item.wavelength_max+" μm":"";
  meta.textContent=(item.collection||"SPHEREx")+" · "+band+range+" · "+date;details.append(title,meta);card.append(details);
  if(typeof item.access_url==="string"&&item.access_url.startsWith("https://irsa.ipac.caltech.edu/")){const link=document.createElement("a");link.href=item.access_url;link.target="_blank";link.rel="noopener noreferrer";link.textContent="OPEN ↗";card.append(link);}
  $("sia-records").append(card);
 });
}
function svgElement(name,attrs={}){const el=document.createElementNS("http://www.w3.org/2000/svg",name);Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,String(v)));return el;}
function renderMeasurements(detections){
 const rows=detections.filter(r=>finite(r.mjd)).sort((a,b)=>Number(a.mjd)-Number(b.mjd)),w1=rows.filter(r=>finite(r.w1_mag)),w2=rows.filter(r=>finite(r.w2_mag));
 const values=[...w1.map(r=>Number(r.w1_mag)),...w2.map(r=>Number(r.w2_mag))];$("light-curve").replaceChildren();
 if(!rows.length||!values.length){
  $("light-curve").append(chartEmpty("No W1/W2 measurements returned","The query returned no usable dated band magnitudes."));$("light-curve-legend").classList.add("hidden");
  setText("neowise-summary",rows.length+" dated rows · no usable W1/W2 magnitudes");
 }else{
  const width=800,height=245,left=60,right=18,top=18,bottom=38,pw=width-left-right,ph=height-top-bottom;
  const mjds=rows.map(r=>Number(r.mjd)),minM=Math.min(...mjds),maxM=Math.max(...mjds),minV=Math.min(...values),maxV=Math.max(...values),span=Math.max(maxV-minV,.2);
  const x=v=>left+((Number(v)-minM)/Math.max(maxM-minM,1))*pw,y=v=>top+((Number(v)-(minV-.12*span))/(1.24*span))*ph;
  const chart=svgElement("svg",{viewBox:"0 0 800 245",role:"img","aria-label":"NEOWISE-R nearby single-exposure measurements plotted by MJD. Points are not connected because source association is not performed."});
  const title=svgElement("title");title.textContent="NEOWISE-R dated measurements by MJD · source association not performed";chart.append(title);
  for(let i=0;i<=4;i++){
   const yy=top+ph*i/4;chart.append(svgElement("line",{x1:left,x2:width-right,y1:yy,y2:yy,stroke:"#243849","stroke-width":1}));
   const label=svgElement("text",{x:left-9,y:yy+3,fill:"#91a6b7","font-size":9,"text-anchor":"end"});label.textContent=(minV-.12*span+1.24*span*i/4).toFixed(2);chart.append(label);
  }
  chart.append(svgElement("line",{x1:left,x2:width-right,y1:height-bottom,y2:height-bottom,stroke:"#6b8498"}));
  const xl=svgElement("text",{x:width/2,y:height-8,fill:"#91a6b7","font-size":10,"text-anchor":"middle"});xl.textContent="Modified Julian Date (MJD)";
  const yl=svgElement("text",{x:13,y:height/2,fill:"#91a6b7","font-size":10,transform:"rotate(-90 13 "+height/2+")","text-anchor":"middle"});yl.textContent="Magnitude";chart.append(xl,yl);
  for(const [band,series,color] of [["W1",w1,"#79e7df"],["W2",w2,"#b7a8ff"]]){
   series.forEach(row=>{const mag=Number(row[band.toLowerCase()+"_mag"]),point=svgElement("circle",{cx:x(row.mjd),cy:y(mag),r:3.1,fill:color,stroke:"#07111c","stroke-width":1});
    const tip=svgElement("title");tip.textContent=band+" "+mag.toFixed(3)+" mag · MJD "+row.mjd+" · quality "+(row.photometric_quality||"not supplied")+" · scan "+(row.scan_id??"—")+" / frame "+(row.frame_num??"—");point.append(tip);chart.append(point);});
  }
  $("light-curve").append(chart);$("light-curve-legend").classList.remove("hidden");
  setText("neowise-summary",rows.length+" nearby single-exposure rows · W1: "+w1.length+" · W2: "+w2.length+" · span: "+(maxM-minM).toFixed(1)+" days · sources not cross-matched");
 }
 const body=$("neowise-rows");body.replaceChildren();
 if(!rows.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=5;td.className="table-empty";td.textContent="No dated NEOWISE-R rows returned.";tr.append(td);body.append(tr);}
 else{
  rows.slice(0,100).forEach(r=>{const tr=document.createElement("tr"),cells=[Number(r.mjd).toFixed(3)+" / "+mjdDate(r.mjd),finite(r.w1_mag)?Number(r.w1_mag).toFixed(3):"—",finite(r.w2_mag)?Number(r.w2_mag).toFixed(3):"—",r.photometric_quality||r.frame_quality||"—",(r.scan_id??"—")+" / "+(r.frame_num??"—")];
   cells.forEach(v=>{const td=document.createElement("td");td.textContent=String(v);tr.append(td);});body.append(tr);});
  if(rows.length>100){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=5;td.className="table-empty";td.textContent="Showing first 100 of "+rows.length+" rows.";tr.append(td);body.append(tr);}
 }
}
async function queryNeowise(){
 if(!state.query)return;$("neowise-button").disabled=true;$("neowise-button").textContent="Querying…";
 $("light-curve").replaceChildren(chartEmpty("Querying NASA/IPAC IRSA","Retrieving dated NEOWISE-R catalog rows."));
 try{
  const q=new URLSearchParams({ra_deg:String(state.query.ra_deg),dec_deg:String(state.query.dec_deg),radius_arcsec:String(Math.min(state.query.radius_arcsec,120)),limit:"200"});
  const response=await api("/api/v1/neowise/search?"+q,{},90000),payload=await response.json();renderMeasurements(payload.detections||[]);
  text("neowise-note",payload.notice||"Nearby NEOWISE-R single-exposure rows may include artifacts. Source association is not performed; review quality fields before interpretation.");
 }catch(e){$("light-curve").replaceChildren(chartEmpty("NEOWISE-R request failed",e.message));text("neowise-summary","No measurements loaded");}
 finally{$("neowise-button").disabled=false;$("neowise-button").textContent="Query NEOWISE ↗";}
}
function wire(){
 $("search-form").addEventListener("submit",loadField);
 $("target-preset").addEventListener("change",e=>{const p=PRESETS[e.target.value];if(p){$("ra").value=p[0];$("dec").value=p[1];}});
 document.querySelectorAll(".mode-button").forEach(b=>b.addEventListener("click",()=>setMode(b.dataset.mode)));
 $("channel-a").addEventListener("input",updateLabels);$("channel-b").addEventListener("input",updateLabels);
 $("channel-a").addEventListener("change",()=>state.tile!==null&&loadFrame("A"));$("channel-b").addEventListener("change",()=>state.tile!==null&&loadFrame("B"));
 $("load-a").addEventListener("click",()=>loadFrame("A"));$("load-b").addEventListener("click",()=>loadFrame("B"));
 $("swap-channels").addEventListener("click",()=>{const a=$("channel-a").value;$("channel-a").value=$("channel-b").value;$("channel-b").value=a;updateLabels();if(state.tile!==null){loadFrame("A");loadFrame("B");}});
 $("reset-channels").addEventListener("click",()=>{$("channel-a").value="10";$("channel-b").value="90";updateLabels();if(state.tile!==null){loadFrame("A");loadFrame("B");}});
 $("blink-button").addEventListener("click",toggleBlink);
 $("blink-rate").addEventListener("input",e=>{state.rate=Number(e.target.value);text("blink-rate-value",state.rate.toFixed(1)+"/s");if(state.playing){stopBlink();toggleBlink();}});
 $("swipe-range").addEventListener("input",e=>{state.swipe=Number(e.target.value);$("layer-b").style.clipPath="inset(0 0 0 "+state.swipe+"%)";text("swipe-value",state.swipe+"%");});
 $("neowise-button").addEventListener("click",queryNeowise);
 $("frame-stage").addEventListener("keydown",e=>{if(e.target!==$("frame-stage")||e.ctrlKey||e.metaKey||e.altKey)return;
  if(["1","2","3","4"].includes(e.key)){setMode(["blink","swipe","side","diff"][Number(e.key)-1]);e.preventDefault();}
  else if(e.key.toLowerCase()==="x"){$("swap-channels").click();e.preventDefault();}
  else if(e.key===" "&&state.mode==="blink"&&state.frames.A&&state.frames.B){state.showB=!state.showB;renderStage();e.preventDefault();}
 });
}
async function init(){
 wire();status("api-status","checking","CHECKING API");
 try{const response=await api("/api/v1/health",{},12000),health=await response.json();if(health.status!=="ok")throw new Error("Unexpected health response");status("api-status","online","API ONLINE");}
 catch(e){status("api-status","offline","API OFFLINE");status("viewer-status","error","API NOT CONNECTED");notice("TimeLens API health check failed: "+e.message+". Live archive data cannot be loaded.");}
 try{await loadMetadata();}catch(e){text("prov-preview","Wavelength metadata unavailable");notice("IRSA wavelength metadata could not be loaded: "+e.message);}
 renderStage();
}
init();
