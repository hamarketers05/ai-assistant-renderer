# Main Worker Groq reasoning-effort reliability hotfix

Verified on 2026-10-13 in the deployed Main Worker `dark-sunset-a2a1`.

Root cause reproduced by the Oct 15 research preflight: Groq accepted the request but returned empty assistant content at the default medium reasoning effort. The worker logged `Groq returned empty content`, then the caller fell back to the Handoff Worker's exhausted free-neuron pool, so the visible failure looked like a Workers AI quota failure.

The live worker now:
- adds optional `reasoningEffort="medium"` to `nfGroqText(...)`;
- sets Groq `reasoning_effort` to `low|medium|high` only for `openai/gpt-oss-20b` and `openai/gpt-oss-120b`;
- keeps existing callers at medium by default;
- on the authenticated `/internal/ai/generate` route, retries exactly once at low effort only when medium effort returns empty content;
- does not change the primary provider, credentials, or paid-service settings.

Live `nfGroqText` signature:
```js
async function nfGroqText(env,messages,maxTokens=700,timeoutMs=10000,jsonMode=false,schema=null,reasoningEffort="medium"){
 const model=String(env.GROQ_MODEL||"openai/gpt-oss-20b").trim();
 if(!env.GROQ_API_KEY)throw new Error("GROQ_API_KEY missing");
 const started=Date.now(),requestId=crypto.randomUUID(),controller=new AbortController();let timer;
 try{
  timer=setTimeout(()=>controller.abort(),Math.max(1000,Math.min(60000,Number(timeoutMs)||10000)));
  const clean=(Array.isArray(messages)?messages:[]).filter(x=>x&&typeof x==="object").map(x=>({role:["system","developer","user","assistant"].includes(String(x.role||""))?String(x.role):"user",content:String(x.content||"").slice(0,26000)}));
  const body={model,messages:clean,max_tokens:Math.max(32,Math.min(4096,Number(maxTokens)||700)),temperature:0.2};
  if(model==="openai/gpt-oss-20b"||model==="openai/gpt-oss-120b"){const effort=String(reasoningEffort||"medium");body.reasoning_effort=["low","medium","high"].includes(effort)?effort:"medium";}
  if(jsonMode)body.response_format=schema?{type:"json_schema",json_schema:{name:"assistant_response",schema,strict:false}}:{type:"json_object"};
  const res=await fetch("https://api.groq.com/openai/v1/chat/completions",{method:"POST",signal:controller.signal,headers:{"Content-Type":"application/json",Authorization:"Bearer "+env.GROQ_API_KEY},body:JSON.stringify(body)});
  if(!res.ok)throw new Error("Groq HTTP "+res.status);
  const data=await res.json(),text=data?.choices?.[0]?.message?.content;
  if(typeof text!=="string"||!text.trim())throw new Error("Groq returned empty content");
  await nfRecordProviderEvent(env,requestId,"groq",model,"SUCCESS",started,null);
  await nfLog(env,"INFO","AI_PROVIDER","provider=groq model="+model+" status=200 latency_ms="+(Date.now()-started));
  return {text:text.trim(),model,latency_ms:Date.now()-started};
 }catch(err){
  const message=err?.name==="AbortError"?"timeout":String(err?.message||err);
  const status=(message.match(/HTTP\s+\d{3}/)||[])[0]||message.slice(0,100);
  await nfRecordProviderEvent(env,requestId,"groq",model,"FAILED",started,status);
  await nfLog(env,"ERROR","AI_PROVIDER","provider=groq model="+model+" status="+status+" latency_ms="+(Date.now()-started));
  throw new Error("Groq request failed: "+status);
 }finally{if(timer)clearTimeout(timer)}
}
```

Exact authenticated route source is preserved in `trusted-ai-generate-route.js`.
No secret values are stored in this patch snapshot.
