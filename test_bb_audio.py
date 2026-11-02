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

    def plan(self, r2, approved=False, bundle=None, q=None):
        with mock.patch.object(A, "r2", lambda: r2), mock.patch.object(A, "today_utc", lambda: DATE), \
                mock.patch.object(A, "existing_keys", lambda c, d: set(c.names)), \
                mock.patch.object(A, "fetch_bundle", lambda: bundle or brief()), \
                mock.patch.object(A, "fetch_queue", lambda: q if q is not None else queue()), \
                mock.patch.object(A, "log"):
            A.cmd_plan(NS(date="", wait=0, batches=20, limit=0, approved=approved))
        plan = json.loads(A.PLAN.read_text()) if A.PLAN.exists() else {}
        return plan, self.out.read_text()


class TextTest(unittest.TestCase):
    def test_the_voice_never_gets_a_spelled_out_number(self):
        self.assertEqual(A.text_of(EN), "Learjet 60 crashes. Nine died.")
        self.assertEqual(A.text_of(LEVEL), "A plane crashed. Nine people died.")

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

    def test_a_publish_run_only_reads_what_is_left(self):
        done = {f"{KEY}.mp3", f"{KEY}.mp3.{A.fingerprint(EN)}"}
        plan, out = self.plan(FakeR2(done))
        keys = [i["key"] for w in plan["waves"].values() for b in w for i in b]
        self.assertEqual(keys, [f"{DATE}/en/A1/short/crash"])
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
        item = plan["waves"]["gn"][0][0]
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

    def test_english_alone_makes_no_push(self):
        self.assertEqual(self.run_ready(queue(), {f"{KEY}.mp3"}), [])

    def test_yesterdays_queue_makes_no_push(self):
        self.assertEqual(self.run_ready({"date": "2026-11-02", "nativeJournalism": {"de": {}}}, set()), [])


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
        self.assertEqual(TTS.said, "Learjet 60 crashes. Nine died.")   # from the private branch
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
