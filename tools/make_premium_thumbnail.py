#!/usr/bin/env python3
"""Create premium thumbnails with optional Hugging Face FLUX.1-schnell imagery plus deterministic Python/Pillow typography and 3D overlays."""
from __future__ import annotations
import argparse, json, math, os, re
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

W, H = 1280, 720
NAVY=(3,8,24); CYAN=(45,224,255); GOLD=(255,207,80); WHITE=(247,250,255)

def generate_flux_background(title, focus="", visual_reason=""):
    """Use one FLUX.1-schnell image only when a Hugging Face token is configured.
    Missing token, unavailable inference, or exhausted credits safely triggers local Python artwork.
    """
    token = os.getenv("HF_TOKEN", "").strip() or os.getenv("HUGGINGFACEHUB_API_TOKEN", "").strip()
    if not token:
        return None, "local_python_fallback: HF_TOKEN not configured"
    focus = re.sub(r"[^A-Za-z0-9 ,&'-]", "", str(focus or "AI technology"))[:100]
    reason = re.sub(r"\s+", " ", str(visual_reason or ""))[:240]
    prompt = (
        "Create a premium cinematic 16:9 editorial technology photograph for a YouTube thumbnail. "
        f"Story/topic: {title[:220]}. Main visual subject: {focus}. Editorial context: {reason}. "
        "Place the main subject on the RIGHT half, leave the LEFT third visually dark and uncluttered for large title typography. "
        "Photorealistic high-end technology advertising, dramatic but plausible lighting, deep navy shadows, electric cyan rim light, "
        "subtle amber highlights, real material texture, rich depth, controlled contrast, crisp subject, atmospheric particles only if relevant. "
        "No text, no letters, no numbers, no logo, no watermark, no collage, no split-screen, no UI screenshot, no fake charts."
    )
    try:
        from huggingface_hub import InferenceClient
        client = InferenceClient(provider="fal-ai", api_key=token, timeout=120)
        image = client.text_to_image(
            prompt,
            model="black-forest-labs/FLUX.1-schnell",
            width=1024,
            height=576,
            num_inference_steps=4,
        )
        if image is None:
            raise RuntimeError("FLUX returned no image")
        image = image.convert("RGB").resize((W, H), Image.Resampling.LANCZOS)
        return image, "FLUX.1-schnell via Hugging Face Inference Providers"
    except Exception as exc:
        # Recovery never blocks production or claims FLUX succeeded when it did not.
        print("FLUX unavailable; using local Python thumbnail:", type(exc).__name__, str(exc)[:180])
        return None, "local_python_fallback: FLUX request unavailable"



def font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"):
        if Path(p).is_file(): return ImageFont.truetype(p,size)
    return ImageFont.load_default()

def background():
    y,x=np.mgrid[0:H,0:W]; yf=y.astype(np.float32)/H; xf=x.astype(np.float32)/W
    glow=np.exp(-(((xf-.76)/.25)**2+((yf-.49)/.43)**2)*2.0)
    glow2=np.exp(-(((xf-.32)/.5)**2+((yf-.15)/.45)**2)*2.2)
    arr=np.zeros((H,W,3),dtype=np.uint8)
    arr[:,:,0]=np.clip(3+22*glow+4*glow2+4*yf,0,255)
    arr[:,:,1]=np.clip(8+92*glow+14*glow2+9*yf,0,255)
    arr[:,:,2]=np.clip(24+148*glow+30*glow2+22*yf,0,255)
    img=Image.fromarray(arr,"RGB").convert("RGBA"); d=ImageDraw.Draw(img,"RGBA")
    for i in range(-500,1800,70): d.line((i,0,i-300,H),fill=(25,142,204,33),width=2)
    for r in (120,190,265): d.ellipse((940-r,335-r*.64,940+r,335+r*.64),outline=(70,224,255,70),width=3)
    for xx in range(705,1270,42): d.line((xx,35,xx,680),fill=(45,168,225,25),width=1)
    for yy in range(45,690,42): d.line((680,yy,1260,yy),fill=(45,168,225,25),width=1)
    return img

