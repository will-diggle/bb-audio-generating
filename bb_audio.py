"""Bilinguist Brief audio: reads every article of the day's brief aloud with Supertonic 3
and saves the MP3s to Cloudflare R2, where the Worker's /audio route serves them.

Runs on GitHub Actions in three steps (see .github/workflows/generate-audio.yml):

    python bb_audio.py plan  --batches 20     today's brief → plan.json, split into equal batches
    python bb_audio.py speak --batch 7        one batch: synthesise, encode, upload
    python bb_audio.py check                  every article has its MP3? + delete old days

R2 keys are the ones the Google TTS stage used (bilinguist_audio.py), so the app and Worker
need no change: `{date}/{lang}/{level}/{length}/{slug}.mp3`, level "Native" for native articles.
Model: Supertonic 3 (Supertone, OpenRAIL-M; its 10 built-in voices only).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BUCKET = "bilinguist-audio"
DATA_URL = os.environ.get("BB_DATA_URL") or "https://api.bilinguistbrief.com"
PLAN = Path("plan.json")
KEEP_DAYS = int(os.environ.get("BB_AUDIO_KEEP_DAYS") or 14)

# Voices per language, alternating story by story (the same story keeps its voice at every level and
# length). Supertonic 3's ten built-in voices: F1 Sarah, F2 Lily, F3 Jessica (broadcast announcer),
# F4 Olivia, F5 Emily (British-sounding), M1 Alex, M2 James, M3 Robert (authoritative presenter),
# M4 Sam, M5 Daniel. English is Emily only and German Alex only (Will, 28 Oct). Override with BB_VOICES='{"de": ["F4","M2"]}'.
VOICES: dict[str, list[str]] = {lang: ["F3", "M3"] for lang in ("de", "fr", "es", "it", "pt", "sv", "hu", "tr", "ar")}
VOICES["en"] = ["F5"]
VOICES["de"] = ["M1"]  # Alex (Will, 28 Oct)
VOICES.update(json.loads(os.environ.get("BB_VOICES") or "{}"))

# Quality = refinement steps (2-16; the library default is 8). Speed 1.0 reads too fast for learners;
# 0.90-0.95 sounds right (Will, 28 Oct).
STEPS = int(os.environ.get("BB_TTS_STEPS") or 12)
SPEED = float(os.environ.get("BB_TTS_SPEED") or 0.92)
SPEED_BY_LANG: dict[str, float] = {"de": 0.95}  # Alex reads German best a touch quicker (Will, 28 Oct)

# Supertonic refuses typographic quotes (German „ …); plain ones read the same.
PLAIN = str.maketrans({"„": '"', "“": '"', "”": '"', "«": '"', "»": '"', "‹": "'", "›": "'", "‚": "'",
                       "‘": "'", "’": "'", "–": "-", "—": "-", "…": "...", " ": " ", " ": " "})


def log(msg: str) -> None:
    print(msg, flush=True)


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── R2 ────────────────────────────────────────────────────────────────────────

def r2():
    """boto3 client for R2, or None when the secrets aren't set (dry runs)."""
    account = (os.environ.get("R2_ACCOUNT_ID") or "").strip()
    key_id = (os.environ.get("R2_ACCESS_KEY_ID") or "").strip()
    secret = (os.environ.get("R2_SECRET_ACCESS_KEY") or "").strip()
    if not (account and key_id and secret):
        return None
    import boto3
    from botocore.config import Config
    return boto3.client("s3", endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
                        aws_access_key_id=key_id, aws_secret_access_key=secret, region_name="auto",
                        config=Config(retries={"max_attempts": 5, "mode": "standard"}))


def existing_keys(client, date: str) -> set[str]:
    """Every MP3 already in R2 for this date (one listing, not a HEAD per article)."""
    keys: set[str] = set()
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=f"{date}/"):
        keys.update(o["Key"] for o in page.get("Contents", []))
    return keys


# ── Plan ──────────────────────────────────────────────────────────────────────

