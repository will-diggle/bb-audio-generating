# BB audio generating

Reads every article of the day's [Bilinguist Brief](https://bilinguistbrief.com) aloud and saves the
MP3s to Cloudflare R2, where the app's Worker serves them (`/audio/{date}/{lang}/{level}/{length}/{slug}`).

- **Voice model:** [Supertonic 3](https://huggingface.co/Supertone/supertonic-3) by Supertone, run on
  GitHub's machines (no API, no per-character cost). Licence: OpenRAIL-M. Only the model's 10 built-in
  voices are used.
- **Voices:** English is Emily (F5); German (speed 0.95) and French are Alex (M1). The other languages alternate Jessica (F3) and Robert (M3) story
  by story. Speed 0.92, quality 12 steps. All are set at the top of `bb_audio.py`, or by the
  `BB_VOICES`, `BB_TTS_SPEED` and `BB_TTS_STEPS` environment variables.
- **When it runs:** when the main pipeline sends `brief-ready`, plus at 06:45 and 08:30 UTC as a
  backup. Articles that already have audio are skipped.

## How a run works

1. **plan**: fetches today's brief from the Worker, drops articles that already have audio, and
   splits the rest into two waves of up to 20 equal batches: **Global News first** (the only
   articles today's app can play), then every other topic.
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
