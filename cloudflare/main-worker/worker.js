import { WorkflowEntrypoint, DurableObject } from "cloudflare:workers";


export class WhatsAppControl extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    ctx.blockConcurrencyWhile(async () => {
      ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS mailbox(id INTEGER PRIMARY KEY AUTOINCREMENT,wa_message_id TEXT NOT NULL UNIQUE,wa_from TEXT NOT NULL,message_type TEXT NOT NULL,payload_json TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'QUEUED',created_at INTEGER NOT NULL,started_at INTEGER,completed_at INTEGER,error TEXT)");
      ctx.storage.sql.exec("CREATE INDEX IF NOT EXISTS idx_mailbox_status ON mailbox(status,created_at)");
      ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS state(k TEXT PRIMARY KEY,v TEXT NOT NULL)");
      ctx.storage.sql.exec("INSERT OR IGNORE INTO state(k,v) VALUES('processing','0')");
    });
  }
  async enqueueText(to, waMessageId, text) {
    return this.enqueue(to, waMessageId, "text", { text: String(text || "") });
  }
  async enqueueAudio(to, waMessageId, mediaId, mime) {
    return this.enqueue(to, waMessageId, "audio", { mediaId: String(mediaId || ""), mime: String(mime || "audio/ogg") });
  }
  async enqueue(to, waMessageId, type, payload) {
    const id = String(waMessageId || "");
    if (!id) throw new Error("WhatsApp message id missing");
    const created = Date.now();
    const before = this.ctx.storage.sql.exec("SELECT id,status FROM mailbox WHERE wa_message_id=?", id).toArray()[0];
    if (before) return { ok: true, duplicate: true, id: Number(before.id), status: before.status };
    this.ctx.storage.sql.exec("INSERT INTO mailbox(wa_message_id,wa_from,message_type,payload_json,status,created_at) VALUES(?,?,?,?,?,?)", id, String(to), String(type), JSON.stringify(payload || {}), "QUEUED", created);
    const processing = this.ctx.storage.sql.exec("SELECT v FROM state WHERE k='processing'").toArray()[0]?.v === "1";
    if (!processing) {
      this.ctx.storage.sql.exec("UPDATE state SET v='1' WHERE k='processing'");
      await this.ctx.storage.setAlarm(Date.now() + 1);
    }
    return { ok: true, queued: true, id };
  }
  async status() {
    const rows = this.ctx.storage.sql.exec("SELECT status,COUNT(*) n FROM mailbox GROUP BY status").toArray();
    return { ok: true, rows };
  }
  async alarm() {
    const row = this.ctx.storage.sql.exec("SELECT id,wa_message_id,wa_from,message_type,payload_json FROM mailbox WHERE status='QUEUED' ORDER BY id LIMIT 1").toArray()[0];
    if (!row) {
      this.ctx.storage.sql.exec("UPDATE state SET v='0' WHERE k='processing'");
      return;
    }
    this.ctx.storage.sql.exec("UPDATE mailbox SET status='PROCESSING',started_at=? WHERE id=?", Date.now(), Number(row.id));
    try {
      const p = JSON.parse(String(row.payload_json || "{}"));
      const result = row.message_type === "audio"
        ? await nfProcessAudio(this.env, String(row.wa_from), String(p.mediaId || ""), String(p.mime || "audio/ogg"))
        : await nfProcessText(this.env, String(row.wa_from), String(p.text || ""));
      await nfFinalizeInbound(this.env, String(row.wa_from), result, String(p.text || ""), row.message_type === "audio", String(row.wa_message_id));
      this.ctx.storage.sql.exec("UPDATE mailbox SET status='COMPLETED',completed_at=?,error=NULL WHERE id=?", Date.now(), Number(row.id));
    } catch (e) {
      const err = String(e?.stack || e).slice(0, 1800);
      this.ctx.storage.sql.exec("UPDATE mailbox SET status='FAILED',completed_at=?,error=? WHERE id=?", Date.now(), err, Number(row.id));
      await nfLog(this.env, "ERROR", "WHATSAPP_CONTROL", err);
      try { await nfAlert(this.env, "WhatsApp command process mein issue aya. Error record aur recovery path active hai."); } catch (_) {}
      try { await this.env.DB.prepare("UPDATE whatsapp_messages SET status='ERROR',error=? WHERE wa_message_id=?").bind(err, String(row.wa_message_id)).run(); } catch (_) {}
    }
    const more = this.ctx.storage.sql.exec("SELECT id FROM mailbox WHERE status='QUEUED' ORDER BY id LIMIT 1").toArray()[0];
    if (more) await this.ctx.storage.setAlarm(Date.now() + 1);
    else this.ctx.storage.sql.exec("UPDATE state SET v='0' WHERE k='processing'");
  }
}

