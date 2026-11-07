"""Bilinguist Brief audio: reads every article of the day's brief aloud with Supertonic 3
and saves the MP3s to Cloudflare R2, where the Worker's /audio route serves them.

Runs on GitHub Actions as soon as articles are approved, not before (Will, 2 Nov 2026): English
native once it has passed its checks, the other natives once they have passed theirs, the levels
once the final check publishes them. See .github/workflows/generate-audio.yml:

    python bb_audio.py plan  --batches 20         today's brief → plan.json: Global News wave, other wave
    python bb_audio.py plan  --approved           the same for the articles approved so far
    python bb_audio.py speak --wave gn --batch 7  one batch: synthesise, encode, upload
    python bb_audio.py ready                      tell the final check which approved articles are read
    python bb_audio.py label                      add audioKey to the live brief where the MP3 exists
    python bb_audio.py check                      every article has its MP3? + delete old days

R2 keys are the ones the Google TTS stage used (bilinguist_audio.py), so the app and Worker
need no change: `{date}/{lang}/{level}/{length}/{slug}.mp3`, level "Native" for native articles.
Model: Supertonic 3 (Supertone, OpenRAIL-M; its 10 built-in voices only).
"""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import play_all

BUCKET = "bilinguist-audio"
DATA_URL = os.environ.get("BB_DATA_URL") or "https://api.bilinguistbrief.com"
PLAN = Path("plan.json")
KEEP_DAYS = int(os.environ.get("BB_AUDIO_KEEP_DAYS") or 14)

# Voices per language, alternating story by story (the same story keeps its voice at every level and
# length). Supertonic 3's ten built-in voices: F1 Sarah, F2 Lily, F3 Jessica (broadcast announcer),
# F4 Olivia, F5 Emily (British-sounding), M1 Alex, M2 James, M3 Robert (authoritative presenter),
# M4 Sam, M5 Daniel. English is Emily only; German and French Alex only (Will, 28 Oct). Override with BB_VOICES='{"de": ["F4","M2"]}'.
VOICES: dict[str, list[str]] = {lang: ["F3", "M3"] for lang in ("de", "fr", "es", "it", "pt", "sv", "hu", "tr", "ar")}
VOICES["en"] = ["F5"]
VOICES["de"] = ["M1"]  # Alex (Will, 28 Oct)
VOICES["fr"] = ["M1"]  # Alex (Will, 28 Oct)
VOICES.update(json.loads(os.environ.get("BB_VOICES") or "{}"))

# Quality = refinement steps (2-16; the library default is 8). Speed 1.0 reads too fast for learners;
# 0.90-0.95 sounds right (Will, 28 Oct).
STEPS = int(os.environ.get("BB_TTS_STEPS") or 12)
SPEED = float(os.environ.get("BB_TTS_SPEED") or 0.92)
SPEED_BY_LANG: dict[str, float] = {"de": 0.95}  # Alex reads German best a touch quicker (Will, 28 Oct)

# Supertonic refuses typographic quotes (German „ …); plain ones read the same.
PLAIN = str.maketrans({"„": '"', "“": '"', "”": '"', "«": '"', "»": '"', "‹": "'", "›": "'", "‚": "'",
                       "‘": "'", "’": "'", "–": "-", "—": "-", "…": "...", " ": " ", " ": " ",
                       # invisible marks the voice refuses ("\xad" lost a Swedish article on 7 Nov 2026)
                       **dict.fromkeys(["\u00ad", "\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"])})


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


# ── The approved articles, on a private branch of bilinguist-data ─────────────
# This repo is public, so their text never goes in its plan file: nobody may read them before the
# brief is published. The pipeline writes queue.json; `ready` writes ready.json for the final check.

QUEUE_BRANCH = "audio-queue"


