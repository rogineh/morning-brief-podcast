#!/usr/bin/env python3
"""Build pending Morning Brief episode(s) and publish into docs/. Run by the
.github/workflows/tts.yml Actions workflow, which has normal internet
access so edge-tts's real neural voices work (unlike the Claude sandbox
that writes the scripts, whose network policy blocks edge-tts).

Supports multiple independent shows (e.g. the main show and a bonus
"friend" show with no tech/AI segment), each with its own feed, docs
folder, and subscribe URL:

- The MAIN show is the flat scripts/pending/{en.txt,ko.txt,meta.json},
  published into docs/ at the site root (unchanged, original behaviour).
- Any OTHER show is a subdirectory scripts/pending/<show_id>/{en.txt,
  ko.txt,meta.json}. Its meta.json must include a "show" object:
    "show": {
      "docs_subdir": "friend",                          -- required
      "site_base": "https://.../morning-brief-podcast/friend",  -- required
      "channel_title": "Morning Brief — Australia Edition",     -- required (first episode only)
      "channel_description": "..."                              -- required (first episode only)
    }
  published into docs/<docs_subdir>/ with its own feed.xml/index.html.

meta.json (per episode): {"date": "YYYY-MM-DD", "title": "...", "description": "..."}
Optional fields:
  "slug": filename/guid identity distinct from "date" (e.g. "2026-09-13-extra"),
          for a same-day bonus episode that shouldn't overwrite the daily one.
  "pub_datetime": full ISO8601 datetime with offset to use as pubDate instead
          of the default <date>T06:30:00+10:00.
  "show": see above; omit for the main show.
"""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PENDING_ROOT = REPO_ROOT / "scripts" / "pending"
DOCS_DIR = REPO_ROOT / "docs"
MAIN_SITE_BASE = "https://rogineh.github.io/morning-brief-podcast"
MAIN_CHANNEL_TITLE = "Daily Brief — Morning Edition"
MAIN_CHANNEL_DESCRIPTION = (
    "A short daily news brief covering technology and AI, Australian "
    "national news, Queensland, and the Gold Coast — made to listen "
    "to on the morning drive."
)
AEST = timezone(timedelta(hours=10))
RETENTION_DAYS = 30

EN_VOICE = "en-AU-NatashaNeural"
KO_VOICE = "ko-KR-SunHiNeural"

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM_NS = "http://www.w3.org/2005/Atom"
ET.register_namespace("itunes", ITUNES_NS)
ET.register_namespace("atom", ATOM_NS)


def gh_output(name: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    with open(out, "a", encoding="utf-8") as f:
        delim = "GHADELIM"
        f.write(f"{name}<<{delim}\n{value}\n{delim}\n")


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def synthesize(voice: str, text_path: Path, out_path: Path) -> None:
    run(["edge-tts", "--voice", voice, "--file", str(text_path), "--write-media", str(out_path)])


def combine_audio(en_mp3: Path, ko_mp3: Path, out_mp3: Path) -> None:
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg", "-y",
        "-i", str(en_mp3),
        "-i", str(ko_mp3),
        "-f", "lavfi", "-t", "1.2", "-i", "anullsrc=r=24000:cl=mono",
        "-filter_complex", "[0:a][2:a][1:a]concat=n=3:v=0:a=1[out]",
        "-map", "[out]",
        "-codec:a", "libmp3lame", "-qscale:a", "4",
        str(out_mp3),
    ])


def load_feed(feed_path: Path, site_base: str, channel_title: str, channel_description: str) -> ET.ElementTree:
    if feed_path.exists():
        return ET.parse(feed_path)
    root = ET.Element("rss", {
        "version": "2.0",
        "xmlns:itunes": ITUNES_NS,
        "xmlns:atom": ATOM_NS,
    })
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = channel_title
    ET.SubElement(channel, "link").text = f"{site_base}/"
    atom_link = ET.SubElement(channel, f"{{{ATOM_NS}}}link")
    atom_link.set("href", f"{site_base}/feed.xml")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")
    ET.SubElement(channel, "description").text = channel_description
    ET.SubElement(channel, "language").text = "en-au"
    ET.SubElement(channel, f"{{{ITUNES_NS}}}author").text = channel_title
    ET.SubElement(channel, f"{{{ITUNES_NS}}}explicit").text = "false"
    cat = ET.SubElement(channel, f"{{{ITUNES_NS}}}category")
    cat.set("text", "News")
    return ET.ElementTree(root)


def item_pubdate(item: ET.Element) -> datetime | None:
    pd = item.find("pubDate")
    if pd is None or not pd.text:
        return None
    try:
        return parsedate_to_datetime(pd.text)
    except Exception:
        return None


def item_audio_filename(item: ET.Element) -> str | None:
    enc = item.find("enclosure")
    if enc is None:
        return None
    url = enc.get("url", "")
    return url.rsplit("/", 1)[-1] if url else None