def draw_chip(img):
    glow=Image.new("RGBA",img.size,(0,0,0,0)); gd=ImageDraw.Draw(glow)
    gd.ellipse((780,115,1215,575),fill=(0,190,255,95)); img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(46)))
    d=ImageDraw.Draw(img,"RGBA")
    for n in range(9):
        x=805+n*39; d.line((x,160,x,105-(n%3)*13),fill=(44,209,255,145),width=4)
        d.ellipse((x-5,99-(n%3)*13,x+5,109-(n%3)*13),fill=(120,240,255,230))
        d.line((x,520,x,574+(n%3)*11),fill=(44,209,255,120),width=3)
    front=[(835,218),(1000,154),(1160,221),(1128,425),(960,505),(795,424)]
    side=[(x+24,y+21) for x,y in front]
    d.polygon(side,fill=(2,20,48,255),outline=(0,88,150,255))
    d.polygon([front[0],front[1],side[1],side[0]],fill=(36,139,200,255))
    d.polygon([front[1],front[2],side[2],side[1]],fill=(14,83,151,255))
    d.polygon([front[2],front[3],side[3],side[2]],fill=(6,49,102,255))
    d.polygon([front[3],front[4],side[4],side[3]],fill=(2,28,66,255))
    d.polygon(front,fill=(8,29,57,255),outline=(68,226,255,255))
    core=[(862,240),(997,189),(1133,240),(1104,405),(962,474),(823,407)]
    d.polygon(core,fill=(14,55,94,255),outline=(255,207,80,255),width=4)
    center=[(908,265),(999,232),(1088,267),(1064,377),(962,424),(870,378)]
    d.polygon(center,fill=(2,15,37,255),outline=(65,223,255,255),width=4)
    d.ellipse((920,276,1061,410),fill=(0,90,151,220),outline=(89,239,255,255),width=5)
    d.ellipse((941,297,1041,397),fill=(8,42,83,255),outline=(255,207,80,255),width=3)
    d.text((991,347),"AI",font=font(66),fill=WHITE,anchor="mm",stroke_width=2,stroke_fill=(0,88,140,255))
    for yy in (278,310,342,374,406):
        d.line((846,yy,880,yy+2),fill=(76,212,255,230),width=4)
        d.line((1090,yy,1112,yy-3),fill=(76,212,255,230),width=4)
    d.line(front[:3],fill=(208,252,255,255),width=4); d.line(front[3:],fill=(26,112,185,255),width=3)

def draw_shield(img):
    """Topic-specific beveled 3D shield and lock for AI-agent safety/security videos."""
    glow=Image.new("RGBA",img.size,(0,0,0,0)); gd=ImageDraw.Draw(glow)
    gd.ellipse((785,110,1210,600),fill=(0,190,255,105))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(48)))
    d=ImageDraw.Draw(img,"RGBA")
    # Circuit paths behind the shield.
    for x in (810,875,1145,1200):
        d.line((x,130,x,200),fill=(45,220,255,150),width=4)
        d.ellipse((x-6,122,x+6,134),fill=(155,245,255,230))
        d.line((x,480,x,555),fill=(45,220,255,130),width=3)
    front=[(1000,155),(1155,218),(1138,378),(1095,451),(1000,515),(905,451),(862,378),(845,218)]
    back=[(x+25,y+24) for x,y in front]
    d.polygon(back,fill=(1,22,48,255),outline=(0,98,160,255))
    d.polygon([front[0],front[1],back[1],back[0]],fill=(56,159,205,255))
    d.polygon([front[1],front[2],back[2],back[1]],fill=(16,96,157,255))
    d.polygon([front[2],front[3],back[3],back[2]],fill=(8,65,119,255))
    d.polygon([front[3],front[4],back[4],back[3]],fill=(3,34,73,255))
    d.polygon(front,fill=(8,36,68,255),outline=(68,226,255,255))
    inner=[(1000,196),(1118,244),(1105,365),(1068,422),(1000,465),(932,422),(895,365),(882,244)]
    d.polygon(inner,fill=(12,69,109,255),outline=(255,207,80,255),width=5)
    # Gold-rimmed lock is a legible security cue at mobile scale.
    d.arc((941,272,1059,392),180,360,fill=(230,250,255,255),width=15)
    d.rounded_rectangle((925,326,1075,430),radius=20,fill=(3,18,40,255),outline=(75,229,255,255),width=5)
    d.ellipse((982,353,1018,389),fill=(255,207,80,255))
    d.rounded_rectangle((993,379,1007,407),radius=6,fill=(255,207,80,255))
    d.line(front[:3],fill=(215,251,255,255),width=4)

def headline_for(title):
    low=title.lower()
    if "agent" in low and any(x in low for x in ("security","safe","test","guard","risk")): return ["AI AGENTS","NEED GUARDRAILS"]
    if any(x in low for x in ("local ai","into your pc","on-device","on device","offline ai")): return ["AI IS MOVING","INTO YOUR PC"]
    if any(x in low for x in ("cybersecurity","cyber security","hack","privacy","security")): return ["YOUR AI","YOUR SECURITY?"]
    if any(x in low for x in ("robot","humanoid")): return ["THE NEXT","AI ROBOTS"]
    if any(x in low for x in ("agent","automation")): return ["AI AGENTS","CHANGE EVERYTHING"]
    if any(x in low for x in ("chip","gpu","processor")): return ["THE AI CHIP","RACE"]
    words=re.findall(r"[A-Za-z0-9]+",re.sub(r"(?i)^AI Tech Lab\s*[:|—-]?\s*","",title).upper())[:7]
    if len(words)<=3: return [" ".join(words or ["FUTURE TECHNOLOGY"])]
    cut=math.ceil(len(words)/2); return [" ".join(words[:cut])," ".join(words[cut:])]