def _data_api(path: str, method: str = "GET", body: dict | None = None, raw: bool = False):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{DATA_REPO}/contents/{path}", method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {(os.environ.get('DATA_REPO_TOKEN') or '').strip()}",
                 "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
                 "User-Agent": "bb-audio-generating"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch_queue() -> dict:
    """{"date", "nativeJournalism"}: the articles approved so far, or {} if they can't be read."""
    if not (os.environ.get("DATA_REPO_TOKEN") or "").strip():
        return {}
    for attempt in range(3):
        try:
            return _data_api(f"queue.json?ref={QUEUE_BRANCH}", raw=True)
        except Exception as e:  # noqa: BLE001
            log(f"Reading the approved articles failed ({e})")
            time.sleep(5 * (attempt + 1))
    return {}


# ── Plan ──────────────────────────────────────────────────────────────────────

def fetch_bundle() -> dict:
    """Today's brief from the Worker (about 17 MB). Retried: a fetch timed out on 28 Oct."""
    headers = {"User-Agent": "bb-audio-generating"}
    if os.environ.get("BB_CONTENT_KEY"):
        headers["X-Internal-Key"] = os.environ["BB_CONTENT_KEY"]
    req = urllib.request.Request(f"{DATA_URL}/latest", headers=headers)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.load(resp)
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                raise
            log(f"Fetching the brief failed ({e}); trying again in {15 * (attempt + 1)} s")
            time.sleep(15 * (attempt + 1))


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


def _spoken(a: dict) -> str:
    """Headline then body, in their audio versions, which have no spelled-out numbers ("Learjet
    60 (sixty)" was read as written until 2 Nov 2026, on 302 of that day's 747 headlines)."""
    return (f"{a.get('headlineAudio') or a.get('headline') or ''}. "
            f"{a.get('bodyAudio') or a.get('body') or ''}").strip()


def text_of(a: dict) -> str:
    return _spoken(a).translate(PLAIN)


def fingerprint(a: dict) -> str:
    """Which text an article's audio was read from. Must match audio_queue.fingerprint in the
    pipeline, which the final check uses (both repos test the same value)."""
    return hashlib.sha256(_spoken(a).encode("utf-8")).hexdigest()[:12]


# Beside each MP3 sits an empty file named `<key>.mp3.<fingerprint>`, so one listing says what
# every MP3 was read from, and text fixed after it was read gets read again.
_MARK = re.compile(r"\.mp3\.[0-9a-f]{12}$")


def reader(have: set[str]):
    """read(key, article): is this article's audio in R2, read from its current text? `have` is
    a listing (existing_keys). An MP3 with no mark at all is from before marks, and counts."""
    marked = {n.rsplit(".", 1)[0] for n in have if _MARK.search(n)}

    def read(key: str, a: dict) -> bool:
        mp3 = f"{key}.mp3"
        return mp3 in have and (f"{mp3}.{fingerprint(a)}" in have or mp3 not in marked)
    return read


