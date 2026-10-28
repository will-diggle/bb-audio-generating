# BB audio generating

Reads every article of the day's [Bilinguist Brief](https://bilinguistbrief.com) aloud and saves the
MP3s to Cloudflare R2, where the app's Worker serves them (`/audio/{date}/{lang}/{level}/{length}/{slug}`).

- **Voice model:** [Supertonic 3](https://huggingface.co/Supertone/supertonic-3) by Supertone, run on
  GitHub's machines (no API, no per-character cost). Licence: OpenRAIL-M. Only the model's 10 built-in
  voices are used.
- **Voices:** English is Emily (F5), German is Alex (M1) at speed 0.95. The other languages alternate Jessica (F3) and Robert (M3) story
  by story. Speed 0.92, quality 12 steps. All are set at the top of `bb_audio.py`, or by the
  `BB_VOICES`, `BB_TTS_SPEED` and `BB_TTS_STEPS` environment variables.
- **When it runs:** when the main pipeline sends `brief-ready`, plus at 06:45 and 08:30 UTC as a
  backup. Articles that already have audio are skipped.

## How a run works

1. **plan**: fetches today's brief from the Worker, drops articles that already have audio, and
   splits the rest into up to 20 batches of equal size.
2. **speak**: one job per batch, all at once. Each reads its articles aloud, encodes MP3 (mono,
   48 kbps) and uploads to the `bilinguist-audio` bucket.
3. **check**: confirms every article has its MP3 and deletes days older than 14 (R2's free tier is
   10 GB).

## Secrets (Settings → Secrets and variables → Actions)

`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`: the same R2 keys the main pipeline
uses. Without them a run is a dry run: it reads everything aloud, uploads nothing, and reports the
speed.

## Run it locally

```bash
pip install -r requirements.txt
python bb_audio.py plan --limit 3 --batches 1
python bb_audio.py speak --batch 0      # without R2 keys the MP3s land in ./out
```
