"""Offline regression tests: no model calls or Telegram edits leave this process."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import content_memory as cm
import daily_ai_curator as curator
from editorial import make_brief, validate_response


class EditorialTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.memory = cm.load_memory(Path(directory.name) / 'memory.json')
        self.corpus = cm.load_corpus()
        self.brief = make_brief('Example Artist', 'Example Title', 'Pop', True, False, self.memory, self.corpus)
        self.poem = next(p for p in self.brief['inspirations'] if p['language'] == 'en')
        self.output = dict(language='en', sentence='Fold the map until the distance fits inside a coat.',
                           hashtags=[], poem_id=self.poem['id'])

    def validate(self, output=None, brief=None):
        return validate_response(json.dumps(output or self.output), brief or self.brief, self.memory, self.corpus)

    def test_corpus_is_bilingual_and_sourced(self):
        self.assertGreaterEqual(len(self.corpus), 48)
        for lang in ('fa', 'en'):
            self.assertGreaterEqual(sum(p['language'] == lang for p in self.corpus), 24)
        self.assertTrue(all(p['source'].startswith('https://') and p['rights'] for p in self.corpus))

    def test_normalization_blocks_persian_variants(self):
        a, b = '«يك خانه‌ی روشن.»', '<b>یک خانه ی روشن!</b>'
        self.assertEqual(cm.fingerprint(a), cm.fingerprint(b))

    def test_exact_memory_survives_recent_window(self):
        record = self.validate()
        cm.remember(self.memory, record)
        self.memory['recent'] = []
        self.assertTrue(cm.repeated(record['text'], self.memory))

    def test_near_duplicate_and_same_opening_rejected(self):
        cm.remember(self.memory, self.validate())
        for text in ('Fold the map until all the distance fits inside a coat.',
                     'Fold the map beneath a different afternoon.'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.validate(dict(self.output, sentence=text))

    def test_pending_source_and_text_reserved(self):
        self.memory['pending']['42'] = self.validate()
        for _ in range(30):
            brief = make_brief('A', 'B', 'Pop', True, False, self.memory, self.corpus)
            self.assertNotIn(self.poem['id'], [p['id'] for p in brief['inspirations']])
        with self.assertRaises(ValueError):
            self.validate()

    def test_used_sources_never_recycled_after_exhaustion(self):
        self.memory['used_poem_ids'] = [p['id'] for p in self.corpus]
        brief = make_brief('A', 'B', 'Pop', True, False, self.memory, self.corpus)
        self.assertEqual(brief['inspirations'], [])
        result = self.validate(dict(self.output, poem_id=None), brief)
        self.assertIsNone(result['poem_id'])

    def test_bad_output_never_published(self):
        for changes in ({'sentence': 'In the room, a door waits.'}, {'sentence': '<i>Do this.</i>'},
                        {'sentence': 'Something remains'}, {'sentence': 'One thing. Another thing.'},
                        {'sentence': 'An umbrella waits. 🌧'}, {'poem_id': 'invented'},
                        {'sentence': 'Example Artist left a map.'}, {'hashtags': ['#Pop']},
                        {'language': 'fa'}, {'sentence': ' Leading whitespace.'},
                        {'sentence': '你好。.'}, {'sentence': self.poem['text'] + '.'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.validate(dict(self.output, **changes))

    def test_persian_caption_and_html_are_rendered_in_code(self):
        poem = next(p for p in self.brief['inspirations'] if p['language'] == 'fa')
        result = self.validate(dict(language='fa', sentence='چمدان کنار پنجره بوی راه نرفته می‌دهد.',
                                    hashtags=[], poem_id=poem['id']))
        self.assertEqual(result['caption'], '<b>«چمدان کنار پنجره بوی راه نرفته می‌دهد.»</b>')
        self.assertEqual(result['author'], poem['author'])

    def test_tags_only_does_not_consume_poetry(self):
        brief = make_brief('A', 'B', 'Pop', False, True, self.memory, self.corpus)
        result = self.validate(dict(language='fa', sentence='', hashtags=['#پاپ', '#Pop', '#Melancholy'], poem_id=None), brief)
        self.assertEqual(result['caption'], '#پاپ #Pop #Melancholy')
        self.assertIsNone(result['poem_id'])
        self.assertEqual(brief['inspirations'], [])

    def test_styles_and_lenses_rotate(self):
        self.memory['recent'] = [dict(text='old', style='action', lens='body')]
        for _ in range(30):
            brief = make_brief('A', 'B', 'Pop', True, False, self.memory, self.corpus)
            self.assertNotEqual(brief['style'], 'action')
            self.assertNotEqual(brief['lens'], 'body')

    def test_retries_are_bounded_and_fetch_metadata_once(self):
        with patch.object(curator, 'call_groq', return_value='bad') as call, patch.object(curator, 'fetch_itunes_metadata', return_value='Pop') as fetch:
            self.assertIsNone(curator.generate_ai_content('A', 'B', True, False, self.memory, self.corpus))
        self.assertEqual(call.call_count, 3)
        fetch.assert_called_once()

    def test_invalid_memory_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'memory.json'
            path.write_text('{"version":1}')
            with self.assertRaises(ValueError):
                cm.load_memory(path)
            path.write_text('{')
            with self.assertRaises(ValueError):
                cm.load_memory(path)

    def test_remember_is_idempotent(self):
        record = self.validate()
        cm.remember(self.memory, record)
        cm.remember(self.memory, record)
        self.assertEqual(len(self.memory['recent']), 1)
        self.assertEqual(self.memory['used_poem_ids'], [record['poem_id']])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.directory.name)
        self.record = dict(caption='<b>"A small window keeps the afternoon folded."</b>',
                           text='A small window keeps the afternoon folded.',
                           poem_id='source-1', author='Writer', style='object', lens='light')
        cm.save_json('daily_log.json', [dict(message_id=42, title='Track', performer='Artist', caption='')])
        self.patches = [patch.object(curator, 'GROQ_API_KEY', 'test'), patch.object(curator.time, 'sleep')]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        os.chdir(self.old_cwd)
        self.directory.cleanup()

    def read_queue(self):
        return json.loads(Path('daily_log.json').read_text())

    def test_success_remembers_source_and_removes_queue(self):
        with patch.object(curator, 'generate_ai_content', return_value=copy.deepcopy(self.record)), patch.object(curator.telegram_client, 'edit_message_caption', return_value={'ok': True}):
            curator.main()
        self.assertEqual(self.read_queue(), [])
        self.assertEqual(cm.load_memory()['used_poem_ids'], ['source-1'])
        self.assertEqual(cm.load_memory()['pending'], {})

    def test_failure_retains_caption_then_retry_reuses_it(self):
        with patch.object(curator, 'generate_ai_content', return_value=copy.deepcopy(self.record)), patch.object(curator.telegram_client, 'edit_message_caption', return_value=None):
            curator.main()
        self.assertEqual(len(self.read_queue()), 1)
        self.assertEqual(cm.load_memory()['used_poem_ids'], [])
        self.assertIn('42', cm.load_memory()['pending'])
        with patch.object(curator, 'generate_ai_content') as generate, patch.object(curator.telegram_client, 'edit_message_caption', return_value={'ok': True, 'ignored': True}) as edit:
            curator.main()
        generate.assert_not_called()
        edit.assert_called_once_with(42, self.record['caption'])
        self.assertEqual(self.read_queue(), [])

    def test_invalid_generation_keeps_queue_and_does_not_edit(self):
        with patch.object(curator, 'generate_ai_content', return_value=None), patch.object(curator.telegram_client, 'edit_message_caption') as edit:
            curator.main()
        edit.assert_not_called()
        self.assertEqual(len(self.read_queue()), 1)

    def test_existing_caption_is_preserved_and_only_tags_added(self):
        cm.save_json('daily_log.json', [dict(message_id=42, caption='متن من <3 & موسیقی')])
        tags = dict(self.record, text='', caption='#پاپ #Pop #Calm', poem_id=None, author=None)
        with patch.object(curator, 'generate_ai_content', return_value=tags) as generate, patch.object(curator.telegram_client, 'edit_message_caption', return_value={'ok': True}) as edit:
            curator.main()
        self.assertEqual(generate.call_args.args[2:4], (False, True))
        edit.assert_called_once_with(42, 'متن من &lt;3 &amp; موسیقی\n\n#پاپ #Pop #Calm')
        self.assertEqual(cm.load_memory()['used_poem_ids'], [])

    def test_complete_caption_is_untouched(self):
        cm.save_json('daily_log.json', [dict(message_id=42, caption='متن #آرام')])
        with patch.object(curator, 'generate_ai_content') as generate, patch.object(curator.telegram_client, 'edit_message_caption') as edit:
            curator.main()
        generate.assert_not_called()
        edit.assert_not_called()
        self.assertEqual(self.read_queue(), [])

    def test_oversized_manual_caption_is_not_truncated(self):
        cm.save_json('daily_log.json', [dict(message_id=42, caption='a' * 1024)])
        tags = dict(self.record, text='', caption='#Pop #Calm #Jazz', poem_id=None)
        with patch.object(curator, 'generate_ai_content', return_value=tags), patch.object(curator.telegram_client, 'edit_message_caption') as edit:
            curator.main()
        edit.assert_not_called()
        self.assertEqual(self.read_queue()[0]['caption'], 'a' * 1024)

    def test_orphaned_journal_is_cleaned_conservatively(self):
        memory = cm.load_memory()
        memory['pending']['41'] = dict(self.record, original_caption='')
        cm.save_json('content_memory.json', memory)
        cm.save_json('daily_log.json', [])
        curator.main()
        self.assertEqual(cm.load_memory()['pending'], {})
        self.assertEqual(cm.load_memory()['used_poem_ids'], ['source-1'])

    def test_metadata_genre_avoids_duplicate_lookup(self):
        with patch.object(curator, 'fetch_itunes_metadata') as fetch, patch.object(curator, 'call_groq', return_value=None):
            curator.generate_ai_content('A', 'B', True, False, cm.load_memory(), cm.load_corpus(), ['Pop'])
        fetch.assert_not_called()

    def test_crash_after_telegram_success_replays_journal(self):
        real_save = curator.save_json
        def interrupted_save(path, data):
            if path == 'daily_log.json':
                raise OSError('simulated interrupted queue write')
            real_save(path, data)
        with patch.object(curator, 'generate_ai_content', return_value=copy.deepcopy(self.record)), patch.object(curator.telegram_client, 'edit_message_caption', return_value={'ok': True}), patch.object(curator, 'save_json', side_effect=interrupted_save):
            with self.assertRaises(OSError):
                curator.main()
        with patch.object(curator, 'generate_ai_content') as generate, patch.object(curator.telegram_client, 'edit_message_caption', return_value={'ok': True, 'ignored': True}):
            curator.main()
        generate.assert_not_called()
        self.assertEqual(len(cm.load_memory()['recent']), 1)
        self.assertEqual(self.read_queue(), [])


if __name__ == '__main__':
    unittest.main()