def cmd_plan(args) -> None:
    out = Path(os.environ.get("GITHUB_OUTPUT") or os.devnull)
    want = args.date or today_utc()
    bundle = fetch_queue() if args.approved else fetch_bundle()
    # Started by the publish itself (brief-ready), the Worker can serve the old brief for a minute
    deadline = time.time() + args.wait * 60
    while (bundle.get("date") or "") != want and time.time() < deadline:
        log(f"The Worker is still serving {bundle.get('date')}; waiting for {want}")
        time.sleep(30)
        bundle = fetch_bundle()
    date = bundle.get("date") or ""
    if date != want:
        log(f"The {'approved articles are' if args.approved else 'published brief is'} for "
            f"{date or 'no date'}, not {want}: nothing to do yet.")
        with out.open("a") as f:
            f.write("gn_matrix=[]\nrest_matrix=[]\n")
        return

    # Each story keeps one voice everywhere; stories alternate between the language's two voices.
    # The approved articles count too, so a story the final check leaves out can't shift the voices
    # of the stories after it away from what their natives were read in.
    queue = bundle if args.approved else fetch_queue()
    slugs: dict[str, list[str]] = {}
    for source in (bundle, queue if queue.get("date") == date else {}):
        for lang, _, _, a in articles(source):
            slugs.setdefault(lang, [])
            if a.get("slug") and a["slug"] not in slugs[lang]:
                slugs[lang].append(a["slug"])
    for lang in slugs:
        slugs[lang].sort()

    client = r2()
    done = (existing_keys(client, date) | existing_keys(client, TITLES_FOLDER)) if client else set()
    read = reader(done)
    items, skipped = [], 0
    for lang, level, length, a in articles(bundle):
        slug, text = a.get("slug"), text_of(a)
        if not slug or len(text) < 3:
            continue
        key = f"{date}/{lang}/{level}/{length}/{slug}"
        if read(key, a):
            skipped += 1
            continue
        pair = VOICES.get(lang) or ["F3", "M3"]
        items.append({"key": key, "lang": lang, "voice": pair[slugs[lang].index(slug) % len(pair)], "text": text,
                      "genre": (a.get("genre") or "").upper(), "mark": fingerprint(a),
                      "stale": [n for n in done if n.startswith(f"{key}.mp3.")]})
    if args.limit:
        items = items[: args.limit]
    else:
        more, already = play_all_items(bundle, date, read, done)
        items += more
        skipped += already
        if client and any(i.get("intro") for i in more):
            make_saved_parts(client, date, {i["lang"] for i in more if i.get("intro")} | {"en"}, done)

    # Two waves: Global News first (labelled as soon as they are read), then everything else; the
    # approved articles go in one, to be read before the brief is published. Within a wave: longest
    # first into the lightest batch, so the batches finish together.
    def split(wave: list[dict]) -> list[list[dict]]:
        n = max(1, min(args.batches, len(wave)))
        batches: list[list[dict]] = [[] for _ in range(n)]
        sizes = [0] * n
        for it in sorted(wave, key=lambda i: -len(i["text"])):
            b = sizes.index(min(sizes))
            batches[b].append(it)
            sizes[b] += len(it["text"])
        return [b for b in batches if b]

    if args.approved:
        waves = {"gn": split(items), "rest": []}
    else:
        waves = {"gn": split([i for i in items if i["genre"] == "GLOBAL NEWS"]),
                 "rest": split([i for i in items if i["genre"] != "GLOBAL NEWS"])}
    for name, label in (("gn", "Approved" if args.approved else "Global News"), ("rest", "other topics")):
        wave = [i for b in waves[name] for i in b]
        log(f"{date} {label}: {len(wave)} articles ({sum(len(i['text']) for i in wave):,} characters) "
            f"in {len(waves[name])} batches")
    log(f"{skipped} already in R2")
    if args.approved:  # the speak jobs read the text from the private branch
        for i in items:
            if not i["key"].startswith(f"{TITLES_FOLDER}/"):
                del i["text"]
    PLAN.write_text(json.dumps({"date": date, "approved": args.approved, "waves": waves}, ensure_ascii=False))
    with out.open("a") as f:
        f.write(f"gn_matrix={json.dumps(list(range(len(waves['gn']))))}\n")
        f.write(f"rest_matrix={json.dumps(list(range(len(waves['rest']))))}\n")
        f.write(f"date={date}\n")
        f.write(f"source={'approved' if args.approved else 'brief'}\n")


# ── Play all ─────────────────────────────────────────────────────────────────────────────────────
# The intros and topic titles (play_all.py). An edition's six intro files are read as one item, so
# the headlines they share are only read once, and its last file says whether it's all done.

TITLES_FOLDER = "play-all"
# Not .mp3: the Worker serves any "<key>.mp3" at /audio/<key>, and the track must never be downloadable
# on its own (Pixabay's licence bans standalone distribution)
MUSIC_KEY = f"{TITLES_FOLDER}/news-music.track"
LAST_INTRO = f"-{play_all.TIMES[-1]}-no-title"
FREE_LENGTH = "short"                 # the only edition a free reader gets
INTRO_LEAD, INTRO_TAIL = 2.5, 3.0     # seconds of music alone before the voice and after it
MUSIC_LOUDNESS = 0.1                  # any track is brought to this (RMS), so a new one sits the same
MUSIC_ALONE, MUSIC_UNDER = 0.7, 0.1   # alone it's about as loud as the voice, under it about 15 dB below
GAPS = {"greeting": 0.25, "lead-in": 0.55, "headline": 0.65, "title": 1.4}


def intro_key(date: str, lang: str, level: str, length: str) -> str:
    return f"{date}/{lang}/{level}/{length}/_play-all"