const UNIFIED_SYSTEM_PROMPT="You are the autonomous AI Assistant Factory controller and WhatsApp operations agent. You control and reason over the user's YouTube channels and automation system. You have access to supplied live logs, analytics, content state, research results, jobs, recovery state, and operational context. Preserve the user's operational boundaries: never invent facts, never claim an action completed without backend evidence, use fresh research when requested or required, keep production/upload/publish actions within the existing pipeline, and respond in natural Pakistani Urdu unless the task requires English content. Treat this system prompt as authoritative operational policy for both Gemini and Cloudflare AI fallback.";
async function sessionHistory(env,to){try{if(env.ASSISTANT_SESSION){const v=await env.ASSISTANT_SESSION.get("session:"+to);if(v){const x=JSON.parse(v);return Array.isArray(x)?x.slice(-5):[]}}}catch(e){}try{const r=await env.DB.prepare("SELECT direction,text,transcript,created_at FROM whatsapp_messages WHERE wa_from=? ORDER BY id DESC LIMIT 5").bind(to).all();return (r.results||[]).reverse()}catch(e){return []}}
async function saveSession(env,to,item){const next=(await sessionHistory(env,to)).concat([item]).slice(-5);try{if(env.ASSISTANT_SESSION)await env.ASSISTANT_SESSION.put("session:"+to,JSON.stringify(next),{expirationTtl:86400})}catch(e){}return next}
async function tavilyLive(env,q){const r=await fetch('https://api.tavily.com/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:env.TAVILY_API_KEY,query:String(q).slice(0,800),search_depth:'advanced',max_results:6,include_answer:true})});if(!r.ok)throw new Error('Tavily failed '+r.status);return await r.json()}
async function parseIntent(env,text,history){
 const baseHistory=Array.isArray(history)?history.slice(-5):[];
 const prompt="Return only JSON with keys intent,query,content_id,needs_fresh_data. intent must be one of research,script,analytics,upload,chat. User: "+text+"\nConversation context: "+JSON.stringify(baseHistory).slice(-7000);
 if(env.GEMINI_API_KEY){try{const model=NF_GEMINI_MODEL;const r=await fetch("https://generativelanguage.googleapis.com/v1beta/models/"+model+":generateContent?key="+encodeURIComponent(env.GEMINI_API_KEY),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({systemInstruction:{parts:[{text:UNIFIED_SYSTEM_PROMPT}]},contents:[{role:"user",parts:[{text:prompt}]}],generationConfig:{maxOutputTokens:250,responseMimeType:"application/json",thinkingConfig:{thinkingLevel:"low"}}})});if(r.ok){const j=await r.json();const t=j.candidates&&j.candidates[0]&&j.candidates[0].content&&j.candidates[0].content.parts&&j.candidates[0].content.parts.map(x=>x.text||"").join("");if(t)return JSON.parse(t)}}catch(e){}}
 const fallbackPayload=await Promise.all([
   sessionHistory(env,""+String(env.WHATSAPP_ADMIN_TO||"")).catch(()=>baseHistory),
   tavilyLive(env,text).catch(()=>({answer:"",results:[]})),
   (async()=>{try{const [c,l]=await Promise.all([env.DB.prepare("SELECT COUNT(*) AS n FROM content").first(),env.DB.prepare("SELECT level,component,message,created_at FROM system_logs ORDER BY id DESC LIMIT 5").all()]);return {content_count:c?.n||0,recent_logs:l?.results||[]}}catch(e){return {content_count:0,recent_logs:[]}}})()
 ]);
 const rehydrated=Array.isArray(fallbackPayload[0])?fallbackPayload[0].slice(-5):baseHistory;
 const research=fallbackPayload[1]||{answer:"",results:[]};
 const dbState=fallbackPayload[2]||{};
 const messages=[
   {role:"system",content:UNIFIED_SYSTEM_PROMPT},
   {role:"system",content:"LIVE REHYDRATED WHATSAPP CONTEXT (last 5 messages): "+JSON.stringify(rehydrated).slice(-9000)},
   {role:"system",content:"CONCURRENT LIVE INGESTION — TAVILY: "+JSON.stringify(research).slice(0,12000)+"\nD1 STATE: "+JSON.stringify(dbState).slice(0,6000)},
   {role:"user",content:prompt}
 ];
 const a=await env.AI.run("@cf/zai-org/glm-4.7-flash",{messages,max_tokens:250,temperature:0});
 try{return JSON.parse(String(a&&a.response||a&&a.text||"").trim())}catch(e){return {intent:"chat",query:"",content_id:null,needs_fresh_data:false}}
}
async function handleDynamicIntent(env,to,text){const l=String(text).toLowerCase();const actionable=l.includes('script')||l.includes('research')||l.includes('fresh')||l.includes('latest')||l.includes('analytics')||l.includes('analysis')||l.includes('upload')||l.includes('render')||l.includes('topic')||l.includes('status')||l.includes('health')||l.includes('recover')||l.includes('recovery')||l.includes('voice')||l.includes('production')||l.includes('schedule')||l.includes('publish')||l.includes('content');if(!actionable)return null;const h=await sessionHistory(env,to);const it=await parseIntent(env,text,h);await saveSession(env,to,{role:'user',text,at:new Date().toISOString(),intent:it.intent});if(it.intent==='research'){const d=await tavilyLive(env,it.query||text);const src=(d.results||[]).slice(0,5).map((x,i)=>(i+1)+'. '+x.title+' - '+x.url).join('\n');return {reply:('جی سر، live Tavily research complete.\n\n'+String(d.answer||'')+'\n\nSources:\n'+src).slice(0,4000)}}if(it.intent==='script'){const d=await tavilyLive(env,it.query||text);const ev=(d.results||[]).slice(0,6).map((x,i)=>(i+1)+'. '+x.title+' | '+x.url+' | '+String(x.content||'').slice(0,600)).join('\n');const a=await env.AI.run('@cf/zai-org/glm-4.7-flash',{messages:[{role:'system',content:'Write an original natural English YouTube script. Use only supported facts from research. Strong hook and retention.'},{role:'user',content:'Request: '+text+'\nResearch:\n'+ev}],max_tokens:1800,temperature:.55});const s=String(a&&a.response||a&&a.text||'').trim();await saveSession(env,to,{role:'assistant',text:s.slice(0,7000),at:new Date().toISOString(),intent:'script'});return {reply:('جی سر، fresh research ke basis par script تیار ہے.\n\n'+s).slice(0,4096)}}if(it.intent==='analytics'){const r=await env.DB.prepare('SELECT brand_id,platform,content_id,views,likes,comments,watch_time,created_at FROM analytics ORDER BY id DESC LIMIT 10').all().catch(()=>({results:[]}));return {reply:('جی سر, latest analytics:\n'+(r.results||[]).map(x=>JSON.stringify(x)).join('\n')).slice(0,4000)}}if(it.intent==='upload'){const cid=Number(it.content_id||0);const row=cid?await env.DB.prepare('SELECT id,title,status,audio_url FROM content WHERE id=?').bind(cid).first():await env.DB.prepare('SELECT id,title,status,audio_url FROM content WHERE audio_url IS NOT NULL ORDER BY id DESC LIMIT 1').first();if(!row)return {reply:'جی سر، upload ke liye audio-ready content نہیں ملا۔'};if(!row.audio_url)return {reply:'جی سر، audio ابھی موجود نہیں۔'};const out=await resumeExistingContent(env,row.id);return {reply:'جی سر، content #'+row.id+' production pipeline mein resume ہو گیا: '+JSON.stringify(out).slice(0,1600)}}if(it.intent==='chat'||it.intent==='analytics')return null;const c=await getLiveContext(env);const a=await env.AI.run('@cf/zai-org/glm-4.7-flash',{messages:[{role:'system',content:UNIFIED_SYSTEM_PROMPT+' You are also an execution router. For operational questions, report supplied live state only.'},{role:'system',content:'LIVE CONTEXT: '+JSON.stringify(c).slice(0,28000)},{role:'user',content:text}],max_tokens:500,temperature:0});return {reply:String(a&&a.response||a&&a.text||'جی سر، live system context available ہے۔').slice(0,4000)}}

async function queueRecovery(env,contentId,stage,error){try{await env.DB.prepare("INSERT INTO recovery_queue(content_id,failed_stage,error_message,status,next_retry_at) VALUES(?,?,?,?,datetime('now','+5 minutes'))").bind(Number(contentId),String(stage),String(error).slice(0,1800),"PENDING").run();}catch(e){try{await env.DB.prepare("INSERT INTO system_logs(level,component,message) VALUES(?,?,?)").bind("ERROR","RECOVERY_QUEUE",String(e).slice(0,1000)).run()}catch(_){}}}
async function resumeExistingContent(env,contentId){
 let stage="production";
 try{
  const row=await env.DB.prepare("SELECT id,brand_id,platform,content_format,language,title,script,description,tags,audio_url,youtube_video_id,platform_visibility,scheduled_publish_at,status FROM content WHERE id=?").bind(contentId).first();
  if(!row)return{ok:false,error:"Content not found"};
  await nfEnsurePipelineJobs(env,contentId);
  if(row.youtube_video_id||["PRODUCED","SCHEDULED","PUBLISHED","UPLOADED"].includes(String(row.status||"").toUpperCase()))return{ok:true,content_id:Number(contentId),status:"ALREADY_UPLOADED_OR_RENDERED",no_retry:true};
  const title=String(row.title||"").trim(),script=String(row.script||"").trim();
  if(title.length<3||script.length<200){await nfLog(env,"ERROR","RENDER_CONTRACT","Content "+contentId+" rejected because title/script contract is invalid");throw new Error("Render contract invalid: title/script missing or too short")}
  if(!row.audio_url)return{ok:false,error:"No uploaded audio exists for this content"};
  await env.DB.prepare("UPDATE pipeline_jobs SET state='DONE',paused_by_user=0,updated_at=CURRENT_TIMESTAMP WHERE content_id=? AND stage='production_plan'").bind(contentId).run().catch(()=>{});
  await env.DB.prepare("UPDATE content SET status='PRODUCTION_RUNNING' WHERE id=?").bind(contentId).run();
  stage="audio-sign";
  const sign=await nfFetch(env.SUPABASE_URL+"/storage/v1/object/sign/ai-assistant-audio/"+row.audio_url,{method:"POST",headers:{"Authorization":"Bearer "+env.SUPABASE_SERVICE_ROLE_KEY,"apikey":env.SUPABASE_SERVICE_ROLE_KEY,"Content-Type":"application/json"},body:JSON.stringify({expiresIn:3600})},"Audio signing");
  if(!sign.ok)throw new Error("Audio signing failed");
  const sj=await sign.json();const rawSigned=String(sj.signedURL||sj.signedUrl||sj.url||"").trim();if(!rawSigned)throw new Error("Signed audio URL missing");let supaBase=String(env.SUPABASE_URL||"");while(supaBase.endsWith("/"))supaBase=supaBase.slice(0,-1);let audioUrl=rawSigned;if(audioUrl.startsWith("https://")){}else if(audioUrl.startsWith("/storage/v1/"))audioUrl=supaBase+audioUrl;else{while(audioUrl.startsWith("/"))audioUrl=audioUrl.slice(1);if(audioUrl.toLowerCase().startsWith("http://"))throw new Error("Signed audio URL must use HTTPS");audioUrl=supaBase+"/storage/v1/"+audioUrl}let audioParsed;try{audioParsed=new URL(audioUrl)}catch(_){throw new Error("Signed audio URL invalid")}if(audioParsed.protocol!=="https:")throw new Error("Signed audio URL must be HTTPS");
  stage="production-worker";
  const productionRequest=new Request("https://ai-production-worker/produce",{method:"POST",headers:{"Content-Type":"application/json","Authorization":"Bearer "+env.WORKER_AUTH_TOKEN},body:JSON.stringify({content_id:row.id,brand_id:row.brand_id,platform:row.platform,language:row.language||"english",content_format:row.content_format||"LONG_VIDEO",title,script,audio_url:audioUrl})});const pr=env.PRODUCTION?await env.PRODUCTION.fetch(productionRequest):await nfFetch(String(env.NEW_PRODUCTION_WORKER_URL||"").replace(/\/+$/,"")+"/produce",{method:"POST",headers:{"Content-Type":"application/json","Authorization":"Bearer "+env.WORKER_AUTH_TOKEN},body:JSON.stringify({content_id:row.id,brand_id:row.brand_id,platform:row.platform,language:row.language||"english",content_format:row.content_format||"LONG_VIDEO",title,script,audio_url:audioUrl})},"Production Worker");
  const ptxt=await pr.text().catch(()=>"");let pd={};try{pd=JSON.parse(ptxt)}catch(_){}if(!pr.ok||pd.status!=="production_ready")throw new Error("Production Worker failed (HTTP "+pr.status+", content-type "+String(pr.headers.get("content-type")||"unknown")+"): "+(ptxt||JSON.stringify(pd)).slice(0,800));
  stage="github-render";
  const startedAt=new Date().toISOString();
  const rawPublishAt=String(row.scheduled_publish_at||"").trim();const publishAt=rawPublishAt&&/(?:Z|[+-]\d{2}:\d{2})$/.test(rawPublishAt)&&Number.isFinite(Date.parse(rawPublishAt))?new Date(rawPublishAt).toISOString():"";const payload={ref:"main",inputs:{content_id:String(row.id),audio_url:String(audioUrl),title,script,description:String(row.description||""),tags:String(row.tags||""),publish_at:publishAt,content_format:String(row.content_format||"LONG_VIDEO")}};
  const gh=await nfFetch("https://api.github.com/repos/"+(env.GITHUB_OWNER||"hamarketers05")+"/"+(env.GITHUB_REPO||"ai-assistant-renderer")+"/actions/workflows/"+(env.GITHUB_WORKFLOW||"manual.yml")+"/dispatches",{method:"POST",headers:{"Authorization":"Bearer "+env.GITHUB_TOKEN,"Accept":"application/vnd.github+json","User-Agent":"AI-Assistant-Factory","X-GitHub-Api-Version":"2022-11-28","Content-Type":"application/json"},body:JSON.stringify(payload)},"GitHub render trigger");
  if(!gh.ok)throw new Error("GitHub render trigger failed: "+(await gh.text()).slice(0,900));
  await env.DB.prepare("UPDATE content SET status='RENDERING' WHERE id=? AND youtube_video_id IS NULL").bind(contentId).run();
  await env.DB.prepare("UPDATE pipeline_jobs SET state='RUNNING',started_at=?,updated_at=CURRENT_TIMESTAMP,attempt=attempt+1,github_run_id=NULL,last_error=NULL,paused_by_user=0 WHERE content_id=? AND stage='render'").bind(startedAt,contentId).run().catch(()=>{});
  await env.DB.prepare("UPDATE pipeline_jobs SET state='PENDING',updated_at=CURRENT_TIMESTAMP WHERE content_id=? AND stage IN ('qa','approval','upload') AND state<>'DONE'").bind(contentId).run().catch(()=>{});
  try{const list=await nfFetch("https://api.github.com/repos/"+(env.GITHUB_OWNER||"hamarketers05")+"/"+(env.GITHUB_REPO||"ai-assistant-renderer")+"/actions/runs?event=workflow_dispatch&per_page=10",{headers:{"Authorization":"Bearer "+env.GITHUB_TOKEN,"Accept":"application/vnd.github+json","User-Agent":"AI-Assistant-Factory","X-GitHub-Api-Version":"2022-11-28"}}, "GitHub run id lookup");if(list.ok){const j=await list.json(),runs=(j.workflow_runs||[]).filter(x=>String(x.name||"").includes("AI Assistant Renderer")&&Date.parse(String(x.created_at||""))>=Date.parse(startedAt)-10000);if(runs.length===1)await env.DB.prepare("UPDATE pipeline_jobs SET github_run_id=? WHERE content_id=? AND stage='render'").bind(String(runs[0].id),contentId).run().catch(()=>{})}}catch(e){await nfLog(env,"WARN","GITHUB_RUN_DISCOVERY",String(e?.message||e).slice(0,180))}
  await env.DB.prepare("INSERT INTO system_logs(level,component,message) VALUES(?,?,?)").bind("INFO","PRODUCTION_RESUME","Content "+contentId+" render dispatched to GitHub; original voice and production manifest validated.").run();
  return{ok:true,content_id:contentId,status:"RENDERING",render:"github-dispatched"};
 }catch(e){await queueRecovery(env,contentId,stage,e?.stack||e);throw e}
}

async function sendWhatsAppAudio(env,to,text){
 const v=env.WHATSAPP_GRAPH_VERSION||"v26.0";
 const audio=await env.AI.run("@cf/myshell-ai/melotts",{prompt:String(text).slice(0,3500),lang:"ur"});
 const blob=audio instanceof Blob?audio:new Blob([audio],{type:"audio/mpeg"});
 const form=new FormData();
 form.append("messaging_product","whatsapp");
 form.append("file",blob,"reply.mp3");
 form.append("type","audio/mpeg");
 const up=await fetch("https://graph.facebook.com/"+v+"/"+env.WHATSAPP_PHONE_NUMBER_ID+"/media",{method:"POST",headers:{Authorization:"Bearer "+env.WHATSAPP_ACCESS_TOKEN},body:form});
 const ud=await up.json().catch(()=>({}));
 if(!up.ok||!ud.id)throw new Error("WhatsApp media upload failed: "+JSON.stringify(ud).slice(0,700));
 const sr=await fetch("https://graph.facebook.com/"+v+"/"+env.WHATSAPP_PHONE_NUMBER_ID+"/messages",{method:"POST",headers:{Authorization:"Bearer "+env.WHATSAPP_ACCESS_TOKEN,"Content-Type":"application/json"},body:JSON.stringify({messaging_product:"whatsapp",to:String(to),type:"audio",audio:{id:String(ud.id)}})});
 if(!sr.ok)throw new Error("WhatsApp audio send failed: "+(await sr.text()).slice(0,700));
 return ud.id;
}

async function getLiveContext(env){const q=async(sql)=>{try{const r=await env.DB.prepare(sql).all();return r.results||[]}catch(e){return []}};const latest=await q("SELECT id,brand_id,platform,title,status,audio_status FROM content ORDER BY id DESC LIMIT 8");const pending=await q("SELECT id,brand_id,platform,title,status,audio_status FROM content WHERE status='WAITING_FOR_VOICE' ORDER BY id DESC LIMIT 8");const errs=await q("SELECT level,component,message,created_at FROM system_logs WHERE level IN ('ERROR','WARN') ORDER BY id DESC LIMIT 10");const jobs=await q("SELECT id,brand_id,status,created_at FROM jobs ORDER BY id DESC LIMIT 10");const rec=await q("SELECT id,content_id,status,retry_count,last_error,next_retry_at FROM recovery_queue ORDER BY id DESC LIMIT 10");return {now:new Date().toISOString(),latest,pending_voice:pending,errors:errs,jobs,recovery:rec};}

/* MAIN_AI_OPERATOR_V4 */
const BOT_ACTIONS_V4=["daily_run","research","next_topic","status","latest_content","voice_status","send_script","resume_content","upload","analytics","fix_error","auto_recover","connections","schedule_get","schedule_set","pending","delete_blocked","confirm_yes","confirm_no","chat"];
const BOT_CONFIRM_V4=new Set(["daily_run","resume_content","upload","auto_recover","schedule_set"]);
const BOT_BANNED_V4=["kripya","samay","anusar","dhanyavaad","avashyak","pratiksha","sahayata"];
const SYSTEM_INSTRUCTION_V4="You are the WhatsApp intent assistant for a real AI Assistant Factory. Speak Pakistani everyday Roman Urdu with natural English. Never invent facts. Never expose IDs, database fields, technical status names, provider names, secrets, or internal URLs. Worker code decides execution and confirmation; AI only classifies intent and naturalizes supplied facts. user_gave_order is true only for an actual order, not a question. Script sending uses exact D1 script. Forbidden Hindi: kripya, samay, anusar, dhanyavaad, avashyak, pratiksha, sahayata. Use: meherbani, waqt, mutabiq, shukriya, zaroori, intezar, madad. Return only JSON. Examples: script bhejo=>send_script/true; send it=>send_script/true; daily run ka status kya hai?=>status/false; daily run chala do=>daily_run/true; AI news pe research karo=>research topic AI news/true; video delete kar do=>delete_blocked/true.";
const BOT_SCHEMA_V4={type:"object",additionalProperties:false,properties:{reply:{type:"string"},action:{type:"string",enum:BOT_ACTIONS_V4},params:{type:"object",additionalProperties:false,properties:{topic:{type:"string"},which:{type:"string",enum:["latest","first","by_title"]},title_hint:{type:"string"},time:{type:"string",pattern:"^([01]\\d|2[0-3]):[0-5]\\d$"}}},user_gave_order:{type:"boolean"}},required:["reply","action","params","user_gave_order"]};
const botKV4=e=>e.SESSIONS||e.ASSISTANT_SESSION||null;
async function botLog4(e,l,c,m){try{await e.DB.prepare("INSERT INTO system_logs(level,component,message,created_at) VALUES(?,?,?,CURRENT_TIMESTAMP)").bind(l,c,String(m).slice(0,1500)).run()}catch(_){}}
async function botTimeout4(fn){const c=new AbortController(),t=setTimeout(()=>c.abort(),8000);try{return await fn(c.signal)}finally{clearTimeout(t)}}
async function botCircuit4(e,ok){const k=botKV4(e);if(!k)return false;try{if(ok){a --- TRUNCATED --- 753,875 chars