#!/usr/bin/env python3
"""Create premium Python/Pillow thumbnails with layered 3D pop-out and cinematic bars."""
from __future__ import annotations
import argparse, json, math, re
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

W, H = 1280, 720
NAVY=(3,8,24); CYAN=(45,224,255); GOLD=(255,207,80); WHITE=(247,250,255)

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

def draw_robot(img):
    glow=Image.new("RGBA",img.size,(0,0,0,0)); gd=ImageDraw.Draw(glow)
    gd.ellipse((770,115,1220,595),fill=(255,150,40,100))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(44)))
    d=ImageDraw.Draw(img,"RGBA")
    back=[(892,220),(1010,168),(1126,226),(1110,390),(1008,474),(900,392)]
    side=[(x+24,y+22) for x,y in back]
    d.polygon(side,fill=(2,18,45,255),outline=(0,78,130,255))
    d.polygon([back[0],back[1],side[1],side[0]],fill=(211,113,29,255))
    d.polygon([back[1],back[2],side[2],side[1]],fill=(128,76,34,255))
    d.polygon(back,fill=(10,38,66,255),outline=(83,226,255,255))
    d.rounded_rectangle((918,257,1101,378),radius=28,fill=(4,15,33,255),outline=(255,207,80,255),width=5)
    for x in (957,1062):
        d.ellipse((x-21,294,x+21,336),fill=(5,100,155,255),outline=(110,243,255,255),width=4)
        d.ellipse((x-8,306,x+8,322),fill=(255,230,120,255))
    d.line((957,355,1065,355),fill=(80,210,255,255),width=7)
    for x in range(900,1110,35):
        d.line((x,215,x,177-(x%3)*6),fill=(54,214,255,180),width=3)
        d.ellipse((x-4,170-(x%3)*6,x+4,178-(x%3)*6),fill=(255,207,80,255))

def draw_network(img):
    glow=Image.new("RGBA",img.size,(0,0,0,0)); gd=ImageDraw.Draw(glow)
    gd.ellipse((770,105,1220,600),fill=(0,190,255,110))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(42)))
    d=ImageDraw.Draw(img,"RGBA")
    nodes=[(845,245),(955,180),(1080,216),(1150,315),(1090,430),(965,485),(850,405),(975,330)]
    edges=[(0,1),(1,2),(2,3),(3,4),(4,5),(5,6),(6,0),(0,7),(1,7),(2,7),(3,7),(4,7),(5,7),(6,7)]
    for a,b in edges:
        x1,y1=nodes[a]; x2,y2=nodes[b]
        for off in range(6,0,-1):
            d.line((x1+off,y1+off,x2+off,y2+off),fill=(0,25+off*5,65+off*8,130),width=7)
        d.line((x1,y1,x2,y2),fill=(65,224,255,235),width=4)
    for i,(x,y) in enumerate(nodes):
        r=19 if i==7 else 13
        d.ellipse((x-r-8,y-r-8,x+r+8,y+r+8),fill=(0,180,245,55))
        d.ellipse((x-r,y-r,x+r,y+r),fill=(5,37,68,255),outline=(255,207,80,255) if i==7 else (95,240,255,255),width=5)

def draw_datacenter(img):
    glow=Image.new("RGBA",img.size,(0,0,0,0)); gd=ImageDraw.Draw(glow)
    gd.ellipse((765,110,1225,605),fill=(0,165,255,105))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(48)))
    d=ImageDraw.Draw(img,"RGBA")
    for i in range(3):
        x=835+i*112
        back=[(x,220),(x+82,185),(x+82,440),(x,474)]
        side=[(a+20,b+17) for a,b in back]
        d.polygon(side,fill=(1,15,40,255),outline=(0,90,145,255))
        d.polygon(back,fill=(7,42,77,255),outline=(55,225,255,255),width=4)
        d.polygon([(x,220),(x+82,185),(x+102,202),(x+20,237)],fill=(20,100,160,255))
        for y in (265,320,375,430):
            d.rounded_rectangle((x+13,y,x+61,y+18),radius=5,fill=(255,207,80,235),outline=(120,245,255,255),width=2)
            d.ellipse((x+67,y+4,x+74,y+11),fill=(90,255,175,255))