def intro_article(text: str) -> dict:
    """What an intro's fingerprint is taken from: its headlines and the music."""
    return {"bodyAudio": f"{play_all.INTRO_VERSION}\n{text}"}


def intro_headlines(bundle: dict) -> dict:
    """Each edition's Global News headlines, as said aloud, one to a line, by its intro's key."""
    found: dict[str, list[str]] = {}
    date = bundle.get("date") or ""
    for lang, level, length, a in articles(bundle):
        if lang in play_all.GREETINGS and (a.get("genre") or "").upper() == "GLOBAL NEWS":
            headline = (a.get("headlineAudio") or a.get("headline") or "").translate(PLAIN)
            if headline.strip():
                found.setdefault(intro_key(date, lang, level, length), []).append(play_all.as_sentence(headline))
    return {key: "\n".join(lines) for key, lines in found.items()}


def play_all_items(bundle: dict, date: str, read, done: set[str]) -> tuple[list[dict], int]:
    """What's still to read: each edition's intros, and any topic title not made yet."""
    items, skipped = [], 0
    for key, text in intro_headlines(bundle).items():
        a = intro_article(text)
        if read(key + LAST_INTRO, a):
            skipped += 1
            continue
        lang = key.split("/")[1]
        items.append({"key": key, "lang": lang, "voice": (VOICES.get(lang) or ["F3"])[0], "text": text,
                      "genre": "GLOBAL NEWS", "mark": fingerprint(a), "intro": True,
                      "stale": [n for n in done if n.startswith(f"{key}-") and _MARK.search(n)]})
    for lang in sorted({key.split("/")[1] for key in intro_headlines(bundle)}):
        for genre, name in play_all.TOPICS.items():
            key, text = f"{TITLES_FOLDER}/{lang}/{name}", play_all.TITLES[lang][genre]
            a = {"bodyAudio": text}
            if read(key, a):
                continue
            items.append({"key": key, "lang": lang, "voice": (VOICES.get(lang) or ["F3"])[0], "text": text,
                          "genre": "GLOBAL NEWS", "mark": fingerprint(a),
                          "stale": [n for n in done if n.startswith(f"{key}.mp3.")]})
    key, a = f"{TITLES_FOLDER}/en/free-message", {"bodyAudio": play_all.FREE_MESSAGE}
    if intro_headlines(bundle) and not read(key, a):
        items.append({"key": key, "lang": "en", "voice": VOICES["en"][0], "text": play_all.FREE_MESSAGE,
                      "genre": "GLOBAL NEWS", "mark": fingerprint(a),
                      "stale": [n for n in done if n.startswith(f"{key}.mp3.")]})
    return items, skipped


def saved_part_key(line: str, lang: str, date: str) -> str:
    """Where a shared line's samples are kept: the day's line goes with the day's files, and the
    rest stay. The voice and its settings are in the name, as the samples depend on them."""
    if line == play_all.day_line(lang, date):
        return f"{date}/{lang}/_play-all-day.f32"
    voice = (VOICES.get(lang) or ["F3"])[0]
    made_with = f"{line}|{voice}|{STEPS}|{SPEED_BY_LANG.get(lang, SPEED)}"
    return f"{TITLES_FOLDER}/{lang}/parts/{hashlib.sha256(made_with.encode()).hexdigest()[:12]}.f32"


def make_saved_parts(client, date: str, langs: set[str], done: set[str]) -> None:
    """Before the machines start: read today's day line and any shared line not saved yet, once
    per language. If this fails, each machine reads what it needs."""
    try:
        missing = [(lang, line) for lang in sorted(langs)
                   for line in [*play_all.saved_lines(lang), play_all.day_line(lang, date)]
                   if saved_part_key(line, lang, date) not in done]
        if not missing:
            return
        from supertonic import TTS
        tts, styles = TTS(model="supertonic-3"), {}
        for lang, line in missing:
            voice = (VOICES.get(lang) or ["F3"])[0]
            samples = synthesize(tts, styles, line, voice, lang, STEPS).reshape(-1).astype("float32")
            client.put_object(Bucket=BUCKET, Key=saved_part_key(line, lang, date), Body=samples.tobytes())
        log(f"Saved {len(missing)} shared intro lines")
    except Exception as e:  # noqa: BLE001
        log(f"Shared intro lines not saved in advance: {e}")