def make(title,output,hook=None,focus="",visual_reason=""):
    flux_image, image_provider = generate_flux_background(title, focus, visual_reason)
    if flux_image is None:
        img=background()
    else:
        img=flux_image.convert("RGBA")
        # Python-authored navy shade keeps typography legible and unifies FLUX with channel branding.
        img.alpha_composite(Image.new("RGBA", img.size, (2, 9, 25, 58)))
        d=ImageDraw.Draw(img,"RGBA")
        for i in range(-500,1800,90):
            d.line((i,0,i-300,H),fill=(45,170,225,20),width=2)
    low=(str(focus)+" "+title).lower()
    if any(x in low for x in ("security","shield","safe","test","guard","risk")):
        draw_shield(img)
    else:
        draw_chip(img)
    panel=Image.new("RGBA",img.size,(0,0,0,0)); pd=ImageDraw.Draw(panel)
    pd.rounded_rectangle((38,72,716,602),radius=32,fill=(1,8,24,218),outline=(45,210,250,165),width=3)
    img.alpha_composite(panel.filter(ImageFilter.GaussianBlur(.4)))
    d=ImageDraw.Draw(img,"RGBA")
    d.text((78,96),"AI TECH LAB  /  FUTURE INTELLIGENCE",font=font(22),fill=CYAN+(255,))
    lines=headline_for(hook or title); fs=76 if len(lines)==2 and max(map(len,lines))<=14 else 62
    while fs>44 and any(d.textbbox((0,0),line,font=font(fs))[2]>590 for line in lines): fs-=2
    f=font(fs); y=235 if len(lines)==2 else 255
    for i,line in enumerate(lines[:3]): d.text((78,y+i*(fs+22)),line,font=f,fill=(GOLD if i==len(lines)-1 else WHITE)+(255,),stroke_width=2,stroke_fill=(0,0,0,210))
    d.rounded_rectangle((78,504,418,563),radius=17,fill=(9,186,227,248),outline=(180,246,255,255),width=2)
    d.text((101,518),"WHAT CHANGES NEXT?",font=font(22),fill=NAVY+(255,))
    d.text((80,632),"RESEARCH  •  REAL-WORLD IMPACT  •  WHAT TO KNOW",font=font(17),fill=(181,216,239,255))
    img=ImageEnhance.Contrast(img.convert("RGB")).enhance(1.08).filter(ImageFilter.UnsharpMask(radius=1.4,percent=145,threshold=2))
    output.parent.mkdir(parents=True,exist_ok=True); img.save(output,quality=95,optimize=True)
    with Image.open(output) as check:
        if check.size!=(1280,720): raise SystemExit(f"Thumbnail dimensions invalid: {check.size}")
        check.verify()
    return image_provider

def main():
    p=argparse.ArgumentParser(); p.add_argument("--title-file",default="work/title.txt"); p.add_argument("--output",required=True); p.add_argument("--brief-file",default="work/thumbnail_brief.json")
    args=p.parse_args(); title=Path(args.title_file).read_text(encoding="utf-8").strip()
    if not title: raise SystemExit("Premium thumbnail needs the actual video title.")
    hook=None; focus=""; visual_reason=""
    brief_path=Path(args.brief_file)
    if brief_path.is_file():
        try:
            brief=json.loads(brief_path.read_text(encoding="utf-8"))
            hook=str(brief.get("hook") or "").strip() or None
            focus=str(brief.get("visual_focus") or "").lower()
            visual_reason=str(brief.get("visual_reason") or "").strip()
        except Exception:
            hook=None
    out=Path(args.output); image_provider=make(title,out,hook,focus,visual_reason)
    print(json.dumps({"thumbnail":str(out),"dimensions":"1280x720","style":"FLUX-assisted cinematic image with Python typography/3D overlays" if image_provider.startswith("FLUX") else "locally rendered Python 3D thumbnail","image_provider":image_provider,"creative_brief":"Groq" if brief_path.is_file() and hook else "local fallback","visual_focus":focus or ("security shield" if "security" in title.lower() else "AI chip"),"hook":hook or title}))

if __name__=="__main__": main()
