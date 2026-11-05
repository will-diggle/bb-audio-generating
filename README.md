# BB audio generating

Reads every article of the day's [Bilinguist Brief](https://bilinguistbrief.com) aloud and saves the
MP3s to Cloudflare R2, where the app's Worker serves them (`/audio/{date}/{lang}/{level}/{length}/{slug}`).

- **Voice model:** [Supertonic 3](https://huggingface.co/Supertone/supertonic-3) by Supertone, run on
  GitHub's machines (no API, no per-character cost). Licence: OpenRAIL-M. Only the model's 10 built-in
  voices are used.
- **Voices:** English is Emily (F5); German (speed 0.95) and French are Alex (M1). The other languages alternate Jessica (F3) and Robert (M3) story
  by story. Speed 0.92, quality 12 steps. All are set at the top of `bb_audio.py`, or by the
  `BB_VOICES`, `BB_TTS_SPEED` and `BB_TTS_STEPS` environment variables.
- **When it runs:** as soon as the other AIs have approved each article, never before. The pipeline
  writes the approved articles to `queue.json` on the private `audio-queue` branch of
  `will-diggle/bilinguist-data`, and that repo's `start-audio.yml` starts a run (`articles-approved`):
  English native once it has passed its checks, then the other natives once they have passed theirs.
  The final check's publish starts the levels (`brief-ready`). It needs that repo's
  `AUDIO_TRIGGER_TOKEN` secret, a fine-grained token with Contents read and write on this repo only.
  Runs at 06:45 and 08:30 UTC are a backup, which GitHub runs hours late.
- **What gets read again:** each MP3 has an empty file beside it, `<key>.mp3.<fingerprint>`, naming the
  text it was read from. An article whose text has changed since is read again; others are skipped.

## How a run works

An `articles-approved` run reads what's approved from the private branch, in one wave (their text is
never put in this public repo's files), then saves `ready.json` there, so the English is on the list
first and the other natives join it. The final check uses that to put Listen on them in the same push
that publishes the brief.

A `brief-ready` run:

1. **plan**: fetches today's brief from the Worker, drops articles already read from their current
   text, labels what's already read, and splits the rest into two waves of up to 20 equal batches:
   **Global News first**, then every other topic.
2. **speak-global-news**: one job per batch, all at once.
3. **label-global-news**: adds `audioKey` to every article of the live brief
   (`will-diggle/bilinguist-data`, `latest.json` and `briefings/<date>.json`) whose MP3 is in R2,
   and bumps `generatedAt` so phones re-download it. Listen appears on today's app here.
4. **speak-other-topics**: the second wave, all at once.
5. **check**: labels again, confirms every article has its MP3, and deletes days older than 14
   (R2's free tier is 10 GB). Nothing to label → no commit.

## Secrets (Settings → Secrets and variables → Actions)

- `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`: an R2 key with read and write on the
  `bilinguist-audio` bucket. Without them a run is a dry run: it reads everything aloud, uploads
  nothing, and reports the speed.
- `DATA_REPO_TOKEN`: a fine-grained GitHub token with Contents read and write on
  `will-diggle/bilinguist-data` only. Without it the label step does nothing.

## Run it locally

```bash
pip install -r requirements.txt
python bb_audio.py plan --limit 3 --batches 1
python bb_audio.py speak --batch 0      # without R2 keys the MP3s land in ./out
```

## Play all

The spoken parts of Play all are made here, ready to play between the articles (`play_all.py`). The
apps and website only choose which files to play. Each file is at `/audio/<key>`, with no `.mp3` on
the end, as with `audioKey`.

**Intro:** `{date}/{lang}/{level}/{length}/_play-all-{time}` and `..-{time}-no-title`

- `{time}` is `morning`, `afternoon` or `evening`. `{level}` is `A1` to `B2` or `Native`, as in `audioKey`.
- It has about 2.5 seconds of music, then the greeting, the day, a line introducing the headlines, that
  edition's Global News headlines, a pause and "Bilinguist Brief Global News". The music then fades to
  nothing over 3 seconds, so the first article starts straight after it.
- `-no-title` stops after the headlines, for a brief that doesn't start with Global News.
- `-free` is on `short` editions only, for free readers. After the headlines it says, in English in
  every language, "For more daily news articles in full, subscribe to Brief Plus today." The music
  carries on under that and fades out after it.

**Topic titles:** `play-all/{lang}/{global-news|uk|eu|us|business}`. They have no music and don't
change day to day.

**Old free message:** `play-all/en/free-message` has no music. It stays until the website has moved to
`-free`; the apps shouldn't use it.

**To play a brief:**

1. Reader's time 05:00-11:59 is `morning`, 12:00-17:59 `afternoon`, otherwise `evening`.
2. If the brief starts with Global News, play `_play-all-{time}`, then its articles. If not, play
   `_play-all-{time}-no-title`, then that topic's title, then its articles.
3. Before each later topic, play its title, then its articles.
4. Skip the intro if the brief's date isn't the reader's date today, as it says the day. Intros are
   deleted a day after their date.
5. A missing file (404) is skipped: the rest plays as normal.
6. **A free reader** hears `_play-all-{time}-free` and it stops there: no topic titles and no articles.
7. The intro and titles aren't stories: leave them out of "1 of 11" and of what counts as heard for the
   streak, and don't give them their own Listen button.

The website's `/api/audio` route needs a pass for these keys too, as it does for `audioKey`.

**The music** is `play-all/news-music.track` in R2: not in this public repo, and not named `.mp3`, so
the Worker can't serve it on its own, as its licence requires. To change it, replace the file and bump
`INTRO_VERSION` in `play_all.py`, and every intro is made again. With no file, the
intros are made with no music.

**To save time**, the greeting, the line introducing the headlines and "Bilinguist Brief Global News" are read
once per language and saved in `play-all/{lang}/parts/`. The date line is read once a day per language
before the machines start. Only the headlines are read for each edition; the music is added in code.