def saved_part(client, line: str, lang: str, date: str):
    """A shared line's samples from R2, or None."""
    if not client or line not in [*play_all.saved_lines(lang), play_all.day_line(lang, date)]:
        return None
    try:
        import numpy as np
        body = client.get_object(Bucket=BUCKET, Key=saved_part_key(line, lang, date))["Body"].read()
        return np.frombuffer(body, dtype=np.float32)
    except Exception:  # noqa: BLE001
        return None


def synthesize(tts, styles: dict, text: str, voice: str, lang: str, steps: int):
    style = styles.get(voice) or styles.setdefault(voice, tts.get_voice_style(voice))
    while True:
        try:
            wav, _ = tts.synthesize(text, voice_style=style, lang=lang, total_steps=steps,
                                    speed=SPEED_BY_LANG.get(lang, SPEED))
            return wav
        except ValueError as e:  # a character the model can't read: say nothing for it
            listed = re.search(r"\[.*\]", str(e))
            bad = [ch for ch in ast.literal_eval(listed[0]) if ch in text] if listed else []
            if not bad:
                raise
            for ch in bad:
                text = text.replace(ch, " ")


def news_music(client, rate: int):
    """The music under the intros, as samples, from R2 (BB_NEWS_MUSIC: a local file instead). None if
    it isn't there: the intros still get read."""
    local = os.environ.get("BB_NEWS_MUSIC")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(local) if local else Path(tmp) / "music.mp3"
        if not local:
            try:
                path.write_bytes(client.get_object(Bucket=BUCKET, Key=MUSIC_KEY)["Body"].read())
            except Exception as e:  # noqa: BLE001
                log(f"No news music for the intros: {e}")
                return None
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", str(rate),
                              "-f", "f32le", "-"], check=True, capture_output=True).stdout
    import numpy as np
    music = np.frombuffer(raw, dtype=np.float32)
    sound = np.flatnonzero(np.abs(music) > 0.003)
    if not len(sound):
        return None
    music = music[sound[0]:]   # a silent start would eat into the music played alone
    played = music[:60 * rate]  # level it on the part an intro actually plays
    return music * (MUSIC_LOUDNESS / max(float(np.sqrt(np.mean(played ** 2))), 1e-6))


