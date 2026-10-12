#!/usr/bin/env python3
"""Fetch scene-relevant, commercially usable video from Wikimedia Commons, preserving license records."""
from __future__ import annotations
import html, json, re, subprocess, time, urllib.parse, urllib.request
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
UA = "AI-Tech-Lab-Renderer/1.0 (https://github.com/hamarketers05/ai-assistant-renderer)"
MAX_SCENES, MAX_DOWNLOADS = 48, 16
MAX_BYTES = 80 * 1024 * 1024
STOP = set("""about above after again also although among another any are around because been before being between both but can could did does doing down during each few for from further get got had has have having here how into its itself just more most much must near new nor not now off once only other our out over own same says should since some such than that the their them then there these they thing this those through too under until use used using very was were what when where which while who why will with would your you and the for from with into onto how why when then than that this these those real latest technology artificial intelligence explain explained explains""".split())
VIDEO_EXTS = {".mp4", ".webm", ".ogv", ".ogg", ".mov", ".m4v"}

def clean(value):
    if isinstance(value, dict):
        value = value.get("value", "")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))).strip()

def req_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        if response.status != 200: raise RuntimeError(f"Commons API HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))

def terms_of(text):
    out = []
    for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", text.lower()):
        if word not in STOP and word not in out: out.append(word)
    return out[:8]

def license_ok(label, url):
    label_low = re.sub(r"\s+", " ", label.lower()).strip()
    url_low = url.lower()
    all_text = label_low + " " + url_low
    if any(x in all_text for x in ("by-nc", "by-nd", "noncommercial", "non-commercial", "no derivatives", "no-derivatives")):
        return False, label or "Unverified license", True
    if "public domain" in label_low or "cc0" in label_low or "creativecommons.org/publicdomain" in url_low or "pd-usgov" in label_low:
        return True, label or "Public domain", False
    if "creativecommons.org/licenses/by/" in url_low or "creativecommons.org/licenses/by-sa/" in url_low:
        return True, label or ("CC BY-SA" if "/by-sa/" in url_low else "CC BY"), True
    if re.search(r"\bcc\s*by(?:\s*-?sa)?\b", label_low) and "nc" not in label_low and "nd" not in label_low:
        return True, label, True
    return False, label or "License missing", True

def meta_field(meta, key):
    val = meta.get(key, {})
    return clean(val.get("value", "") if isinstance(val, dict) else val)

def search_files(query):
    params = {"action":"query","format":"json","list":"search",
              "srsearch":f"filetype:video {query}","srnamespace":6,"srlimit":20,"srprop":"size|wordcount"}
    data = req_json(API + "?" + urllib.parse.urlencode(params))
    return (data.get("query") or {}).get("search") or []

def file_info(title):
    params = {"action":"query","format":"json","titles":title,"prop":"imageinfo",
              "iiprop":"url|mime|size|extmetadata","formatversion":2}
    data = req_json(API + "?" + urllib.parse.urlencode(params))
    pages = (data.get("query") or {}).get("pages") or []
    if not pages or "missing" in pages[0]: return None
    infos = pages[0].get("imageinfo") or []
    return {"page":pages[0],"info":infos[0]} if infos else None

def fetch_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_BYTES: raise RuntimeError("File exceeds 80 MiB")
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES: raise RuntimeError("File exceeds 80 MiB")
        return data

def main():
    scenes = Path("work/scenes.tsv")
    if not scenes.is_file(): raise SystemExit("Missing work/scenes.tsv.")
    log = Path("work/asset_sources.jsonl"); log.parent.mkdir(parents=True, exist_ok=True); log.touch(exist_ok=True)
    rows = [line.rstrip("\n").split("\t") for line in scenes.read_text(encoding="utf-8").splitlines() if line.strip()]
    downloaded, checked, skipped = 0, 0, 0
    for row in rows[:MAX_SCENES]:
        if len(row) < 7 or downloaded >= MAX_DOWNLOADS: continue
        scene = re.sub(r"[^A-Za-z0-9_-]", "_", row[0])[:80]
        target = Path(f"assets/scene_{scene}.mp4")
        if target.is_file() and target.stat().st_size > 10000: continue
        query_text = re.sub(r"\s+", " ", f"{row[5]} {row[6]}").strip()
        terms = terms_of(query_text)
        if len(terms) < 2: continue
        selected = None
        seen = set()
        query_candidates = [
            " ".join(terms[:5]),
            " ".join(terms[:3]),
            " ".join(terms[:2]),
            "computer security",
            "cybersecurity network",
            "computer server data center",
            "computer code software",
            "artificial intelligence computer",
            "digital technology office",
            "network cables server",
        ]
        # Deduplicate while preserving query order; broad fallback searches are still
        # required to pass the per-scene title/description relevance test below.
        query_candidates = list(dict.fromkeys(q.strip() for q in query_candidates if q.strip()))
        for query in query_candidates:
            try: results = search_files(query)
            except Exception as exc:
                print(f"Commons search failed for scene {scene}: {str(exc)[:140]}"); continue
            for result in results:
                title = str(result.get("title") or "")
                if not title or title in seen or not re.search(r"\.(mp4|webm|ogv|ogg|mov|m4v)$", title, re.I): continue
                seen.add(title)
                try:
                    pair = file_info(title)
                    if not pair: continue
                    page, info = pair["page"], pair["info"]
                    if not str(info.get("mime") or "").lower().startswith("video/"): continue
                    file_url = str(info.get("url") or "")
                    if Path(urllib.parse.urlparse(file_url).path).suffix.lower() not in VIDEO_EXTS: continue
                    meta = info.get("extmetadata") or {}
                    label, license_url = meta_field(meta,"LicenseShortName"), meta_field(meta,"LicenseUrl")
                    ok, normalized, attribution = license_ok(label, license_url)
                    if not ok:
                        print(f"Commons skipped {title}: not a verified commercial-use license."); continue
                    creator = meta_field(meta,"Artist") or meta_field(meta,"Credit") or meta_field(meta,"Attribution")
                    if attribution and not creator:
                        print(f"Commons skipped {title}: the attribution-required license has no creator metadata.")
                        continue
                    desc = meta_field(meta,"ImageDescription")
                    title_terms = set(terms_of(title.replace("File:"," ")))
                    desc_terms = set(terms_of(desc))
                    overlap = len(set(terms) & (title_terms | desc_terms)) / max(1,min(5,len(terms)))
                    if overlap < 0.20: continue
                    source_url = str(info.get("descriptionurl") or "")
                    if not file_url.startswith("https://") or not source_url.startswith("https://commons.wikimedia.org/"): continue
                    size = int(info.get("size") or 0)
                    if size and size > MAX_BYTES: continue
                    selected = {"title":title,"file_url":file_url,"source_url":source_url,
                                "creator":creator,"license":normalized,"license_url":license_url,
                                "attribution":attribution,"relevance_score":round(overlap,3)}
                    break
                except Exception as exc:
                    print(f"Commons metadata skipped for scene {scene}: {str(exc)[:120]}")
                finally: checked += 1
            if selected: break
            time.sleep(0.25)
        if not selected:
            skipped += 1; print(f"No verified, scene-relevant Commons clip for scene {scene}."); continue
        try:
            data = fetch_bytes(selected["file_url"])
            if len(data) < 10000: raise RuntimeError("Video payload too small")
            ext = Path(urllib.parse.urlparse(selected["file_url"]).path).suffix.lower() or ".webm"
            source = Path(f"work/commons_{scene}{ext}"); source.write_bytes(data)
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-i",str(source),
                "-t","30","-vf","scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=30,setsar=1",
                "-an","-c:v","libx264","-preset","veryfast","-crf","24","-pix_fmt","yuv420p",
                "-movflags","+faststart",str(target)], check=True, timeout=180)
            if not target.is_file() or target.stat().st_size < 10000: raise RuntimeError("FFmpeg output is not usable")
            item = {"scene":scene,"provider":"Wikimedia Commons","asset_title":selected["title"].removeprefix("File:"),
                    "creator":selected["creator"] or "Creator not listed in source metadata",
                    "source_url":selected["source_url"],"license_label":selected["license"],
                    "license_url":selected["license_url"],"attribution_required":selected["attribution"],
                    "relevance_score":selected["relevance_score"],
                    "query":" ".join(terms[:5]),"commercial_use_allowed":True}
            with log.open("a",encoding="utf-8") as out: out.write(json.dumps(item,ensure_ascii=False)+"\n")
            downloaded += 1; print(f"Commons clip used for scene {scene}: {selected['title']}")
        except Exception as exc:
            target.unlink(missing_ok=True); print(f"Commons download failed for scene {scene}: {str(exc)[:140]}")
    report = {"provider":"Wikimedia Commons","scenes_considered":len(rows[:MAX_SCENES]),
              "metadata_items_checked":checked,"clips_downloaded":downloaded,
              "scenes_without_licensed_footage":skipped,"free_only_policy":True}
    Path("work/commons_media_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))

if __name__ == "__main__":
    main()
