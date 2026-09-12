#!/usr/bin/env python3
"""Build today's Morning Brief episode from scripts/pending/ and publish it
into docs/ (audio file, feed.xml, index.html). Run by the
.github/workflows/tts.yml Actions workflow, which has normal internet
access so edge-tts's real neural voices work (unlike the Claude sandbox
that writes the scripts, whose network policy blocks edge-tts).

Expects scripts/pending/en.txt, scripts/pending/ko.txt, scripts/pending/meta.json.
meta.json: {"date": "YYYY-MM-DD", "title": "...", "description": "..."}
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
PENDING_DIR = REPO_ROOT / "scripts" / "pending"
DOCS_DIR = REPO_ROOT / "docs"
AUDIO_DIR = DOCS_DIR / "audio"
FEED_PATH = DOCS_DIR / "feed.xml"
INDEX_PATH = DOCS_DIR / "index.html"
SITE_BASE = "https://rogineh.github.io/morning-brief-podcast"
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


def load_feed() -> ET.ElementTree:
    if FEED_PATH.exists():
        return ET.parse(FEED_PATH)
    root = ET.Element("rss", {
        "version": "2.0",
        "xmlns:itunes": ITUNES_NS,
        "xmlns:atom": ATOM_NS,
    })
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "Morning Brief"
    ET.SubElement(channel, "link").text = f"{SITE_BASE}/"
    atom_link = ET.SubElement(channel, f"{{{ATOM_NS}}}link")
    atom_link.set("href", f"{SITE_BASE}/feed.xml")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")
    ET.SubElement(channel, "description").text = (
        "A short daily news brief covering technology and AI, Australian "
        "national news, Queensland, and the Gold Coast — made to listen "
        "to on the morning drive."
    )
    ET.SubElement(channel, "language").text = "en-au"
    ET.SubElement(channel, f"{{{ITUNES_NS}}}author").text = "Morning Brief"
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


def main() -> int:
    en_txt = PENDING_DIR / "en.txt"
    ko_txt = PENDING_DIR / "ko.txt"
    meta_path = PENDING_DIR / "meta.json"

    if not (en_txt.exists() and ko_txt.exists() and meta_path.exists()):
        print("No pending script found - nothing to do.")
        return 0

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    date_str = meta["date"]
    title = meta["title"]
    description = meta["description"]

    mp3_name = f"brief-{date_str}.mp3"
    mp3_path = AUDIO_DIR / mp3_name

    tmp_en = Path("/tmp/brief-en.mp3")
    tmp_ko = Path("/tmp/brief-ko.mp3")
    synthesize(EN_VOICE, en_txt, tmp_en)
    synthesize(KO_VOICE, ko_txt, tmp_ko)
    combine_audio(tmp_en, tmp_ko, mp3_path)

    file_size = mp3_path.stat().st_size
    pub_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
        hour=6, minute=30, second=0, tzinfo=AEST
    )
    guid_url = f"{SITE_BASE}/audio/{mp3_name}"

    tree = load_feed()
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
    # drop any pre-existing item for the same date (re-running for today)
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
    tree.write(FEED_PATH, encoding="UTF-8", xml_declaration=True)
    with open(FEED_PATH, "a", encoding="utf-8") as f:
        f.write("\n")

    # prune audio files not referenced by any kept item
    if AUDIO_DIR.exists():
        for f in AUDIO_DIR.glob("brief-*.mp3"):
            if f.name not in kept_audio_files:
                print(f"Removing stale audio file {f.name}")
                f.unlink()

    if INDEX_PATH.exists():
        html = INDEX_PATH.read_text(encoding="utf-8")
        import re
        html = re.sub(
            r'(<p id="episode-title">).*?(</p>)',
            lambda m: m.group(1) + title.replace("Morning Brief — ", "") + m.group(2),
            html,
            count=1,
        )
        html = re.sub(
            r'(<audio[^>]*\bsrc=")[^"]*(")',
            lambda m: m.group(1) + f"audio/{mp3_name}" + m.group(2),
            html,
            count=1,
        )
        INDEX_PATH.write_text(html, encoding="utf-8")

    for f in (en_txt, ko_txt, meta_path):
        f.unlink(missing_ok=True)

    gh_output("date", date_str)
    gh_output("description", description)
    print(f"Built {mp3_path} ({file_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