def over_music(voice, music, rate: int):
    """The music alone, then quietly under the voice, then rising and fading to nothing, so it's gone
    as the first article starts."""
    import numpy as np
    lead, tail = int(INTRO_LEAD * rate), int(INTRO_TAIL * rate)
    voice = np.concatenate([np.zeros(lead, dtype=np.float32), voice, np.zeros(tail, dtype=np.float32)])
    if music is None or not len(music):
        return voice[lead - rate // 4:len(voice) - tail + rate // 4]
    bed = np.tile(music, len(voice) // len(music) + 1)[:len(voice)]
    end = (len(voice) - tail) / rate
    level = np.interp(np.arange(len(voice)) / rate,
                      [0, INTRO_LEAD - 0.7, INTRO_LEAD - 0.1, end + 0.1, end + 0.7, end + INTRO_TAIL],
                      [MUSIC_ALONE, MUSIC_ALONE, MUSIC_UNDER, MUSIC_UNDER, MUSIC_ALONE * 0.8, 0.0])
    mixed = voice + bed * level
    return mixed / max(1.0, float(np.abs(mixed).max()) / 0.97)


def read_intros(it: dict, date: str, say, music, rate: int, save) -> None:
    """Make an edition's intro files, ending with the one that says it's done. A free reader only
    gets the concise edition, so only that has an intro for them."""
    import numpy as np
    gap = lambda name: np.zeros(int(GAPS[name] * rate), dtype=np.float32)
    lang = it["lang"]
    headlines = []
    for line in it["text"].split("\n"):
        headlines += [say(line), gap("headline")]
    title = say(play_all.intro_title(lang))
    message = say(play_all.FREE_MESSAGE, "en") if f"/{FREE_LENGTH}/" in it["key"] else None
    today = [gap("greeting"), say(play_all.day_line(lang, date)), gap("greeting"),
             say(play_all.HEADLINES[lang]), gap("lead-in")]
    for time in play_all.TIMES:
        opening = [say(play_all.greeting_line(lang, time)), *today]
        save(f"{it['key']}-{time}", over_music(np.concatenate([*opening, *headlines[:-1], gap("title"), title]), music, rate))
        if message is not None:
            save(f"{it['key']}-{time}-free", over_music(np.concatenate([*opening, *headlines[:-1], gap("title"), message]), music, rate))
        save(f"{it['key']}-{time}-no-title", over_music(np.concatenate([*opening, *headlines[:-1]]), music, rate))


# ── Speak ─────────────────────────────────────────────────────────────────────

def cmd_speak(args) -> None:
    plan = json.loads(PLAN.read_text())
    batch = plan["waves"][args.wave][args.batch]
    approved = {}
    if plan.get("approved"):
        queue = fetch_queue()
        approved = {f"{plan['date']}/{lang}/{level}/{length}/{a.get('slug')}": text_of(a)
                    for lang, level, length, a in articles(queue)}
        approved.update(intro_headlines(queue))
    from supertonic import TTS
    tts = TTS(model="supertonic-3")
    styles: dict[str, object] = {}
    client = r2()
    ok = failed = chars = 0
    audio_secs = 0.0
    start = time.time()

    music = None
    if any(it.get("intro") for it in batch):
        music = news_music(client, tts.sample_rate)

    said: dict[tuple[str, str], object] = {}

    def read_intro_item(it: dict) -> None:
        def say(line: str, lang: str | None = None):
            lang = lang or it["lang"]
            key = (lang, line)
            if key not in said:
                part = saved_part(client, line, lang, plan["date"])
                if part is None:
                    voice = (VOICES.get(lang) or ["F3"])[0]
                    part = synthesize(tts, styles, line, voice, lang, args.steps).reshape(-1).astype("float32")
                said[key] = part
            return said[key]

        def save(key: str, samples) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                wav_path, mp3_path = Path(tmp) / "a.wav", Path(tmp) / "a.mp3"
                tts.save_audio(samples, str(wav_path))
                subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav_path), "-ac", "1", "-ar", "44100",
                                "-b:a", "64k", str(mp3_path)], check=True)
                body = mp3_path.read_bytes()
            if client:
                client.put_object(Bucket=BUCKET, Key=f"{key}.mp3", Body=body, ContentType="audio/mpeg")
                client.put_object(Bucket=BUCKET, Key=f"{key}.mp3.{it['mark']}", Body=b"")
            else:
                local = Path("out") / f"{key}.mp3"
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(body)

        if client:
            for old in it.get("stale") or []:
                client.delete_object(Bucket=BUCKET, Key=old)
        read_intros(it, plan["date"], say, music, tts.sample_rate, save)

    for it in batch:
        text = it["text"] = it.get("text") or approved.get(it["key"]) or ""
        try:
            if not text:
                raise ValueError("no text for this article")
            if it.get("intro"):
                read_intro_item(it)
                ok += 1
                chars += len(text)
                continue
            wav = synthesize(tts, styles, text, it["voice"], it["lang"], args.steps)
            with tempfile.TemporaryDirectory() as tmp:
                wav_path, mp3_path = Path(tmp) / "a.wav", Path(tmp) / "a.mp3"
                tts.save_audio(wav, str(wav_path))
                subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav_path), "-ac", "1", "-ar", "24000",
                                "-b:a", "48k", str(mp3_path)], check=True)
                body = mp3_path.read_bytes()
            if client:
                client.put_object(Bucket=BUCKET, Key=f"{it['key']}.mp3", Body=body, ContentType="audio/mpeg")
                for old in it.get("stale") or []:
                    client.delete_object(Bucket=BUCKET, Key=old)
                client.put_object(Bucket=BUCKET, Key=f"{it['key']}.mp3.{it['mark']}", Body=b"")
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
    log(f"{args.wave} batch {args.batch}: {ok} read, {failed} failed, {chars:,} chars → {audio_secs / 60:.0f} min of audio "
        f"in {took / 60:.1f} min ({chars / max(took, 1):.0f} chars/s){'' if client else ' (dry run: nothing uploaded)'}")
    if failed and failed >= max(1, len(batch) // 10):
        sys.exit(1)


# ── Check + clean-up ──────────────────────────────────────────────────────────

def expired(key: str, cutoff: str, intro_cutoff: str) -> bool:
    day = key.split("/", 1)[0]
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)) and (
        day < cutoff or ("/_play-all-" in key and day < intro_cutoff))


