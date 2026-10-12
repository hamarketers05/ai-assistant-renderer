#!/usr/bin/env python3
"""Create original, script-matched illustrated visuals when licensed footage is unavailable.
All diagrams are illustrative, not factual measurements; no external image assets are used.
"""
import csv, hashlib, os, re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W,H=1920,1080
OUT=Path("assets"); OUT.mkdir(exist_ok=True)
font_path="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
bold_path="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
def font(size,bold=False):
    return ImageFont.truetype(bold_path if bold else font_path,size)
def wrap(draw,text,f,maxw):
    words=re.sub(r"\s+"," ",text).strip().split()
    lines=[]; line=""
    for word in words:
        trial=(line+" "+word).strip()
        if draw.textbbox((0,0),trial,font=f)[2] <= maxw: line=trial
        else:
            if line: lines.append(line)
            line=word
    if line: lines.append(line)
    return lines[:3]
def rounded(draw,box,r,fill,outline=None,width=2):
    draw.rounded_rectangle(box,radius=r,fill=fill,outline=outline,width=width)
def line(draw,points,fill=(0,220,255),width=5):
    draw.line(points,fill=fill,width=width,joint="curve")
def make_icon(draw,kind,cx,cy):
    c=(0,220,255); pale=(160,235,255); white=(236,247,255)
    if any(k in kind for k in ("privacy","security","safe","protect","risk")):
        pts=[(cx,cy-155),(cx+125,cy-105),(cx+105,cy+55),(cx,cy+145),(cx-105,cy+55),(cx-125,cy-105),(cx,cy-155)]
        line(draw,pts,c,12); line(draw,[(cx-55,cy-5),(cx-12,cy+38),(cx+65,cy-48)],white,15)
        rounded(draw,(cx+175,cy-70,cx+285,cy+55),18,(8,40,70),c,5)
        draw.arc((cx+202,cy-115,cx+258,cy-15),180,360,fill=pale,width=10)
    elif any(k in kind for k in ("cloud","server","internet","remote")):
        draw.ellipse((cx-145,cy-45,cx-35,cy+65),fill=(8,53,86),outline=c,width=7)
        draw.ellipse((cx-60,cy-105,cx+70,cy+65),fill=(8,53,86),outline=c,width=7)
        draw.ellipse((cx+20,cy-50,cx+150,cy+65),fill=(8,53,86),outline=c,width=7)
        rounded(draw,(cx-120,cy+5,cx+125,cy+75),22,(8,53,86),c,5)
        for yy in (cy+115,cy+160,cy+205):
            rounded(draw,(cx-115,yy,cx+115,yy+27),8,(10,38,68),pale,3)
    elif any(k in kind for k in ("graph","chart","performance","speed","compare","benchmark","data")):
        rounded(draw,(cx-190,cy-150,cx+190,cy+180),20,(7,29,55),c,4)
        for yy in (cy-75,cy,cy+75): line(draw,[(cx-150,yy),(cx+150,yy)],(34,70,96),2)
        bars=[(cx-115,cy+70,cx-65,cy+135),(cx-35,cy+5,cx+15,cy+135),(cx+45,cy-65,cx+95,cy+135)]
        for b in bars: rounded(draw,b,8,(0,140,205),pale,2)
        line(draw,[(cx-135,cy-65),(cx-40,cy-20),(cx+30,cy-90),(cx+135,cy-130)],(255,190,75),8)
    elif any(k in kind for k in ("network","neural","model","agent","workflow","brain","learn")):
        pts=[(cx-130,cy-90),(cx-145,cy+10),(cx-100,cy+115),(cx,cy-135),(cx+15,cy-20),(cx+100,cy+95),(cx+145,cy-70)]
        edges=[(0,3),(0,4),(1,3),(1,4),(1,2),(2,4),(2,5),(3,4),(3,6),(4,5),(4,6),(5,6)]
        for a,b in edges: line(draw,[pts[a],pts[b]],(26,112,150),4)
        for x,y in pts: draw.ellipse((x+cx-7,y+cy-7,x+cx+7,y+cy+7),fill=white,outline=c,width=4)
        for j,label in enumerate(("INPUT","MODEL","OUTPUT")):
            rounded(draw,(cx-225+j*155,cy+190,cx-100+j*155,cy+235),12,(7,38,65),c,2)
            draw.text((cx-212+j*155,cy+199),label,font=font(17,True),fill=white)
    else:
        # Original laptop + compute chip illustration.
        rounded(draw,(cx-205,cy-145,cx+205,cy+100),20,(5,24,46),c,8)
        rounded(draw,(cx-175,cy-115,cx+175,cy+70),12,(8,53,86),pale,3)
        # circuit traces on screen
        for k in range(5):
            x=cx-125+k*62
            line(draw,[(x,cy-80),(x,cy-25),(cx,cy+5)],(18,137,177),3)
            draw.ellipse((x-7,cy-88,x+7,cy-74),fill=(255,190,75))
        line(draw,[(cx-245,cy+125),(cx+245,cy+125),(cx+190,cy+165),(cx-190,cy+165),(cx-245,cy+125)],pale,7)
        rounded(draw,(cx-70,cy+185,cx+70,cy+255),14,(7,38,65),c,4)
        draw.text((cx-54,cy+204),"AI CHIP",font=font(25,True),fill=white)
