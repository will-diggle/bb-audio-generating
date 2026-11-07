"""Tests for bb_audio.py, with R2 and the voice faked. No network.

    python3 test_bb_audio.py
"""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import bb_audio as A
import play_all as P

try:
    import numpy as np
except ImportError:
    np = None

DATE = "2026-11-03"
EN = {"genre": "US", "slug": "crash", "headline": "Learjet 60 (sixty) crashes", "headlineAudio": "Learjet 60 crashes",
      "body": "Nine (nine) died.", "bodyAudio": "Nine died."}
LEVEL = {"genre": "GLOBAL NEWS", "slug": "crash", "headline": "A plane crashed", "body": "Nine people died."}
KEY = f"{DATE}/en/Native/short/crash"


def queue():
    return {"date": DATE, "nativeJournalism": {"en": {"short": [dict(EN)]}}}


def brief():
    return {"date": DATE, "nativeJournalism": {"en": {"short": [dict(EN)]}},
            "briefings": {"en": {"A1": {"short": {"articles": [dict(LEVEL)]}}}}}


class FakeR2:
    def __init__(self, names=()):
        self.names = set(names)

    def put_object(self, Bucket, Key, Body, **_):
        self.names.add(Key)

    def delete_object(self, Bucket, Key):
        self.names.discard(Key)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.out = Path(self.dir.name) / "out"
        self.out.touch()
        cwd = os.getcwd()
        os.chdir(self.dir.name)
        self.addCleanup(os.chdir, cwd)
        env = mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(self.out)})
        env.start()
        self.addCleanup(env.stop)

    def plan(self, r2, approved=False, bundle=None, q=None, again=False):
        with mock.patch.object(A, "r2", lambda: r2), mock.patch.object(A, "today_utc", lambda: DATE), \
                mock.patch.object(A, "existing_keys", lambda c, d: set(c.names)), \
                mock.patch.object(A, "fetch_bundle", lambda: bundle or brief()), \
                mock.patch.object(A, "make_saved_parts", lambda *a: None), \
                mock.patch.object(A, "fetch_queue", lambda: q if q is not None else queue()), \
                mock.patch.object(A, "log"):
            A.cmd_plan(NS(date="", wait=0, batches=20, limit=0, approved=approved, again=again))
        plan = json.loads(A.PLAN.read_text()) if A.PLAN.exists() else {}
        return plan, self.out.read_text()


class TextTest(unittest.TestCase):
    def test_the_voice_never_gets_a_spelled_out_number(self):
        self.assertEqual(A.text_of(EN, "en"), "Learjet sixty crashes. Nine died.")
        self.assertEqual(A.text_of(LEVEL, "en"), "A plane crashed. Nine people died.")

    def test_invisible_marks_are_dropped_inside_words(self):
        # a soft hyphen in a Swedish native article lost its audio on 7 Nov 2026
        self.assertEqual(A.text_of({"headline": "Merz", "body": "presi\xaddent\u200b val\ufeff"}, "sv"),
                         "Merz. president val")

    def test_a_character_the_voice_refuses_is_dropped_even_when_it_prints_escaped(self):
        class TTS:
            said = []
            def get_voice_style(self, v): return v
            def synthesize(self, text, **_):
                TTS.said.append(text)
                if "\x07" in text:
                    raise ValueError("Found 1 unsupported character(s): " + repr(["\x07"]))
                return "wav", None
        self.assertEqual(A.synthesize(TTS(), {}, "Ett\x07två", "F3", "sv", 12), "wav")
        self.assertEqual(TTS.said[-1], "Ett två")

    def test_the_fingerprint_is_the_same_as_the_pipelines(self):
        # audio_queue.fingerprint in Claude-Routines' test_audio_queue.py has this same value
        self.assertEqual(A.fingerprint(EN), "7fad55e58bbe")


class ReaderTest(unittest.TestCase):
    def test_read_only_from_the_current_text(self):
        mark = f"{KEY}.mp3.{A.fingerprint(EN)}"
        self.assertTrue(A.reader({f"{KEY}.mp3", mark})(KEY, EN))
        self.assertFalse(A.reader({f"{KEY}.mp3", f"{KEY}.mp3.aaaaaaaaaaaa"})(KEY, EN))  # text changed
        self.assertFalse(A.reader({mark})(KEY, EN))                                     # no MP3
        self.assertFalse(A.reader(set())(KEY, EN))

    def test_an_mp3_from_before_marks_counts_as_read(self):
        self.assertTrue(A.reader({f"{KEY}.mp3"})(KEY, EN))