def build_show(pending_dir: Path, docs_dir: Path, site_base: str,
                channel_title: str, channel_description: str) -> dict | None:
    en_txt = pending_dir / "en.txt"
    ko_txt = pending_dir / "ko.txt"
    meta_path = pending_dir / "meta.json"

    if not (en_txt.exists() and ko_txt.exists() and meta_path.exists()):
        return None

    audio_dir = docs_dir / "audio"
    feed_path = docs_dir / "feed.xml"
    index_path = docs_dir / "index.html"

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    date_str = meta["date"]
    title = meta["title"]
    description = meta["description"]
    slug = meta.get("slug", date_str)

    mp3_name = f"brief-{slug}.mp3"
    mp3_path = audio_dir / mp3_name

    tmp_en = Path(f"/tmp/brief-en-{slug}.mp3")
    tmp_ko = Path(f"/tmp/brief-ko-{slug}.mp3")
    synthesize(EN_VOICE, en_txt, tmp_en)
    synthesize(KO_VOICE, ko_txt, tmp_ko)
    combine_audio(tmp_en, tmp_ko, mp3_path)

    file_size = mp3_path.stat().st_size
    if "pub_datetime" in meta:
        pub_dt = datetime.fromisoformat(meta["pub_datetime"])
    else:
        pub_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=6, minute=30, second=0, tzinfo=AEST
        )
    guid_url = f"{site_base}/audio/{mp3_name}"

    tree = load_feed(feed_path, site_base, channel_title, channel_description)
    root = tree.getroot()
    channel = root.find("channel")

    new_item = ET.Element("item")
    ET.SubElement(new_item, "title").text = title
    ET.SubElement(new_item, "description").text = description
    ET.SubElement(new_item, "enclosure", {
        "url": guid_url,
        "type": "audio/mpeg",
        "length": str(file_size),
    })
    guid_el = ET.SubElement(new_item, "guid", {"isPermaLink": "false"})
    guid_el.text = guid_url
    ET.SubElement(new_item, "pubDate").text = format_datetime(pub_dt)

    existing_items = channel.findall("item")
    # drop any pre-existing item with the same filename (re-running for today)
    existing_items = [it for it in existing_items if item_audio_filename(it) != mp3_name]
    for it in existing_items:
        channel.remove(it)

    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    kept_items = [new_item]
    kept_audio_files = {mp3_name}
    for it in existing_items:
        pd = item_pubdate(it)
        if pd is not None and pd >= cutoff:
            kept_items.append(it)
            fn = item_audio_filename(it)
            if fn:
                kept_audio_files.add(fn)

    # remove all old <item> elements, then insert kept ones (new first) right after itunes:category
    for it in channel.findall("item"):
        channel.remove(it)
    insert_at = len(list(channel))
    for offset, it in enumerate(kept_items):
        channel.insert(insert_at + offset, it)

    ET.indent(tree, space="  ")
    tree.write(feed_path, encoding="UTF-8", xml_declaration=True)
    with open(feed_path, "a", encoding="utf-8") as f:
        f.write("\n")

    # prune audio files not referenced by any kept item
    if audio_dir.exists():
        for f in audio_dir.glob("brief-*.mp3"):
            if f.name not in kept_audio_files:
                print(f"Removing stale audio file {f.name}")
                f.unlink()

    if index_path.exists():
        html = index_path.read_text(encoding="utf-8")
        import re
        html = re.sub(
            r'(<p id="episode-title">).*?(</p>)',
            lambda m: m.group(1) + title.replace("Morning Brief — ", "").replace(f"{channel_title} — ", "") + m.group(2),
            html,
            count=1,
        )
        html = re.sub(
            r'(<audio[^>]*\bsrc=")[^"]*(")',
            lambda m: m.group(1) + f"audio/{mp3_name}" + m.group(2),
            html,
            count=1,
        )
        index_path.write_text(html, encoding="utf-8")

    for f in (en_txt, ko_txt, meta_path):
        f.unlink(missing_ok=True)

    print(f"Built {mp3_path} ({file_size} bytes)")
    return {"date": date_str, "description": description}


def main() -> int:
    built_any = False
    last_result: dict | None = None

    # Main show: flat scripts/pending/{en.txt,ko.txt,meta.json}
    result = build_show(PENDING_ROOT, DOCS_DIR, MAIN_SITE_BASE, MAIN_CHANNEL_TITLE, MAIN_CHANNEL_DESCRIPTION)
    if result is not None:
        built_any = True
        last_result = result

    # Any other show: scripts/pending/<show_id>/{en.txt,ko.txt,meta.json}
    if PENDING_ROOT.exists():
        for sub in sorted(PENDING_ROOT.iterdir()):
            if not sub.is_dir():
                continue
            meta_path = sub / "meta.json"
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            show = meta.get("show")
            if not show:
                print(f"Skipping {sub}: no pending files or no 'show' block in meta.json")
                continue
            docs_dir = DOCS_DIR / show["docs_subdir"]
            result = build_show(
                sub, docs_dir, show["site_base"],
                show.get("channel_title", "Morning Brief"),
                show.get("channel_description", ""),
            )
            if result is not None:
                built_any = True
                last_result = result

    if not built_any:
        print("No pending script found - nothing to do.")
        return 0

    gh_output("date", last_result["date"])
    gh_output("description", last_result["description"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