def cmd_check(args) -> None:
    client = r2()
    if not client:
        log("No R2 secrets: nothing to check.")
        return
    bundle = fetch_bundle()
    date = bundle.get("date") or today_utc()
    have = existing_keys(client, date)
    expected = {f"{date}/{lang}/{level}/{length}/{a['slug']}": a
                for lang, level, length, a in articles(bundle) if a.get("slug")}
    read = reader(have)
    missing = sorted(f"{key}.mp3" for key, a in expected.items() if not read(key, a))
    summary = f"{date}: {len(expected) - len(missing)} of {len(expected)} articles have audio"
    log(summary)
    for k in missing[:20]:
        log(f"  missing {k}")
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a") as f:
            f.write(f"### {summary}\n" + "".join(f"- missing `{k}`\n" for k in missing[:50]))

    intros = intro_headlines(bundle)
    read_intros_count = sum(read(key + LAST_INTRO, intro_article(text)) for key, text in intros.items())
    log(f"{date}: {read_intros_count} of {len(intros)} Play all intros are made")

    # Keep the last KEEP_DAYS days (R2's free tier is 10 GB; a day is about 0.5 GB). An intro says
    # today's date, so it's no use after that day: those go after a day.
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    intro_cutoff = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    old = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET):
        for o in page.get("Contents", []):
            if expired(o["Key"], cutoff, intro_cutoff):
                old.append({"Key": o["Key"]})
    for i in range(0, len(old), 1000):
        client.delete_objects(Bucket=BUCKET, Delete={"Objects": old[i:i + 1000], "Quiet": True})
    if old:
        log(f"Deleted {len(old)} files older than {cutoff}")
    if missing:
        sys.exit(1)


# ── Label ─────────────────────────────────────────────────────────────────────
# The current app shows Listen only on an article that carries an `audioKey` (and only for Global
# News). The brief is published before the audio exists, so once the audio is in R2 this adds the
# key to every article that has its MP3, in both files the Worker may serve (they must stay
# identical), and bumps generatedAt so phones re-download the brief. No change → no commit.

DATA_REPO = "will-diggle/bilinguist-data"
COMMIT_EMAIL = "81531349+will-diggle@users.noreply.github.com"  # GitHub rejects Will's private email