class PlanTest(Base):
    def test_approved_text_never_goes_in_the_public_plan_file(self):
        plan, out = self.plan(FakeR2(), approved=True)
        self.assertTrue(plan["approved"])
        self.assertEqual(len(plan["waves"]["gn"]), 1)
        self.assertEqual(plan["waves"]["rest"], [])
        self.assertNotIn("Learjet", A.PLAN.read_text())
        self.assertEqual(plan["waves"]["gn"][0][0]["mark"], A.fingerprint(EN))
        self.assertIn("source=approved", out)

    def test_read_again_reads_today_s_articles_even_if_read(self):
        done = {f"{KEY}.mp3", f"{KEY}.mp3.{A.fingerprint(EN)}", "play-all/en/uk.mp3"}
        plan, _ = self.plan(FakeR2(done), again=True)
        keys = [i["key"] for w in plan["waves"].values() for b in w for i in b]
        self.assertIn(KEY, keys)
        self.assertIn(f"{DATE}/en/A1/short/crash", keys)

    def test_a_publish_run_only_reads_what_is_left(self):
        done = {f"{KEY}.mp3", f"{KEY}.mp3.{A.fingerprint(EN)}"}
        plan, out = self.plan(FakeR2(done))
        keys = [i["key"] for w in plan["waves"].values() for b in w for i in b]
        self.assertEqual([k for k in keys if "play-all" not in k], [f"{DATE}/en/A1/short/crash"])
        self.assertIn("source=brief", out)

    def test_a_native_the_final_check_changed_is_read_again(self):
        old = f"{KEY}.mp3.aaaaaaaaaaaa"
        plan, _ = self.plan(FakeR2({f"{KEY}.mp3", old}))
        items = {i["key"]: i for w in plan["waves"].values() for b in w for i in b}
        self.assertEqual(items[KEY]["stale"], [old])

    def test_approved_articles_for_another_day_do_nothing(self):
        plan, out = self.plan(FakeR2(), approved=True, q={"date": "2026-11-02", "nativeJournalism": {}})
        self.assertEqual(plan, {})
        self.assertIn("gn_matrix=[]", out)

    def test_voices_stay_put_when_the_final_check_drops_a_story(self):
        two = {"date": DATE, "nativeJournalism": {"it": {"short": [
            dict(EN, slug="aaa"), dict(EN, slug="bbb")]}}}
        approved, _ = self.plan(FakeR2(), approved=True, q=two)
        was = {i["key"]: i["voice"] for b in approved["waves"]["gn"] for i in b}
        left = {"date": DATE, "briefings": {"it": {"A1": {"short": {"articles": [dict(LEVEL, slug="bbb")]}}}}}
        plan, _ = self.plan(FakeR2(), bundle=left, q=two)
        item = next(i for b in plan["waves"]["gn"] for i in b if i["key"] == f"{DATE}/it/A1/short/bbb")
        self.assertEqual(item["voice"], was[f"{DATE}/it/Native/short/bbb"])


class ReadyTest(Base):
    def run_ready(self, q, names):
        puts = []
        def api(path, method="GET", body=None, raw=False):
            if method == "PUT":
                puts.append(json.loads(A.base64.b64decode(body["content"])))
                return {}
            raise A.urllib.error.HTTPError("u", 404, "nope", None, None)
        with mock.patch.object(A, "r2", lambda: FakeR2(names)), mock.patch.object(A, "today_utc", lambda: DATE), \
                mock.patch.object(A, "existing_keys", lambda c, d: set(c.names)), \
                mock.patch.object(A, "fetch_queue", lambda: q), mock.patch.object(A, "_data_api", api), \
                mock.patch.object(A, "log"):
            A.cmd_ready(NS())
        return puts

    def test_it_lists_what_is_read_from_the_approved_text(self):
        q = {"date": DATE, "nativeJournalism": {"en": {"short": [dict(EN)]}, "de": {"short": [dict(EN)]}}}
        de = f"{DATE}/de/Native/short/crash"
        puts = self.run_ready(q, {f"{KEY}.mp3", f"{KEY}.mp3.{A.fingerprint(EN)}"})
        self.assertEqual(puts, [{"date": DATE, "read": {KEY: A.fingerprint(EN)}}])
        self.assertNotIn(de, puts[0]["read"])

    def test_english_alone_is_told_too(self):
        self.assertEqual(self.run_ready(queue(), {f"{KEY}.mp3"}), [{"date": DATE, "read": {KEY: A.fingerprint(EN)}}])

    def test_yesterdays_queue_makes_no_push(self):
        self.assertEqual(self.run_ready({"date": "2026-11-02", "nativeJournalism": {"de": {}}}, set()), [])