def fetch_bundle() -> dict:
    req = urllib.request.Request(f"{DATA_URL}/latest", headers={"User-Agent": "bb-audio-generating"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def articles(bundle: dict):
    """(lang, level, length, article) for every article a reader can see: every leveled brief and
    the native articles. Not `nativeIntermediate` (an internal stepping stone nobody reads)."""
    for lang, by_level in (bundle.get("briefings") or {}).items():
        for level, by_length in (by_level or {}).items():
            for length, brief in (by_length or {}).items():
                for a in (brief or {}).get("articles") or []:
                    yield lang, level, length, a
    for lang, by_length in (bundle.get("nativeJournalism") or {}).items():
        for length, items in (by_length or {}).items():
            for a in items or []:
                yield lang, "Native", length, a


def text_of(a: dict) -> str:
    """Headline then the audio body, as the Google stage read it."""
    return f"{a.get('headline') or ''}. {a.get('bodyAudio') or a.get('body') or ''}".strip().translate(PLAIN)


def cmd_plan(args) -> None:
    out = Path(os.environ.get("GITHUB_OUTPUT") or os.devnull)
    bundle = fetch_bundle()
    date = bundle.get("date") or ""
    want = args.date or today_utc()
    if date != want:
        log(f"The published brief is for {date or 'no date'}, not {want}: nothing to do yet.")
        with out.open("a") as f:
            f.write("matrix=[]\n")
        return

    # Each story keeps one voice everywhere; stories alternate between the language's two voices.
    slugs: dict[str, list[str]] = {}
    for lang, _, _, a in articles(bundle):
        slugs.setdefault(lang, [])
        if a.get("slug") and a["slug"] not in slugs[lang]:
            slugs[lang].append(a["slug"])
    for lang in slugs:
        slugs[lang].sort()

    client = r2()
    done = existing_keys(client, date) if client else set()
    items, skipped = [], 0
    for lang, level, length, a in articles(bundle):
        slug, text = a.get("slug"), text_of(a)
        if not slug or len(text) < 3:
            continue
        key = f"{date}/{lang}/{level}/{length}/{slug}"
        if f"{key}.mp3" in done:
            skipped += 1
            continue
        pair = VOICES.get(lang) or ["F3", "M3"]
        items.append({"key": key, "lang": lang, "voice": pair[slugs[lang].index(slug) % len(pair)], "text": text})
    if args.limit:
        items = items[: args.limit]

    # Longest first into the lightest batch, so the batches finish together.
    n = max(1, min(args.batches, len(items)))
    batches: list[list[dict]] = [[] for _ in range(n)]
    sizes = [0] * n
    for it in sorted(items, key=lambda i: -len(i["text"])):
        b = sizes.index(min(sizes))
        batches[b].append(it)
        sizes[b] += len(it["text"])
    batches = [b for b in batches if b]

    PLAN.write_text(json.dumps({"date": date, "batches": batches}, ensure_ascii=False))
    total = sum(len(i["text"]) for i in items)
    log(f"{date}: {len(items)} articles to read ({total:,} characters) in {len(batches)} batches; "
        f"{skipped} already in R2")
    with out.open("a") as f:
        f.write(f"matrix={json.dumps(list(range(len(batches))))}\n")
        f.write(f"date={date}\n")


# ── Speak ─────────────────────────────────────────────────────────────────────

def cmd_speak(args) -> None:
    plan = json.loads(PLAN.read_text())
    batch = plan["batches"][args.batch]
    from supertonic import TTS
    tts = TTS(model="supertonic-3")
    styles: dict[str, object] = {}
    client = r2()
    ok = failed = chars = 0
    audio_secs = 0.0
    start = time.time()

    for it in batch:
        text = it["text"]
        try:
            style = styles.get(it["voice"]) or styles.setdefault(it["voice"], tts.get_voice_style(it["voice"]))
            while True:
                try:
                    wav, _ = tts.synthesize(text, voice_style=style, lang=it["lang"], total_steps=args.steps,
                                              speed=SPEED_BY_LANG.get(it["lang"], SPEED))
                    break
                except ValueError as e:  # a character the model can't read: say nothing for it
                    bad = re.findall(r"'(.)'", str(e))
                    if not bad:
                        raise
                    for ch in bad:
                        text = text.replace(ch, " ")
            with tempfile.TemporaryDirectory() as tmp:
                wav_path, mp3_path = Path(tmp) / "a.wav", Path(tmp) / "a.mp3"
                tts.save_audio(wav, str(wav_path))
                subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav_path), "-ac", "1", "-ar", "24000",
                                "-b:a", "48k", str(mp3_path)], check=True)
                body = mp3_path.read_bytes()
            if client:
                client.put_object(Bucket=BUCKET, Key=f"{it['key']}.mp3", Body=body, ContentType="audio/mpeg")
            else:  # dry run: keep the file locally to listen to
                local = Path("out") / f"{it['key']}.mp3"
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(body)
            ok += 1
            chars += len(it["text"])
            audio_secs += wav.reshape(-1).shape[0] / tts.sample_rate
        except Exception as e:  # one article must never stop the rest
            failed += 1
            log(f"FAILED {it['key']}: {e}")

    took = time.time() - start
    log(f"batch {args.batch}: {ok} read, {failed} failed, {chars:,} chars → {audio_secs / 60:.0f} min of audio "
        f"in {took / 60:.1f} min ({chars / max(took, 1):.0f} chars/s){'' if client else ' (dry run: nothing uploaded)'}")
    if failed and failed >= max(1, len(batch) // 10):
        sys.exit(1)


# ── Check + clean-up ──────────────────────────────────────────────────────────

def cmd_check(args) -> None:
    client = r2()
    if not client:
        log("No R2 secrets: nothing to check.")
        return
    bundle = fetch_bundle()
    date = bundle.get("date") or today_utc()
    have = existing_keys(client, date)
    expected = {f"{date}/{lang}/{level}/{length}/{a['slug']}.mp3"
                for lang, level, length, a in articles(bundle) if a.get("slug")}
    missing = sorted(expected - have)
    summary = f"{date}: {len(expected) - len(missing)} of {len(expected)} articles have audio"
    log(summary)
    for k in missing[:20]:
        log(f"  missing {k}")
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a") as f:
            f.write(f"### {summary}\n" + "".join(f"- missing `{k}`\n" for k in missing[:50]))

    # Keep the last KEEP_DAYS days (R2's free tier is 10 GB; a day is about 0.3 GB).
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    old = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET):
        for o in page.get("Contents", []):
            day = o["Key"].split("/", 1)[0]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) and day < cutoff:
                old.append({"Key": o["Key"]})
    for i in range(0, len(old), 1000):
        client.delete_objects(Bucket=BUCKET, Delete={"Objects": old[i:i + 1000], "Quiet": True})
    if old:
        log(f"Deleted {len(old)} files older than {cutoff}")
    if missing:
        sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("plan")
    a.add_argument("--batches", type=int, default=20)
    a.add_argument("--date", default="")
    a.add_argument("--limit", type=int, default=0, help="only this many articles (a test run)")
    a.set_defaults(fn=cmd_plan)
    a = sub.add_parser("speak")
    a.add_argument("--batch", type=int, required=True)
    a.add_argument("--steps", type=int, default=STEPS)
    a.set_defaults(fn=cmd_speak)
    a = sub.add_parser("check")
    a.set_defaults(fn=cmd_check)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
