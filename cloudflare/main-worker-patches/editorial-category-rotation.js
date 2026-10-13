// Source fragment for the category-rotation functions deployed in the full live Worker bundle.
// This file is NOT a standalone Worker. Do not deploy it as a replacement for cloudflare/main-worker/worker.js.
// Integration points: nfResearchTopic, nfGenerateScript, /research, and the read-only /editorial/* self-test routes.

const NF_EDITORIAL_CATEGORIES = [
{name:"AI News & Breakthroughs",brief:"Verified launches, model changes, research breakthroughs, and what they actually change.",keywords:["announces","launches","released","new model","breakthrough","openai","anthropic","gemini","claude","deepseek","gpt-5","llama","model update"]},
{name:"AI Tools & Practical Workflows",brief:"Useful AI tools, real workflow demos, and clear before/after value without invented testing.",keywords:["ai tool","tool review","workflow","how to","productivity","copilot","coding tool","app launch","image generator","video generator"]},
{name:"AI Agents & Automation",brief:"AI agents, computer-use systems, autonomous task execution, and real automation trade-offs.",keywords:["ai agent","agents","agentic","autonomous task","computer use","multi-agent","automation agent","agent framework"]},
{name:"Robotics & Physical AI",brief:"Robots, humanoids, autonomous machines, physical AI, and what they can demonstrably do.",keywords:["robot","robotics","humanoid","physical ai","self-driving","autonomous vehicle","robot arm","factory robot"]},
{name:"AI, Jobs & Business",brief:"Work, careers, companies, enterprise deployment, productivity, economics, and evidence-backed impact.",keywords:["jobs","career","workforce","business","enterprise","layoffs","salary","labor market","productivity at work","economy"]},
{name:"AI Safety, Privacy & Cybersecurity",brief:"Security, privacy, misuse, deepfakes, data protection, safety, and policy explained carefully.",keywords:["cybersecurity","privacy","data leak","security flaw","deepfake","ai safety","alignment","prompt injection","scam","regulation"]},
{name:"Future Tech, Science & Predictions",brief:"Evidence-grounded forecasts about AI, science, compute, and future technology; separate forecasts from facts.",keywords:["future of ai","forecast","prediction","agi","superintelligence","quantum computing","space technology","scientific discovery","2030","future technology"]}
];
function nfEditorialDate(value){if(value){const day=String(value);if(day.length!==10||day[4]!=="-"||day[7]!=="-")throw new Error("Editorial date must use YYYY-MM-DD");const d=new Date(day+"T00:00:00Z");if(!Number.isFinite(d.getTime())||d.toISOString().slice(0,10)!==day)throw new Error("Editorial date is invalid");return day}const parts=new Intl.DateTimeFormat("en-US",{timeZone:"America/New_York",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(new Date()),out={};for(const p of parts)out[p.type]=p.value;return out.year+"-"+out.month+"-"+out.day}
function nfCategoryRotation(dateValue){const day=nfEditorialDate(dateValue),anchor="2026-10-13",delta=Math.floor((Date.parse(day+"T00:00:00Z")-Date.parse(anchor+"T00:00:00Z"))/86400000),index=((delta%NF_EDITORIAL_CATEGORIES.length)+NF_EDITORIAL_CATEGORIES.length)%NF_EDITORIAL_CATEGORIES.length,chosen=NF_EDITORIAL_CATEGORIES[index];return{date_us_eastern:day,timezone:"America/New_York",category:chosen.name,category_index:index,category_brief:chosen.brief,rotation_anchor:anchor,cycle_length_days:NF_EDITORIAL_CATEGORIES.length,next_category:NF_EDITORIAL_CATEGORIES[(index+1)%NF_EDITORIAL_CATEGORIES.length].name,policy:"Deterministic seven-day US Eastern rotation; trend overrides require three distinct YouTube videos and a score lead of at least three."}}
function nfEditorialVideoId(item){const explicit=String(item&&(item.video_id||item.youtube_video_id)||"").trim();if(explicit)return explicit;try{const u=new URL(String(item&&item.url||"")),host=u.hostname.toLowerCase();if(host==="youtu.be")return u.pathname.split("/").filter(Boolean)[0]||"";if(host.endsWith("youtube.com")){const ids=u.searchParams.get("v");if(ids)return ids;const parts=u.pathname.split("/").filter(Boolean);if((parts[0]==="shorts"||parts[0]==="live")&&parts[1])return parts[1]}}catch(_){}return""}
function nfResolveEditorialCategory(items,dateValue){const rotation=nfCategoryRotation(dateValue),videos=new Map();for(const item of Array.isArray(items)?items:[]){const tier=String(item&&(item.source_tier||item.source_type)||"").toLowerCase();if(tier!=="youtube_api"&&tier!=="youtube_popular")continue;const id=nfEditorialVideoId(item);if(!id)continue;if(!videos.has(id))videos.set(id,(String(item.title||"")+" "+String(item.content||item.description_excerpt||"")).toLowerCase())}const scores={};for(const cat of NF_EDITORIAL_CATEGORIES){let count=0,score=0;for(const text of videos.values()){const hits=cat.keywords.filter(k=>text.includes(k.toLowerCase()));if(hits.length){count++;score+=Math.min(3,hits.length)}}scores[cat.name]={matching_video_count:count,score}}const baseline=scores[rotation.category],ranked=NF_EDITORIAL_CATEGORIES.map((c,i)=>({name:c.name,index:i,...scores[c.name]})).sort((a,b)=>b.score-a.score||a.index-b.index),winner=ranked[0],accept=!!winner&&winner.name!==rotation.category&&winner.matching_video_count>=3&&winner.score>=baseline.score+3,chosen=NF_EDITORIAL_CATEGORIES.find(c=>c.name===(accept?winner.name:rotation.category));return{date_us_eastern:rotation.date_us_eastern,timezone:rotation.timezone,category:chosen.name,category_brief:chosen.brief,rotation_category:rotation.category,override:accept,override_status:accept?"accepted_strong_live_trend":winner&&winner.name!==rotation.category?"rejected_insufficient_live_trend_evidence":"scheduled_rotation",supporting_video_count:accept?winner.matching_video_count:baseline.matching_video_count,evidence_scores:scores,distinct_youtube_video_count:videos.size}}
// Two bounded, category-specific YouTube searches extend the date-sorted discovery sample.
// They are trend signals only; they are never used to prove factual claims.
const NF_EDITORIAL_RECOVERY_QUERIES = {
 "AI News & Breakthroughs":["AI model releases announcements OpenAI Anthropic Gemini","AI research breakthrough model evaluation recent"],
 "AI Tools & Practical Workflows":["AI tools productivity workflow Copilot coding assistant","AI software tools practical workflow demonstration"],
 "AI Agents & Automation":["AI agents autonomous workflow computer use framework","agentic AI automation real world use cases"],
 "Robotics & Physical AI":["humanoid robots robotics AI demonstrations","physical AI robot autonomous systems"],
 "AI, Jobs & Business":["AI jobs workforce enterprise productivity","AI salary career labor market automation"],
 "AI Safety, Privacy & Cybersecurity":["AI safety privacy cybersecurity prompt injection deepfake","AI security data leakage privacy risk regulation"],
 "Future Tech, Science & Predictions":["future of AI AGI superintelligence forecast","quantum computing scientific discovery future technology"]
};
const NF_EDITORIAL_EVERGREEN_TOPICS = {
 "AI News & Breakthroughs":"How to separate genuine AI breakthroughs from launch hype, and which evidence actually matters",
 "AI Tools & Practical Workflows":"A practical method for testing AI tools before trusting them with real work",
 "AI Agents & Automation":"Where AI agents are useful, where they fail, and how to design safer workflows",
 "Robotics & Physical AI":"What modern robots can reliably do, and why perception and control still matter",
 "AI, Jobs & Business":"Which workplace tasks AI can assist with, and how teams should measure real impact",
 "AI Safety, Privacy & Cybersecurity":"How prompt injection and data leakage happen, and practical ways to reduce those risks",
 "Future Tech, Science & Predictions":"What current AI research can and cannot tell us about the future of intelligent systems"
};
function nfEditorialYouTubeQueries(categoryName){return (NF_EDITORIAL_RECOVERY_QUERIES[categoryName]||[]).slice(0,2)}
function nfEditorialFallbackTopic(categoryName){return NF_EDITORIAL_EVERGREEN_TOPICS[categoryName]||NF_EDITORIAL_EVERGREEN_TOPICS["AI News & Breakthroughs"]}
function nfEditorialFallbackGate(rotation,observed){return{ok:true,category:rotation.category,distinct_video_count:Number(observed?.distinct_video_count||0),minimum_required:3,videos:Array.isArray(observed?.videos)?observed.videos:[],gate:"SCHEDULED_ROTATION_FALLBACK",fallback:"scheduled_category_evergreen_explainer",scheduled_category:rotation.category,selected_current_trend:false,warning:"Fewer than three distinct category-matching YouTube videos were observed after bounded searches; this is an evergreen explainer, not a verified breaking-trend report. No video IDs or trend metrics were fabricated."}}
function nfCategoryRotationSelfTest(){const anchor="2026-10-13",cycle=NF_EDITORIAL_CATEGORIES.map((_,i)=>nfCategoryRotation(new Date(Date.parse(anchor+"T00:00:00Z")+i*86400000).toISOString().slice(0,10)).category),cyclePass=new Set(cycle).size===7&&nfCategoryRotation("2026-10-20").category===cycle[0]&&nfCategoryRotation("2026-10-14").category===cycle[1],weak=[{url:"https://www.youtube.com/watch?v=robot1",source_tier:"youtube_api",title:"Humanoid robot demonstration"},{url:"https://www.youtube.com/watch?v=robot2",source_tier:"youtube_api",title:"Robotics lab tests a new robot arm"},{url:"https://www.youtube.com/watch?v=robot2",source_tier:"youtube_api",title:"Duplicate robotics evidence"}],weakPass=!nfResolveEditorialCategory(weak,anchor).override,strong=[{url:"https://www.youtube.com/watch?v=robot1",source_tier:"youtube_api",title:"Humanoid robot demonstration and robotics"},{url:"https://www.youtube.com/watch?v=robot2",source_tier:"youtube_api",title:"Robotics lab tests a new robot arm"},{url:"https://www.youtube.com/watch?v=robot3",source_tier:"youtube_popular",title:"Physical AI robot system explained"}],strongDecision=nfResolveEditorialCategory(strong,anchor),strongPass=strongDecision.override&&strongDecision.category==="Robotics & Physical AI",invalidDatePass=(()=>{try{nfCategoryRotation("2026-02-30");return false}catch(_){return true}})(),queryPass=NF_EDITORIAL_CATEGORIES.every(c=>nfEditorialYouTubeQueries(c.name).length===2&&nfEditorialYouTubeQueries(c.name).every(q=>q.length>=10)),topicPass=NF_EDITORIAL_CATEGORIES.every(c=>nfEditorialFallbackTopic(c.name).length>=50),fallback=nfEditorialFallbackGate(nfCategoryRotation(anchor),{distinct_video_count:2,videos:weak.slice(0,2)}),fallbackPass=fallback.ok&&fallback.gate==="SCHEDULED_ROTATION_FALLBACK"&&fallback.distinct_video_count===2&&fallback.videos.length===2&&fallback.selected_current_trend===false;return{ok:cyclePass&&weakPass&&strongPass&&invalidDatePass&&queryPass&&topicPass&&fallbackPass,checks:{seven_unique_days_and_wraparound:cyclePass,duplicate_video_ids_do_not_count:weakPass,three_video_trend_override:strongPass,invalid_date_rejected:invalidDatePass,two_bounded_queries_per_category:queryPass,evergreen_fallback_topic_for_all_categories:topicPass,low_trend_evidence_uses_honest_fallback_without_fabricated_ids:fallbackPass},category_count:NF_EDITORIAL_CATEGORIES.length,anchor,cycle,strong_decision:strongDecision,fallback_test:fallback}}


// Trend-to-script gate added to the live Main Worker bundle on 2026-10-13.
// This helper is intentionally recorded as a fragment, not a deployable Worker by itself.
function nfEditorialTrendGate(items,categoryName){
 const cat=NF_EDITORIAL_CATEGORIES.find(x=>x.name===categoryName);
 if(!cat)return{ok:false,error:"Unknown editorial category",category:categoryName,videos:[]};
 const videos=new Map();
 for(const x of Array.isArray(items)?items:[]){
  const tier=String(x.source_tier||x.source_type||"").toLowerCase();
  if(tier!=="youtube_api"&&tier!=="youtube_popular")continue;
  const id=nfEditorialVideoId(x);if(!id)continue;
  const text=(String(x.title||"")+" "+String(x.content||x.description_excerpt||"")).toLowerCase();
  const matched=cat.keywords.filter(k=>text.includes(k.toLowerCase()));if(!matched.length)continue;
  const row={video_id:id,url:String(x.url||"https://www.youtube.com/watch?v="+id),title:String(x.title||"").trim(),published_at:x.published_at||null,matched_keywords:matched,match_score:matched.length,score:Number(x.score||0)};
  const old=videos.get(id);if(!old||row.match_score>old.match_score)videos.set(id,row);
 }
 const rows=[...videos.values()].sort((a,b)=>b.match_score-a.match_score||b.score-a.score);
 return{ok:rows.length>=3,category:categoryName,distinct_video_count:rows.length,minimum_required:3,videos:rows.slice(0,8),gate:rows.length>=3?"PASS":"BLOCKED_INSUFFICIENT_CATEGORY_RELATED_YOUTUBE_VIDEOS"};
}

// Live integration contract (confirmed by deployment API metadata; runtime verification is
// delegated to the GitHub runner because this environment cannot reach the public Worker URL):
// POST /editorial/trend-script, Authorization: Bearer WORKER_AUTH_TOKEN
// -> research from YouTube Data API v3 + free public RSS/Atom/arXiv (Tavily disabled),
// -> bounded category-targeted YouTube Data API v3 discovery (date order first, then up to
//    two 7-day view-count-ranked category queries), deduplicated by actual video ID;
// -> if three matching videos are still unavailable, preserve the scheduled category and use
//    a labelled evergreen explainer instead of falsely calling it trending;
// -> Groq / Workers AI script; 850-1000 words; independent hook/voice and unsupported-current-claim QA.
// Tavily is not called by this AI Tech Lab research route. D1-unavailable mode is explicitly labelled;
// no content rows/uploads/schedules are created by this endpoint.

// Trigger the no-publishing GitHub-runner verification after the workflow was added.
// Runtime status remains pending until the GitHub Actions log is inspected.

// Cross-cutting provider hardening deployed in Main Worker v420:
// nfGroqText parses Retry-After and compound x-ratelimit-reset values; HTTP 429 retry stays capped at one.
// nfGenerateScript repairs underlength/overlength drafts once before the final 850–1000 word gate.
// Research/claim/script prompt context and token ceilings are bounded to reduce Groq free-tier TPM spikes.
// Trend-script QA fills an omitted `approved` flag ONLY when explicit hook/human scores are >=7 and unsupported claims are [];
// explicit approved:false, low scores, malformed or non-empty unsupported claims continue to block the package.
// No QA is bypassed. See docs/GROQ_RATE_LIMIT_RECOVERY_2026-10-13.md (v419 rollback).