class PlayAllTest(Base):
    """The Play all intros and topic titles (Will, 3 Nov 2026)."""
    GN = {"genre": "GLOBAL NEWS", "slug": "a", "headline": "Plane 60 (sixty) crashes", "headlineAudio": "Plane 60 crashes",
          "body": "Secret text."}
    GN2 = {"genre": "GLOBAL NEWS", "slug": "b", "headline": "Ceasefire holds.", "body": "More."}
    UK = {"genre": "UK", "slug": "c", "headline": "Not a top story", "body": "Text."}

    def bundle(self):
        return {"date": DATE, "nativeJournalism": {"en": {"short": [dict(self.GN), dict(self.UK)]}},
                "briefings": {"en": {"A1": {"short": {"articles": [dict(self.GN2), dict(self.UK)]}}},
                              "hu": {"A1": {"short": {"articles": [dict(self.GN2)]}}}}}

    def test_every_language_has_all_its_words(self):
        for lang in P.GREETINGS:
            self.assertEqual(len(P.GREETINGS[lang]), 3, lang)
            self.assertEqual(len(P.WEEKDAYS[lang]), 7, lang)
            self.assertEqual(len(P.MONTHS[lang]), 12, lang)
            self.assertEqual(len(P.DAYS[lang]), 31, lang)
            self.assertEqual(set(P.TITLES[lang]), set(P.TOPICS), lang)
            self.assertIn("Bilinguist Brief", P.greeting_line(lang, "morning"), lang)
            self.assertEqual(len(P.saved_lines(lang)), 6 if lang == "en" else 5, lang)

    def test_the_greeting_says_the_time_and_the_day(self):
        self.assertEqual(P.greeting_line("en", "evening"), "Good evening and welcome to the Bilinguist Brief.")
        self.assertEqual(P.intro_title("en"), "The Bilinguist Brief. Global News.")
        self.assertEqual(P.HEADLINES["en"], "Here are today's top headlines.")
        self.assertEqual(P.day_line("en", DATE), "Today is Tuesday the third of November.")
        self.assertIn("Dienstag, der dritte November", P.day_line("de", DATE))
        self.assertIn("treinta y uno de diciembre", P.day_line("es", "2026-12-31"))
        self.assertIn("vinte e cinco de dezembro", P.day_line("pt", "2026-12-25"))

    def test_each_edition_gets_its_own_global_news_headlines(self):
        heads = A.intro_headlines(self.bundle())
        self.assertEqual(heads, {f"{DATE}/en/A1/short/_play-all": "Ceasefire holds.",
                                 f"{DATE}/en/Native/short/_play-all": "Plane sixty crashes."})    # no hu: no words for it

    def test_a_publish_run_plans_the_intros_and_titles_in_the_first_wave(self):
        plan, _ = self.plan(FakeR2(), bundle=self.bundle())
        first = {i["key"]: i for b in plan["waves"]["gn"] for i in b}
        self.assertTrue(first[f"{DATE}/en/A1/short/_play-all"]["intro"])
        self.assertEqual(first[f"{DATE}/en/A1/short/_play-all"]["text"], "Ceasefire holds.")
        self.assertEqual(first["play-all/en/uk"]["text"], "United Kingdom")
        self.assertEqual(first["play-all/en/free-message"]["lang"], "en")
        self.assertIn("Plus", first["play-all/en/free-message"]["text"])

    def test_an_approved_plan_never_holds_a_headline(self):
        q = {"date": DATE, "nativeJournalism": {"en": {"short": [dict(self.GN)]}}}
        plan, _ = self.plan(FakeR2(), approved=True, bundle=q, q=q)
        self.assertNotIn("crashes", json.dumps(plan))
        self.assertIn(f"{DATE}/en/Native/short/_play-all", json.dumps(plan))
        self.assertIn("United Kingdom", json.dumps(plan))                      # a title is no secret

    def test_what_is_made_is_left_and_a_changed_headline_is_made_again(self):
        key = f"{DATE}/en/A1/short/_play-all"
        mark = A.fingerprint(A.intro_article("Ceasefire holds."))
        last = f"{key}{A.LAST_INTRO}.mp3"
        title_marks = {f"play-all/en/{n}.mp3.{A.fingerprint({'bodyAudio': P.TITLES['en'][g]})}" for g, n in P.TOPICS.items()}
        title_marks.add(f"play-all/en/free-message.mp3.{A.fingerprint({'bodyAudio': P.FREE_MESSAGE})}")
        have = {last, f"{last}.{mark}"} | title_marks | {m.rsplit(".", 1)[0] for m in title_marks}
        plan, _ = self.plan(FakeR2(have), bundle=self.bundle())
        keys = [i["key"] for b in plan["waves"]["gn"] for i in b]
        self.assertNotIn(key, keys)
        self.assertFalse([k for k in keys if k.startswith("play-all/")])
        changed = self.bundle()
        changed["briefings"]["en"]["A1"]["short"]["articles"][0]["headline"] = "Ceasefire ends."
        plan, _ = self.plan(FakeR2(have), bundle=changed)
        item = next(i for b in plan["waves"]["gn"] for i in b if i["key"] == key)
        self.assertEqual(item["stale"], [f"{last}.{mark}"])

    def test_old_intros_go_first(self):
        self.assertTrue(A.expired("2026-11-01/en/A1/short/_play-all-morning.mp3", "2026-10-20", "2026-11-02"))
        self.assertFalse(A.expired("2026-11-02/en/A1/short/_play-all-morning.mp3", "2026-10-20", "2026-11-02"))
        self.assertFalse(A.expired("2026-11-01/en/A1/short/a-story.mp3", "2026-10-20", "2026-11-02"))
        self.assertFalse(A.expired("play-all/en/uk.mp3", "2026-10-20", "2026-11-02"))

    @unittest.skipUnless(np, "needs numpy")
    def test_the_files_are_made_ending_with_the_one_that_says_its_done(self):
        said, saved = [], {}

        def say(line, lang=None):
            said.append((line, lang))
            return np.ones(1000 if line != P.FREE_MESSAGE else 3000, dtype=np.float32)

        key = f"{DATE}/de/A1/longer/_play-all"
        A.read_intros({"key": key, "lang": "de", "text": "Eins.\nZwei."}, DATE, say, None, 1000,
                      lambda k, samples: saved.update({k: samples}))
        self.assertEqual(list(saved)[-1], key + A.LAST_INTRO)
        self.assertEqual(len(saved), 6)                                        # no free reader gets this edition
        self.assertGreater(len(saved[f"{key}-morning"]), len(saved[f"{key}-morning-no-title"]))
        self.assertEqual(said.count((P.intro_title("de"), None)), 1)
        self.assertEqual(said.count((P.day_line("de", DATE), None)), 1)
        self.assertEqual(said.count((P.HEADLINES["de"], None)), 1)
        said.clear(), saved.clear()
        key = f"{DATE}/de/A1/short/_play-all"
        A.read_intros({"key": key, "lang": "de", "text": "Eins.\nZwei."}, DATE, say, None, 1000,
                      lambda k, samples: saved.update({k: samples}))
        self.assertEqual(len(saved), 9)
        self.assertEqual(list(saved)[-1], key + A.LAST_INTRO)
        self.assertGreater(len(saved[f"{key}-morning-free"]), len(saved[f"{key}-morning"]))
        self.assertEqual(said.count((P.FREE_MESSAGE, "en")), 1)                # English, whatever the language

    def test_shared_lines_keep_where_they_belong(self):
        self.assertEqual(A.saved_part_key(P.day_line("en", DATE), "en", DATE), f"{DATE}/en/_play-all-day.f32")
        key = A.saved_part_key(P.HEADLINES["en"], "en", DATE)
        self.assertTrue(key.startswith("play-all/en/parts/"))
        self.assertTrue(A.expired("2026-11-01/en/_play-all-day.f32", "2026-10-20", "2026-11-02"))
        self.assertFalse(A.expired(key, "2026-10-20", "2026-11-02"))
        self.assertIsNone(A.saved_part(FakeR2(), "A headline.", "en", DATE))     # a headline is never saved

    @unittest.skipUnless(np, "needs numpy")
    def test_a_tracks_silent_start_goes_and_it_is_levelled(self):
        raw = np.concatenate([np.zeros(100, dtype=np.float32), np.full(1000, 0.5, dtype=np.float32)]).tobytes()
        with mock.patch.dict(os.environ, {"BB_NEWS_MUSIC": "track.mp3"}), \
                mock.patch.object(A.subprocess, "run", lambda *a, **k: NS(stdout=raw)):
            music = A.news_music(None, 100)
        self.assertEqual(len(music), 1000)
        self.assertAlmostEqual(float(music[0]), A.MUSIC_LOUDNESS, places=4)

    @unittest.skipUnless(np, "needs numpy")
    def test_the_music_comes_first_and_is_gone_at_the_end(self):
        rate = 1000
        voice = np.zeros(10 * rate, dtype=np.float32)
        out = A.over_music(voice, np.ones(rate, dtype=np.float32) * 0.1, rate)
        self.assertEqual(len(out), int((A.INTRO_LEAD + 10 + A.INTRO_TAIL) * rate))
        self.assertAlmostEqual(float(out[0]), 0.1 * A.MUSIC_ALONE, places=3)
        self.assertAlmostEqual(float(out[len(out) // 2]), 0.1 * A.MUSIC_UNDER, places=3)
        self.assertLess(abs(float(out[-1])), 0.001)
        self.assertEqual(len(A.over_music(voice, None, rate)), 10 * rate + rate // 2)   # no music: still made


class SpeakTest(Base):
    def test_it_marks_what_it_read_and_clears_the_old_mark(self):
        old = f"{KEY}.mp3.aaaaaaaaaaaa"
        r2 = FakeR2({f"{KEY}.mp3", old})
        A.PLAN.write_text(json.dumps({"date": DATE, "approved": True, "waves": {"gn": [[
            {"key": KEY, "lang": "en", "voice": "F5", "mark": A.fingerprint(EN), "stale": [old]}]], "rest": []}}))

        class TTS:
            sample_rate = 24000
            def __init__(self, model): pass
            def get_voice_style(self, v): return v
            def synthesize(self, text, **_):
                self.text = text
                TTS.said = text
                return mock.Mock(reshape=lambda *_: mock.Mock(shape=(1,))), None
            def save_audio(self, wav, path): Path(path).touch()

        def ffmpeg(cmd, check):
            Path(cmd[-1]).write_bytes(b"mp3")

        with mock.patch.dict(sys.modules, {"supertonic": types.SimpleNamespace(TTS=TTS)}), \
                mock.patch.object(A, "r2", lambda: r2), mock.patch.object(A, "fetch_queue", queue), \
                mock.patch.object(A.subprocess, "run", ffmpeg), mock.patch.object(A, "log"):
            A.cmd_speak(NS(wave="gn", batch=0, steps=12))
        self.assertEqual(TTS.said, "Learjet sixty crashes. Nine died.")   # from the private branch
        self.assertIn(f"{KEY}.mp3", r2.names)
        self.assertIn(f"{KEY}.mp3.{A.fingerprint(EN)}", r2.names)
        self.assertNotIn(old, r2.names)


class LabelTest(Base):
    def test_a_stale_mp3_is_not_labelled(self):
        root = Path(self.dir.name)
        (root / "briefings").mkdir()
        text = json.dumps(brief(), indent=2, ensure_ascii=False)
        (root / "latest.json").write_text(text)
        (root / "briefings" / f"{DATE}.json").write_text(text)
        have = {f"{KEY}.mp3", f"{KEY}.mp3.aaaaaaaaaaaa",
                f"{DATE}/en/A1/short/crash.mp3", f"{DATE}/en/A1/short/crash.mp3.{A.fingerprint(LEVEL)}"}
        added, _ = A.label_files(root, have)
        self.assertEqual(added, 1)
        d = json.loads((root / "latest.json").read_text())
        self.assertNotIn("audioKey", d["nativeJournalism"]["en"]["short"][0])
        self.assertEqual(d["briefings"]["en"]["A1"]["short"]["articles"][0]["audioKey"], f"{DATE}/en/A1/short/crash")


if __name__ == "__main__":
    unittest.main()