def main():
    rows=list(csv.reader(open("work/scenes.tsv",encoding="utf-8"),delimiter="\t"))
    if not rows: raise SystemExit("No scene plan found for visual generation.")
    title=Path("work/title.txt").read_text(encoding="utf-8").strip() or "AI TECH LAB"
    made=0
    for i,row in enumerate(rows):
        if len(row)<7: continue
        scene=re.sub(r"[^a-zA-Z0-9_-]","_",row[0])[:80]
        kind=(row[4]+" "+row[5]+" "+row[6]).lower()
        content_seed=os.getenv("CONTENT_ID","unique-video")
        digest=hashlib.sha256((content_seed+scene+kind+title).encode()).digest()
        accent=(0,190+digest[0]%50,220+digest[1]%35)
        img=Image.new("RGB",(W,H))
        px=img.load()
        for y in range(H):
            t=y/H
            col=(3+int(4*t),10+int(18*t),27+int(28*t))
            for x in range(W): px[x,y]=col
        d=ImageDraw.Draw(img,"RGBA")
        # Circuit pattern and luminous nodes give each frame visual texture.
        for x in range(80,W,160):
            d.line((x,120,x,930),fill=(10,70,105,110),width=2)
            for y in range(140,940,160):
                d.ellipse((x-5,y-5,x+5,y+5),fill=(*accent,150))
        d.rounded_rectangle((55,55,W-55,H-55),radius=34,outline=(*accent,220),width=3)
        d.text((100,78),"AI TECH LAB  /  EXPLAINED",font=font(27,True),fill=(*accent,255))
        head=(row[6] or row[5] or title).strip()
        d.multiline_text((100,130),"\n".join(wrap(d,head,font(43,True),750)),font=font(43,True),fill=(245,250,255,255),spacing=12)
        make_icon(d,kind,1190,505)
        # Side information panel tied to this scene's own visual/narration description.
        rounded(d,(100,350,760,790),28,(5,26,48,235),(*accent,230),3)
        d.text((145,390),"WHAT THIS MEANS",font=font(25,True),fill=(*accent,255))
        desc=(row[5] or row[6] or title).strip()
        for j,txt in enumerate(wrap(d,desc,font(29),550)):
            d.text((145,450+j*47),txt,font=font(29),fill=(224,238,250,255))
        labels=["LOCAL COMPUTE","CLOUD CONNECTION","DATA & MODEL","PRACTICAL TRADE-OFFS"]
        label=labels[i%len(labels)]
        rounded(d,(100,835,650,915),18,(5,42,68,240),(*accent,220),3)
        d.text((132,855),label,font=font(25,True),fill=(245,250,255,255))
        # Diagram nodes and arrows; illustrative, not fabricated measurements.
        for j in range(3):
            xx=900+j*205
            rounded(d,(xx,850,xx+155,920),15,(7,34,60,245),(*accent,220),3)
            d.text((xx+15,870),["INPUT","PROCESS","RESULT"][j],font=font(20,True),fill=(245,250,255,255))
            if j<2: line(d,[(xx+158,885),(xx+195,885)],accent,5)
        footer="ILLUSTRATIVE DIAGRAM • NOT A MEASURED BENCHMARK"
        d.text((100,970),footer,font=font(18,True),fill=(145,184,205,255))
        img.save(OUT/f"generated_scene_{scene}.png",quality=95)
        # Transparent lower-third overlay for real footage, driven by this scene's own sentence.
        overlay=Image.new("RGBA",(W,H),(0,0,0,0))
        glow=Image.new("RGBA",(W,H),(0,0,0,0))
        gd=ImageDraw.Draw(glow,"RGBA")
        gd.rounded_rectangle((72,842,1230,1015),radius=26,outline=(*accent,185),width=7)
        overlay.alpha_composite(glow.filter(ImageFilter.GaussianBlur(18)))
        od=ImageDraw.Draw(overlay,"RGBA")
        od.rounded_rectangle((72,842,1230,1015),radius=26,fill=(2,12,30,218),outline=(*accent,235),width=4)
        od.text((108,866),"AI TECH LAB  /  KEY IDEA",font=font(23,True),fill=(*accent,255))
        caption=" ".join(wrap(od,head,font(35,True),1040)[:2])
        od.text((108,910),caption,font=font(35,True),fill=(247,250,255,255),stroke_width=1,stroke_fill=(0,0,0,200))
        overlay.save(OUT/f"scene_overlay_{scene}.png")
        made+=1
    if made<4: raise SystemExit(f"Visual QA failed: only {made} script-matched scenes generated.")
    print(f"Script-matched illustrated scene assets generated: {made}; topic-specific iconography and diagrams included.")
if __name__=="__main__": main()
