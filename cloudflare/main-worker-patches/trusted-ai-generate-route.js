/**
 * Live hotfix snapshot for Main Cloudflare Worker dark-sunset-a2a1.
 * Captured from the deployed source on 2026-10-13 after the authenticated
 * Groq-primary route passed the GitHub Actions JSON-mode probe.
 *
 * Integration requirements in the existing Worker:
 * - Add this function before nfResearchTopic().
 * - In the existing fetch router, add:
 *   if (u.pathname === "/internal/ai/generate" && request.method === "POST")
 *     return await nfTrustedAiGenerate(request, env);
 * - Dependencies already present in the live Main Worker: nfGroqText(), nfLog().
 * - Never expose secret values; WORKER_AUTH_TOKEN and GROQ_API_KEY remain secret bindings.
 * - This route intentionally does not turn on paid APIs or invoke Workers AI.
 */
async function nfTrustedAiGenerate(request,env){
 const expected=String(env.WORKER_AUTH_TOKEN||"").trim(),received=String(request.headers.get("Authorization")||"").trim();
 if(!expected||!received||received!=="Bearer "+expected)return Response.json({ok:false,code:"WORKER_AUTH_FAILED",error:"Unauthorized"},{status:401,headers:{"Cache-Control":"no-store","WWW-Authenticate":"Bearer"}});
 let body={};try{body=await request.json()}catch(_){return Response.json({ok:false,code:"INVALID_JSON",error:"Invalid JSON"},{status:400,headers:{"Cache-Control":"no-store"}})}
 const messages=Array.isArray(body.messages)?body.messages:[];if(!messages.some(m=>m&&String(m.role||"")==="user"&&typeof m.content==="string"&&m.content.trim()))return Response.json({ok:false,code:"USER_MESSAGE_REQUIRED",error:"A text user message is required"},{status:400,headers:{"Cache-Control":"no-store"}});
 const allowed=new Set(["system","developer","user","assistant"]);let chars=0;const clean=[];
 for(const m of messages){if(!m||!allowed.has(String(m.role||""))||typeof m.content!=="string")return Response.json({ok:false,code:"UNSUPPORTED_MESSAGE",error:"Only text messages with standard roles are accepted"},{status:400,headers:{"Cache-Control":"no-store"}});chars+=m.content.length;if(chars>52000)return Response.json({ok:false,code:"INPUT_TOO_LARGE",error:"Input exceeds the bounded text limit"},{status:413,headers:{"Cache-Control":"no-store"}});clean.push({role:String(m.role),content:m.content});}
 const maxTokens=Math.max(64,Math.min(3500,Number(body.max_tokens||body.max_completion_tokens||800)));
 // This Groq model rejects response_format=json_object with HTTP 400 in this account.
 // Keep JSON-format instructions in the caller's system prompt and let caller-side JSON validation enforce output.
 const requestedJsonMode=!!(body.response_format&&typeof body.response_format==="object"&&["json_object","json_schema"].includes(body.response_format.type));
 const response=(out)=>{const content=String(out&&out.text||"").trim();if(!content)throw new Error("Groq returned empty content");return Response.json({ok:true,provider:"groq",id:"chatcmpl_"+crypto.randomUUID(),object:"chat.completion",created:Math.floor(Date.now()/1000),model:String(out.model||env.GROQ_MODEL||"openai/gpt-oss-20b"),choices:[{index:0,message:{role:"assistant",content},finish_reason:"stop"}],usage:{latency_ms:Number(out.latency_ms||0)},json_mode_fallback:requestedJsonMode},{headers:{"Cache-Control":"no-store"}})};
 try{
  const out=await nfGroqText(env,clean,maxTokens,60000,false,null);
  return response(out);
 }catch(e){
  const message=String(e&&e.message||e),marker="HTTP ",pos=message.lastIndexOf(marker),statusText=pos>=0?message.slice(pos+marker.length,pos+marker.length+3):"",digits=statusText.length===3&&statusText.split("").every(c=>c>="0"&&c<="9"),upstream=digits?Number(statusText):0;
  const code=upstream===429?"GROQ_RATE_LIMITED":upstream===400?"GROQ_REQUEST_REJECTED_HTTP_400":upstream===401||upstream===403?"GROQ_CREDENTIAL_REJECTED":upstream===404?"GROQ_MODEL_NOT_FOUND":!env.GROQ_API_KEY?"GROQ_NOT_CONFIGURED":"GROQ_UPSTREAM_FAILED";
  const status=upstream===429?429:upstream>=500?503:502;
  await nfLog(env,"ERROR","TRUSTED_AI_PROXY",code+"; request failed without exposing credentials.");
  return Response.json({ok:false,code,error:"Configured Groq primary could not complete this request."},{status,headers:{"Cache-Control":"no-store"}});
 }
}
