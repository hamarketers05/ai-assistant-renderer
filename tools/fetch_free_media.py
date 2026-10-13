#!/usr/bin/env python3
"""Fetch scene-matched Full-HD image/video assets from conservative free-use APIs.

Enabled without additional keys: Wikimedia Commons, NASA Image and Video Library,
Openverse (CC0 only, with source-page confirmation).
Optional: Smithsonian Open Access (CC0 only; requires SMITHSONIAN_API_KEY).

Every downloaded item is recorded in work/asset_sources.jsonl for the existing
asset novelty guard. Unclear/NC/ND/licence-missing items and sub-Full-HD sources
are not automatically selected. No Pixabay or Pexels source is used.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

UA = "AI-Tech-Lab-Renderer/1.0 (https://github.com/hamarketers05/ai-assistant-renderer; licensed-media-fetcher)"
COMMONS = "https://commons.wikimedia.org/w/api.php"
NASA_SEARCH = "https://images-api.nasa.gov/search"
NASA_ASSET = "https://images-api.nasa.gov/asset/"
OPENVERSE = "https://api.openverse.org/v1/images/"
SMITHSONIAN = "https://api.si.edu/openaccess/api/v1.0/search"
MIN_W, MIN_H = 1920, 1080
MAX_BYTES = 80 * 1024 * 1024
MAX_IMAGE_ASSETS = 18
MAX_NASA_VIDEO_ASSETS = 3
MAX_COMMONS_IMAGE_ASSETS = 10
MAX_OPENVERSE_ASSETS = 4
STOP = set("""about above after again also although among another any are around because been before being between both but could did does doing down during each few for from further get got had has having here how into its itself just more most much must near new nor now off once only other our out over own same says should since some such than that the their them then these thing those through too under until use used using very was were what when where which while who why will would you your newest latest future explain explained technology artificial intelligence""".split())
API_COUNT = 0
LAST_API_CALL = 0.0
API_LIMIT = 95
SEARCH_CACHE: dict[str, list[dict[str, Any]]] = {}
INFO_CACHE: dict[str, dict[str, Any] | None] = {}


def request_bytes(url: str, *, max_bytes: int = MAX_BYTES, json_mode: bool = False) -> bytes | dict[str, Any]:
    global API_COUNT, LAST_API_CALL
    if API_COUNT >= API_LIMIT:
        raise RuntimeError("Free-media API request budget reached")
    # Keep requests polite, particularly to Wikimedia Commons.
    if "commons.wikimedia.org" in url:
        delay = 1.0 - (time.monotonic() - LAST_API_CALL)
        if delay > 0:
            time.sleep(delay)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, image/*, video/*, */*"})
    API_COUNT += 1
    LAST_API_CALL = time.monotonic()
    with urllib.request.urlopen(req, timeout=35) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > max_bytes:
            raise RuntimeError(f"Response exceeds {max_bytes} bytes")
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise RuntimeError(f"Response exceeds {max_bytes} bytes")
    if json_mode:
        return json.loads(data.decode("utf-8"))
    return data


def get_json(url: str) -> dict[str, Any]:
    result = request_bytes(url, json_mode=True)
    if not isinstance(result, dict):
        raise RuntimeError("API response was not a JSON object")
    return result


def tidy(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("value", "")
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def terms(text: str, limit: int = 8) -> list[str]:
    found = []
    for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}|\bAI\b|\bGPU\b|\bCPU\b", text or ""):
        token = word.lower()
        if token not in STOP and token not in found:
            found.append(token)
    return found[:limit]


def relevance(scene_text: str, title: str, description: str) -> float:
    wanted = set(terms(scene_text, 12))
    got = set(terms(title + " " + description, 18))
    if not wanted or not got:
        return 0.0
    overlap = len(wanted & got)
    return round(overlap / min(len(wanted), 6), 3)


def safe_scene(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(value or ""))[:80]


def https_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(str(value or ""))
    return parsed.scheme == "https" and bool(parsed.netloc)


def commons_license(meta: dict[str, Any]) -> tuple[bool, str, str, bool]:
    def field(name: str) -> str:
        return tidy(meta.get(name))
    label = field("LicenseShortName")
    url = field("LicenseUrl")
    corpus = (label + " " + url).lower()
    # Do not auto-use NonCommercial or NoDerivatives assets, and avoid share-alike
    # licenses in this pipeline because scene cropping/compositing makes adaptation obligations complex.
    if any(token in corpus for token in ("by-nc", "by-nd", "noncommercial", "non-commercial", "no derivatives", "no-derivatives", "/by-sa/")):
        return False, label or "Restricted/unclear", url, True
    if "cc0" in corpus or "public domain" in label.lower() or "creativecommons.org/publicdomain" in url.lower() or "pd-usgov" in label.lower():
        return True, label or "Public Domain/CC0", url, False
    if "creativecommons.org/licenses/by/" in url.lower() or re.search(r"\bcc\s*by(?:\s+4\.0|\s+3\.0)?\b", label.lower()):
        return True, label or "CC BY", url, True
    return False, label or "License missing/unclear", url, True


def exif_field(info: dict[str, Any], name: str) -> str:
    value = (info.get("extmetadata") or {}).get(name)
    return tidy(value)


def image_to_full_hd(raw: bytes, target: Path) -> tuple[int, int]:
    from io import BytesIO
    with Image.open(BytesIO(raw)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    source_size = image.size
    if image.width < MIN_W or image.height < MIN_H:
        raise ValueError(f"Native source is below Full HD ({image.width}x{image.height})")
    # Crop to 16:9 from source pixels; never upscale a smaller source and call it Full HD.
    image = ImageOps.fit(image, (1920, 1080), method=Image.Resampling.LANCZOS, centering=(0.5, 0.48))
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "JPEG", quality=95, optimize=True, progressive=True)
    with Image.open(target) as check:
        if check.size != (1920, 1080):
            raise ValueError(f"Normalized image is not 1920x1080: {check.size}")
    return source_size


def append_asset(record: dict[str, Any]) -> None:
    log = Path("work/asset_sources.jsonl")
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def download_image(url: str, target: Path) -> tuple[int, int, str]:
    raw = request_bytes(url)
    if not isinstance(raw, bytes):
        raise RuntimeError("Image download returned no bytes")
    digest = hashlib.sha256(raw).hexdigest()
    source_size = image_to_full_hd(raw, target)
    return source_size[0], source_size[1], digest


def commons_candidates(query: str) -> list[dict[str, Any]]:
    key = "commons:" + query.lower()
    if key in SEARCH_CACHE:
        return SEARCH_CACHE[key]
    params = {
        "action": "query", "format": "json", "list": "search", "srnamespace": 6,
        "srsearch": "filetype:bitmap " + query, "srlimit": 12, "srprop": "size|wordcount",
        "maxlag": 2,
    }
    data = get_json(COMMONS + "?" + urllib.parse.urlencode(params))
    results = (data.get("query") or {}).get("search") or []
    SEARCH_CACHE[key] = results
    return results


def commons_info(title: str) -> dict[str, Any] | None:
    if title in INFO_CACHE:
        return INFO_CACHE[title]
    params = {
        "action": "query", "format": "json", "titles": title, "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata", "formatversion": 2, "maxlag": 2,
    }
    data = get_json(COMMONS + "?" + urllib.parse.urlencode(params))
    pages = (data.get("query") or {}).get("pages") or []
    if not pages or "missing" in pages[0]:
        INFO_CACHE[title] = None
        return None
    infos = pages[0].get("imageinfo") or []
    result = {"page": pages[0], "info": infos[0]} if infos else None
    INFO_CACHE[title] = result
    return result


def fetch_commons_image(row: list[str], title: str, query: str) -> dict[str, Any] | None:
    scene = safe_scene(row[0])
    for result in commons_candidates(query)[:10]:
        file_title = str(result.get("title") or "")
        if not file_title or not re.search(r"\.(jpe?g|png|webp|tiff?)$", file_title, re.I):
            continue
        pair = commons_info(file_title)
        if not pair:
            continue
        info = pair["info"]
        if not str(info.get("mime") or "").lower().startswith("image/"):
            continue
        meta = info.get("extmetadata") or {}
        ok, license_label, license_url, attribution_required = commons_license(meta)
        if not ok:
            continue
        creator = exif_field(info, "Artist") or exif_field(info, "Credit") or exif_field(info, "Attribution")
        if attribution_required and not creator:
            continue
        width, height = int(info.get("width") or 0), int(info.get("height") or 0)
        if width < MIN_W or height < MIN_H:
            continue
        file_url = str(info.get("url") or "")
        source_url = str(info.get("descriptionurl") or "")
        desc = exif_field(info, "ImageDescription")
        score = relevance(" ".join(row[5:7]), file_title, desc)
        if score < 0.25 or not https_url(file_url) or not source_url.startswith("https://commons.wikimedia.org/"):
            continue
        target = Path(f"assets/free_media_scene_{scene}.jpg")
        try:
            source_w, source_h, digest = download_image(file_url, target)
        except Exception as exc:
            print(f"Commons image skipped for {scene}: {str(exc)[:100]}")
            target.unlink(missing_ok=True)
            continue
        return {
            "scene": scene, "provider": "Wikimedia Commons Image",
            "asset_id": file_title, "asset_title": file_title.removeprefix("File:"),
            "creator": creator or "Creator not identified (CC0/Public Domain)",
            "source_url": source_url, "license_label": license_label,
            "license_url": license_url, "attribution_required": attribution_required,
            "relevance_score": score, "matching_terms": terms(" ".join(row[5:7])),
            "commercial_use_allowed": True, "commercial_use_basis": "Per-file CC0/Public Domain/CC BY metadata; NC/ND/SA filtered",
            "asset_path": str(target), "source_width": source_w, "source_height": source_h,
            "output_resolution": "1920x1080", "sha256": digest,
        }
    return None


def source_page_confirms_cc0(url: str) -> bool:
    if not https_url(url):
        return False
    try:
        raw = request_bytes(url, max_bytes=2 * 1024 * 1024)
        if not isinstance(raw, bytes):
            return False
        page = raw.decode("utf-8", errors="ignore").lower()
        markers = (
            "creativecommons.org/publicdomain/zero/1.0",
            "cc0 1.0 universal",
            "public domain mark 1.0",
            "creativecommons public domain mark",
        )
        return any(marker in page for marker in markers)
    except Exception:
        return False


def fetch_openverse_image(row: list[str], query: str) -> dict[str, Any] | None:
    params = {"q": query, "license": "cc0,pdm", "page_size": 8, "aspect_ratio": "wide"}
    data = get_json(OPENVERSE + "?" + urllib.parse.urlencode(params))
    for item in data.get("results") or []:
        license_id = str(item.get("license") or "").lower()
        license_url = str(item.get("license_url") or "")
        source_url = str(item.get("foreign_landing_url") or "")
        if license_id not in {"cc0", "pdm"} or not https_url(source_url) or not https_url(license_url):
            continue
        if "publicdomain/zero/1.0" not in license_url.lower() and "publicdomain/mark/1.0" not in license_url.lower():
            continue
        # Openverse explicitly warns that catalogue license labels can be inaccurate;
        # do not download unless the original source page itself exposes the CC0/PD marker.
        if not source_page_confirms_cc0(source_url):
            continue
        url = str(item.get("url") or "")
        width, height = int(item.get("width") or 0), int(item.get("height") or 0)
        if not https_url(url) or width < MIN_W or height < MIN_H:
            continue
        creator = str(item.get("creator") or "").strip() or "Creator not listed; CC0/PD asset"
        score = relevance(" ".join(row[5:7]), str(item.get("title") or ""), str(item.get("title") or ""))
        if score < 0.25:
            continue
        target = Path(f"assets/free_media_scene_{safe_scene(row[0])}.jpg")
        try:
            source_w, source_h, digest = download_image(url, target)
        except Exception as exc:
            target.unlink(missing_ok=True)
            print(f"Openverse image skipped for {row[0]}: {str(exc)[:100]}")
            continue
        return {
            "scene": safe_scene(row[0]), "provider": "Openverse CC0/PD Image",
            "asset_id": str(item.get("id") or source_url), "asset_title": str(item.get("title") or ""),
            "creator": creator, "source_url": source_url,
            "license_label": "CC0/Public Domain (original source page confirmed)",
            "license_url": license_url, "attribution_required": False,
            "relevance_score": score, "matching_terms": terms(" ".join(row[5:7])),
            "commercial_use_allowed": True, "commercial_use_basis": "CC0/PD marker confirmed on original source page",
            "asset_path": str(target), "source_width": source_w, "source_height": source_h,
            "output_resolution": "1920x1080", "sha256": digest,
        }
    return None


def nasa_rights_ok(metadata: dict[str, Any]) -> bool:
    combined = " ".join(str(v) for v in metadata.values()).lower()
    # Exclude explicit third-party copyright notices and human/brand/logo-dependent media.
    blocked = ("copyrighted", "all rights reserved", "licensed from", "courtesy of esa",
               "© esa", "© jaxa", "copyright:", "logo", "insignia", "portrait",
               "employee portrait", "identifiable crew", "celebrity")
    if any(token in combined for token in blocked):
        return False
    return True


def nasa_asset_files(nasa_id: str) -> list[str]:
    data = get_json(NASA_ASSET + urllib.parse.quote(nasa_id, safe=""))
    items = data.get("collection", {}).get("items") or []
    links = [str(x.get("href") or "") for x in items if isinstance(x, dict)]
    return [u for u in links if https_url(u)]


def fetch_nasa_image(row: list[str], query: str, *, want_video: bool = False) -> dict[str, Any] | None:
    params = {"q": query, "media_type": "video" if want_video else "image", "page_size": 8}
    data = get_json(NASA_SEARCH + "?" + urllib.parse.urlencode(params))
    items = data.get("collection", {}).get("items") or []
    for candidate in items:
        metadata_list = candidate.get("data") or []
        if not metadata_list:
            continue
        metadata = metadata_list[0]
        if not nasa_rights_ok(metadata):
            continue
        title = str(metadata.get("title") or "")
        description = str(metadata.get("description") or metadata.get("description_508") or "")
        score = relevance(" ".join(row[5:7]), title, description)
        if score < 0.25:
            continue
        nasa_id = str(metadata.get("nasa_id") or "")
        if not nasa_id:
            continue
        source_url = "https://images.nasa.gov/details/" + urllib.parse.quote(nasa_id, safe="")
        try:
            files = nasa_asset_files(nasa_id)
        except Exception:
            continue
        if want_video:
            candidates = [u for u in files if re.search(r"\.(mp4|mov|m4v)$", urllib.parse.urlparse(u).path, re.I)]
            for url in candidates:
                target = Path(f"assets/scene_{safe_scene(row[0])}.mp4")
                try:
                    raw = request_bytes(url)
                    if not isinstance(raw, bytes) or len(raw) < 100_000:
                        continue
                    source = Path(f"work/nasa_{safe_scene(row[0])}.mp4")
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_bytes(raw)
                    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                             "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(source)],
                                            capture_output=True, text=True, check=True, timeout=20).stdout.strip()
                    dims = probe.split("x")
                    if len(dims) != 2 or int(dims[0]) < MIN_W or int(dims[1]) < MIN_H:
                        continue
                    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                                    "-t", "30", "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=30,setsar=1",
                                    "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
                                    "-movflags", "+faststart", str(target)], check=True, timeout=180)
                    return {
                        "scene": safe_scene(row[0]), "provider": "NASA Image and Video Library",
                        "asset_id": nasa_id, "asset_title": title, "creator": "NASA",
                        "source_url": source_url, "license_label": "NASA informational/editorial media use",
                        "license_url": "https://www.nasa.gov/nasa-brand-center/images-and-media/",
                        "attribution_required": True, "relevance_score": score,
                        "matching_terms": terms(" ".join(row[5:7])),
                        "commercial_use_allowed": True,
                        "commercial_use_basis": "NASA informational/editorial published work only; no endorsement, logo, or person-dependent use",
                        "asset_path": str(target), "source_width": int(dims[0]), "source_height": int(dims[1]),
                        "output_resolution": "1920x1080", "source_media_url": url,
                    }
                except Exception as exc:
                    target.unlink(missing_ok=True)
                    print(f"NASA video skipped for {row[0]}: {str(exc)[:100]}")
            continue
        candidates = [u for u in files if re.search(r"\.(jpe?g|png|webp)$", urllib.parse.urlparse(u).path, re.I)]
        for url in candidates:
            target = Path(f"assets/free_media_scene_{safe_scene(row[0])}.jpg")
            try:
                source_w, source_h, digest = download_image(url, target)
            except Exception:
                target.unlink(missing_ok=True)
                continue
            return {
                "scene": safe_scene(row[0]), "provider": "NASA Image and Video Library",
                "asset_id": nasa_id, "asset_title": title, "creator": "NASA",
                "source_url": source_url, "license_label": "NASA informational/editorial media use",
                "license_url": "https://www.nasa.gov/nasa-brand-center/images-and-media/",
                "attribution_required": True, "relevance_score": score,
                "matching_terms": terms(" ".join(row[5:7])),
                "commercial_use_allowed": True,
                "commercial_use_basis": "NASA informational/editorial published work only; no endorsement, logo, or person-dependent use",
                "asset_path": str(target), "source_width": source_w, "source_height": source_h,
                "output_resolution": "1920x1080", "sha256": digest,
            }
    return None


def fetch_smithsonian_image(row: list[str], query: str, api_key: str) -> dict[str, Any] | None:
    # Smithsonian's official policy grants commercial reuse to assets explicitly marked CC0 only.
    params = {"q": query, "rows": 10, "api_key": api_key}
    data = get_json(SMITHSONIAN + "?" + urllib.parse.urlencode(params))
    records = data.get("response", {}).get("rows") or []
    for record in records:
        content = record.get("content") or {}
        if content.get("freetouse") not in (True, "true", "True", 1):
            continue
        descriptive = content.get("descriptiveNonRepeating") or {}
        online = descriptive.get("online_media") or {}
        media_items = online.get("media") or []
        title = tidy(descriptive.get("title") or record.get("title") or "")
        guid = tidy(descriptive.get("record_link") or descriptive.get("guid") or record.get("id") or "")
        if not https_url(guid):
            guid = "https://www.si.edu/object/" + urllib.parse.quote(str(record.get("id") or ""), safe="")
        score = relevance(" ".join(row[5:7]), title, json.dumps(content.get("indexedStructured") or {}))
        if score < 0.25:
            continue
        for media in media_items:
            url = str(media.get("content") or media.get("thumbnail") or "")
            if not https_url(url):
                continue
            target = Path(f"assets/free_media_scene_{safe_scene(row[0])}.jpg")
            try:
                source_w, source_h, digest = download_image(url, target)
            except Exception:
                target.unlink(missing_ok=True)
                continue
            creator = tidy(content.get("freetouse") and (content.get("indexedStructured") or {}).get("name")) or "Creator not identified; Smithsonian CC0 asset"
            return {
                "scene": safe_scene(row[0]), "provider": "Smithsonian Open Access CC0",
                "asset_id": str(record.get("id") or guid), "asset_title": title,
                "creator": creator, "source_url": guid,
                "license_label": "CC0 1.0 (Smithsonian Open Access free-to-use flag)",
                "license_url": "https://www.si.edu/openaccess/faq",
                "attribution_required": False, "relevance_score": score,
                "matching_terms": terms(" ".join(row[5:7])),
                "commercial_use_allowed": True,
                "commercial_use_basis": "Smithsonian policy; accepted only when record is explicitly marked free-to-use/CC0",
                "asset_path": str(target), "source_width": source_w, "source_height": source_h,
                "output_resolution": "1920x1080", "sha256": digest,
            }
    return None


def report(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        ok, label, _, attribution = commons_license({"LicenseShortName": {"value": "CC BY 4.0"}, "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0/"}})
        blocked, _, _, _ = commons_license({"LicenseShortName": {"value": "CC BY-NC 4.0"}, "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-nc/4.0/"}})
        assert ok and label and attribution and not blocked
        assert relevance("AI chip data center", "AI chip compute data center", "") >= 0.5
        assert not source_page_confirms_cc0("http://invalid.example")
        print(json.dumps({"status": "self_test_passed", "license_gate": "CC0/Public Domain/CC BY only; NC/ND/SA blocked", "image_resolution_gate": "native 1920x1080 minimum"}))
        return

    scenes_path = Path("work/scenes.tsv")
    if not scenes_path.is_file():
        raise SystemExit("Missing work/scenes.tsv")
    rows = [line.split("\t") for line in scenes_path.read_text(encoding="utf-8").splitlines() if line.strip() and len(line.split("\t")) >= 7]
    title = Path("work/title.txt").read_text(encoding="utf-8").strip() if Path("work/title.txt").is_file() else ""
    downloaded, providers, skipped = [], {}, {"low_resolution": 0, "license_or_relevance": 0, "provider_errors": 0}
    smithsonian_key = os.getenv("SMITHSONIAN_API_KEY", "").strip()
    max_total = MAX_IMAGE_ASSETS + MAX_OPENVERSE_ASSETS + 4

    # NASA videos are only selected when the scene itself semantically matches the source;
    # existing Vecteezy/Wikimedia clips are never overwritten.
    nasa_video_count = 0
    for row in rows:
        scene = safe_scene(row[0])
        if Path(f"assets/scene_{scene}.mp4").is_file() or nasa_video_count >= MAX_NASA_VIDEO_ASSETS:
            continue
        query = " ".join(terms(" ".join(row[5:7]) + " " + title, 5))
        if not query or not re.search(r"space|satellite|orbit|solar|planet|moon|mars|rocket|spacecraft|earth observation", query, re.I):
            continue
        try:
            item = fetch_nasa_image(row, query, want_video=True)
            if item:
                append_asset(item); downloaded.append(item); nasa_video_count += 1
                providers[item["provider"]] = providers.get(item["provider"], 0) + 1
        except Exception as exc:
            skipped["provider_errors"] += 1
            print(f"NASA video search skipped for {scene}: {str(exc)[:100]}")

    image_count = 0
    for row in rows:
        if image_count >= max_total:
            break
        scene = safe_scene(row[0])
        target = Path(f"assets/free_media_scene_{scene}.jpg")
        if target.exists() or Path(f"assets/scene_{scene}.mp4").exists():
            continue
        scene_text = " ".join(row[5:7]).strip()
        query = " ".join(terms(scene_text + " " + title, 6))
        if len(query.split()) < 2:
            continue
        candidates = []
        for provider_name, fetcher in (
            ("Wikimedia Commons Image", lambda: fetch_commons_image(row, title, " ".join(terms(scene_text, 6)))),
            ("Openverse CC0/PD Image", lambda: fetch_openverse_image(row, " ".join(terms(scene_text, 5)))),
            ("NASA Image and Video Library", lambda: fetch_nasa_image(row, " ".join(terms(scene_text, 5)), want_video=False)),
        ):
            # Provider quotas keep acquisition supplemental; exact relevance/licence beats quantity.
            limit = MAX_COMMONS_IMAGE_ASSETS if provider_name.startswith("Wikimedia") else MAX_OPENVERSE_ASSETS if provider_name.startswith("Openverse") else 4
            if providers.get(provider_name, 0) >= limit:
                continue
            try:
                item = fetcher()
                if item:
                    candidates.append(item)
                    break
            except Exception as exc:
                skipped["provider_errors"] += 1
                print(f"{provider_name} search skipped for {scene}: {str(exc)[:100]}")
        if not candidates and smithsonian_key and providers.get("Smithsonian Open Access CC0", 0) < 4:
            try:
                item = fetch_smithsonian_image(row, " ".join(terms(scene_text, 5)), smithsonian_key)
                if item:
                    candidates.append(item)
            except Exception as exc:
                skipped["provider_errors"] += 1
                print(f"Smithsonian search skipped for {scene}: {str(exc)[:100]}")
        if candidates:
            item = candidates[0]
            append_asset(item); downloaded.append(item)
            provider = item["provider"]
            providers[provider] = providers.get(provider, 0) + 1
            image_count += 1
            print(f"Verified Full-HD image for scene {scene}: {provider} — {item.get('asset_title','')}")
        else:
            skipped["license_or_relevance"] += 1

    data = {
        "status": "completed" if downloaded else "no_eligible_assets",
        "scenes_considered": len(rows), "assets_downloaded": len(downloaded),
        "image_assets_downloaded": image_count, "nasa_video_assets_downloaded": nasa_video_count,
        "providers": providers, "skipped": skipped,
        "native_resolution_requirement": "Source must be at least 1920x1080 before 16:9 normalization; smaller sources are rejected.",
        "license_policy": "Wikimedia CC0/Public Domain/CC BY only (no NC/ND/SA); Openverse CC0/PD only with original source-page marker; Smithsonian explicit CC0/free-to-use only; NASA informational/editorial assets exclude explicit third-party rights/person/brand dependencies.",
        "optional_provider": "Smithsonian Open Access is queried only when SMITHSONIAN_API_KEY is configured; no key is required for Wikimedia, NASA or Openverse.",
        "output_resolution": "1920x1080",
        "assets": downloaded,
    }
    report(Path("work/visual_media_report.json"), data)


if __name__ == "__main__":
    main()