def label_files(root: Path, have: set[str]) -> tuple[int, int]:
    """Adds audioKey to every article whose MP3 is in `have`. Returns (added, global_news_added);
    writes nothing when there is nothing to add."""
    latest = root / "latest.json"
    raw = latest.read_text(encoding="utf-8")
    d = json.loads(raw)
    dated = root / "briefings" / f"{d['date']}.json"
    if not dated.exists() or dated.read_text(encoding="utf-8") != raw:
        raise SystemExit("latest.json and today's briefings file differ: not touching either")
    added = global_added = 0
    read = reader(have)
    for lang, level, length, a in articles(d):
        if not a.get("slug"):
            continue
        key = f"{d['date']}/{lang}/{level}/{length}/{a['slug']}"
        if read(key, a) and a.get("audioKey") != key:
            a["audioKey"] = key
            added += 1
            global_added += a.get("genre") == "GLOBAL NEWS"
    if added:
        d["generatedAt"] = int(time.time() * 1000)
        out = json.dumps(d, indent=2, ensure_ascii=False)
        latest.write_text(out, encoding="utf-8")
        dated.write_text(out, encoding="utf-8")
    return added, global_added


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def cmd_label(args) -> None:
    token = (os.environ.get("DATA_REPO_TOKEN") or "").strip()
    client = r2()
    if not (token and client):
        log("No DATA_REPO_TOKEN or R2 secrets: not labelling the brief.")
        return
    date = fetch_bundle().get("date") or ""
    if date != today_utc():
        log(f"The published brief is for {date}, not today: not labelling.")
        return
    have = existing_keys(client, date)
    for attempt in range(3):  # someone else (the fact sweep) may push in between
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse",
                            f"https://x-access-token:{token}@github.com/{DATA_REPO}.git", str(root)], check=True)
            git("sparse-checkout", "set", "--no-cone", "/latest.json", f"/briefings/{date}.json", cwd=root)
            added, global_added = label_files(root, have)
            if not added:
                log(f"{date}: every article with audio is already labelled.")
                return
            git("add", "latest.json", f"briefings/{date}.json", cwd=root)
            git("-c", "user.name=BB audio", "-c", f"user.email={COMMIT_EMAIL}", "commit", "-q", "-m",
                # [skip ci]: audio labels aren't a new brief, so bilinguist-data's push workflow (word
                # routine + QA sweep) mustn't start for them (it did on 28 Oct).
                f"Audio {date}: Listen on {added} articles ({global_added} Global News) [skip ci]", cwd=root)
            try:
                git("push", "-q", "origin", "HEAD", cwd=root)
                log(f"{date}: labelled {added} articles ({global_added} Global News) and bumped generatedAt")
                return
            except subprocess.CalledProcessError:
                log(f"push rejected (attempt {attempt + 1}); someone else pushed, trying again")
                time.sleep(10)
    sys.exit("Could not push the labels after 3 attempts")


# ── Ready ─────────────────────────────────────────────────────────────────────

def cmd_ready(args) -> None:
    """Tell the final check which approved articles have their audio, and from which text, so
    it can put Listen on them in the same push that publishes the brief. If this is late or
    fails, the first step of the run the publish starts labels them instead."""
    client, queue = r2(), fetch_queue()
    date = queue.get("date") or ""
    if not client or date != today_utc():
        log(f"Nothing to tell the final check (approved articles for {date or 'no date'}).")
        return
    read = reader(existing_keys(client, date))
    done = {}
    for lang, level, length, a in articles(queue):
        key = f"{date}/{lang}/{level}/{length}/{a.get('slug')}"
        if read(key, a):
            done[key] = fingerprint(a)
    content = base64.b64encode(json.dumps({"date": date, "read": done}).encode()).decode()
    for attempt in range(3):
        try:
            try:
                sha = {"sha": _data_api(f"ready.json?ref={QUEUE_BRANCH}")["sha"]}
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                sha = {}
            _data_api("ready.json", "PUT", {"message": f"Audio ready {date}: {len(done)} articles",
                                            "branch": QUEUE_BRANCH, "content": content, **sha})
            log(f"{date}: told the final check {len(done)} approved articles have audio")
            return
        except Exception as e:  # noqa: BLE001
            log(f"Saving ready.json failed ({e}); trying again")
            time.sleep(5 * (attempt + 1))
    log("Could not save ready.json: the publish run labels these articles instead")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("plan")
    a.add_argument("--batches", type=int, default=20)
    a.add_argument("--date", default="")
    a.add_argument("--limit", type=int, default=0, help="only this many articles (a test run)")
    a.add_argument("--wait", type=float, default=0, help="minutes to wait for today's brief to be served")
    a.add_argument("--approved", action="store_true", help="the articles approved so far, not the published brief")
    a.set_defaults(fn=cmd_plan)
    a = sub.add_parser("speak")
    a.add_argument("--wave", choices=["gn", "rest"], required=True)
    a.add_argument("--batch", type=int, required=True)
    a.add_argument("--steps", type=int, default=STEPS)
    a.set_defaults(fn=cmd_speak)
    a = sub.add_parser("check")
    a.set_defaults(fn=cmd_check)
    a = sub.add_parser("label")
    a.set_defaults(fn=cmd_label)
    a = sub.add_parser("ready")
    a.set_defaults(fn=cmd_ready)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