def draw_globe(img):
    glow=Image.new("RGBA",img.size,(0,0,0,0)); gd=ImageDraw.Draw(glow)
    gd.ellipse((765,115,1225,595),fill=(0,205,255,110))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(44)))
    d=ImageDraw.Draw(img,"RGBA")
    d.ellipse((845,185,1145,485),fill=(4,36,75,255),outline=(105,240,255,255),width=7)
    d.ellipse((895,185,1095,485),outline=(50,193,240,220),width=4)
    d.ellipse((845,255,1145,415),outline=(50,193,240,220),width=4)
    d.arc((845,185,1145,485),250,290,fill=(255,207,80,255),width=7)
    d.arc((845,185,1145,485),70,110,fill=(255,207,80,255),width=7)
    for x,y in ((920,270),(1040,310),(980,390),(1080,410)):
        d.ellipse((x-8,y-8,x+8,y+8),fill=(255,207,80,255))
        d.line((x,y,x+44,y-33),fill=(75,236,255,220),width=3)

def headline_for(title):
    low=title.lower()
    if "agent" in low and any(x in low for x in ("security","safe","test","guard","risk","safety")): return ["AI AGENTS","NEED GUARDRAILS"]
    if any(x in low for x in ("local ai","into your pc","on-device","on device","offline ai")): return ["AI IS MOVING","INTO YOUR PC"]
    if any(x in low for x in ("cybersecurity","cyber security","hack","privacy","security")): return ["YOUR AI","YOUR SECURITY?"]
    if any(x in low for x in ("robot","humanoid")): return ["THE NEXT","AI ROBOTS"]
    if any(x in low for x in ("agent","automation")): return ["AI AGENTS","CHANGE EVERYTHING"]
    if any(x in low for x in ("cloud","server","data center","datacenter")): return ["INSIDE THE","AI DATA CENTER"]
    if any(x in low for x in ("network","neural","training","model")): return ["INSIDE THE","AI BRAIN"]
    if any(x in low for x in ("chip","gpu","processor")): return ["THE AI CHIP","RACE"]
    if any(x in low for x in ("job","workforce","career","employment")): return ["AI IS CHANGING","THE WORKPLACE"]
    if any(x in low for x in ("health","medical","doctor","hospital")): return ["AI IN","HEALTHCARE"]
    if any(x in low for x in ("smartphone","phone","mobile","app")): return ["AI IN","YOUR POCKET"]
    words=re.findall(r"[A-Za-z0-9]+",re.sub(r"(?i)^AI Tech Lab\s*[:|—-]?\s*","",title).upper())[:7]
    if len(words)<=3: return [" ".join(words or ["FUTURE TECHNOLOGY"])]
    cut=math.ceil(len(words)/2); return [" ".join(words[:cut])," ".join(words[cut:])]

