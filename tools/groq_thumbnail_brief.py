#!/usr/bin/env python3
"""Use Groq text inference for a concise topic-specific thumbnail brief; render the image locally."""
import json, os, re, urllib.request
from pathlib import Path

def main():
    title=Path("work/title.txt").read_text(encoding="utf-8").strip()
    script=Path("work/script.txt").read_text(encoding="utf-8").strip()
    key=os.getenv("GROQ_API_KEY","").strip()
    out=Path("work/thumbnail_brief.json")
    if not key:
        brief={"provider":"local_fallback","hook":"","visual_focus":"AI chip","note":"GROQ_API_KEY not configured; local topic-specific thumbnail renderer used"}
        out.write_text(json.dumps(brief,indent=2),encoding="utf-8")
        print(json.dumps(brief)); return
    payload={"model":"llama-3.3-70b-versatile","temperature":0.35,"max_tokens":180,
      "messages":[{"role":"system","content":"Create YouTube thumbnail creative briefs. Return ONLY valid JSON with keys hook (2-5 words, no clickbait), visual_focus (one of: security shield, AI chip, robot hand, neural network, data center, digital globe), and visual_reason (one sentence). Never invent facts."},
      {"role":"user","content":"Title: "+title+"\nScript opening: "+script[:1400]+"\nMake a distinctive topic-specific AI Tech Lab thumbnail concept, readable on a phone."}]}
    req=urllib.request.Request("https://api.groq.com/openai/v1/chat/completions",data=json.dumps(payload).encode(),headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"})
    try:
      with urllib.request.urlopen(req,timeout=35) as response: data=json.loads(response.read().decode())
      content=data["choices"][0]["message"]["content"]
      match=re.search(r"\{.*\}",content,re.S)
      brief=json.loads(match.group(0) if match else content)
      hook=re.sub(r"[^A-Za-z0-9 '&!?-]","",str(brief.get("hook",""))).strip()[:38]
      focus=str(brief.get("visual_focus","AI chip")).strip()[:40]
      if not hook: raise ValueError("Groq returned an empty thumbnail hook")
      result={"provider":"Groq text inference","hook":hook,"visual_focus":focus,"visual_reason":str(brief.get("visual_reason",""))[:220]}
      out.write_text(json.dumps(result,indent=2),encoding="utf-8")
      print(json.dumps(result))
    except Exception as exc:
      # Keep the run recoverable, but never claim Groq made the image.
      result={"provider":"local_fallback","hook":"","visual_focus":"AI chip","note":"Groq brief unavailable: "+str(exc)[:180]}
      out.write_text(json.dumps(result,indent=2),encoding="utf-8")
      print(json.dumps(result))
if __name__=="__main__": main()