def make(title,output,hook=None,focus="",visual_reason=""):
    img=background()
    subject=Image.new("RGBA",(W,H),(0,0,0,0))
    low=(str(focus)+" "+title).lower()
    if any(x in low for x in ("security","shield","safe","test","guard","risk","privacy","hack")):
        draw_shield(subject); visual_focus="security shield"
    elif any(x in low for x in ("robot","humanoid","hand")):
        draw_robot(subject); visual_focus="robot hand"
    elif any(x in low for x in ("network","neural","model","training","agent","workflow")):
        draw_network(subject); visual_focus="neural network"
    elif any(x in low for x in ("cloud","server","data center","datacenter")):
        draw_datacenter(subject); visual_focus="data center"
    elif any(x in low for x in ("globe","global","world","internet")):
        draw_globe(subject); visual_focus="digital globe"
    else:
        draw_chip(subject); visual_focus="AI chip"
    img.alpha_composite(subject)
    d=ImageDraw.Draw(img,"RGBA")
    d.rectangle((0,0,W,86),fill=(0,0,0,255)); d.rectangle((0,634,W,H),fill=(0,0,0,255))
    d.line((0,86,W,86),fill=(45,224,255,150),width=2); d.line((0,634,W,634),fill=(45,224,255,120),width=2)
    panel=Image.new("RGBA",img.size,(0,0,0,0)); pd=ImageDraw.Draw(panel)
    pd.rounded_rectangle((38,104,716,596),radius=32,fill=(1,8,24,226),outline=(45,210,250,185),width=3)
    img.alpha_composite(panel.filter(ImageFilter.GaussianBlur(.4))); d=ImageDraw.Draw(img,"RGBA")
    d.text((78,124),"AI TECH LAB  /  FUTURE INTELLIGENCE",font=font(22),fill=CYAN+(255,))
    lines=headline_for(title); fs=76 if len(lines)==2 and max(map(len,lines))<=14 else 62
    while fs>44 and any(d.textbbox((0,0),line,font=font(fs))[2]>590 for line in lines): fs-=2
    f=font(fs); y=235 if len(lines)==2 else 255
    for i,line in enumerate(lines[:3]):
        line_y=y+i*(fs+22)
        # "8D-style" is a premium multilayer extrusion treatment, not a literal display format.
        for depth in range(12,0,-1):
            dx=depth*1.45; dy=depth*1.05
            d.text((78+dx,line_y+dy),line,font=f,fill=(0,12+depth*2,32+depth*5,255),
                   stroke_width=2,stroke_fill=(0,90,145,255))
        d.text((75,line_y-2),line,font=f,fill=(0,185,235,120),stroke_width=5,stroke_fill=(0,185,235,90))
        d.text((78,line_y),line,font=f,fill=(GOLD if i==len(lines)-1 else WHITE)+(255,),
               stroke_width=2,stroke_fill=(0,0,0,235))
    d.rounded_rectangle((78,504,418,563),radius=17,fill=(9,186,227,248),outline=(180,246,255,255),width=2)
    badge=(hook or "THE KEY TAKEAWAY").upper()[:24]
    badge_font=font(20)
    while d.textbbox((0,0),badge,font=badge_font)[2]>300 and badge_font.size>15:
        badge_font=font(badge_font.size-1)
    d.text((101,518),badge,font=badge_font,fill=NAVY+(255,))
    d.text((80,655),"RESEARCH  •  REAL-WORLD IMPACT  •  WHAT TO KNOW",font=font(17),fill=(181,216,239,255))
    scaled=subject.resize((int(W*1.6),int(H*1.6)),Image.Resampling.LANCZOS)
    img.alpha_composite(scaled.crop((600,165,600+W,165+H)))
    img=ImageEnhance.Contrast(img.convert("RGB")).enhance(1.08).filter(ImageFilter.UnsharpMask(radius=1.4,percent=145,threshold=2))
    output.parent.mkdir(parents=True,exist_ok=True); img.save(output,quality=95,optimize=True)
    with Image.open(output) as check:
        if check.size!=(1280,720): raise SystemExit(f"Thumbnail dimensions invalid: {check.size}")
        check.verify()
    return {"provider":"Python/Pillow only","effect":"8D-style multilayer text extrusion, topic-specific 3D hero, cinematic lighting and pop-out across bars","visual_focus":visual_focus}

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
    out=Path(args.output); result=make(title,out,hook,focus,visual_reason)
    print(json.dumps({"thumbnail":str(out),"dimensions":"1280x720","style":result["effect"],"image_provider":result["provider"],"creative_brief":"Groq" if brief_path.is_file() and hook else "local fallback","visual_focus":result["visual_focus"],"hook":hook or title}))

if __name__=="__main__": main()
