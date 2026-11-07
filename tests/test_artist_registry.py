"""Artist collection is independent of caption generation and external APIs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import artist_registry as registry
import music_listener as listener
import agent_downloader as downloader
import telegram_api


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous = os.getcwd()
        os.chdir(self.directory.name)

    def tearDown(self):
        os.chdir(self.previous)
        self.directory.cleanup()

    def names(self):
        return registry.ARTISTS_FILE.read_text(encoding='utf-8').splitlines()

    def test_append_and_reload_preserve_spelling_and_first_seen_order(self):
        registry.record_artists(['  Sia  ', 'داریوش', 'Sia'])
        self.assertEqual(registry.record_artists(['sia', 'Korn']), ['Korn'])
        self.assertEqual(self.names(), ['Sia', 'داریوش', 'Korn'])

    def test_arabic_persian_variants_diacritics_and_spacing_do_not_duplicate(self):
        registry.record_artists(['علي كريمي', 'همایون شجریان.'])
        registry.record_artists(['علی کریمی', 'عَلِي كَرِيمِي', 'همایون   شجریان'])
        self.assertEqual(len(self.names()), 2)

    def test_missing_names_placeholders_and_handles_are_ignored(self):
        registry.record_artists([None, 123, '', 'Unknown Artist', 'UNKNOWN', 'ناشناس',
                                '@MusicChannel', 'https://example.com', 't.me/music', '1234'])
        self.assertFalse(registry.ARTISTS_FILE.exists())

    def test_group_names_and_collaboration_credits_stay_intact(self):
        registry.record_artists(['Florence & The Machine', 'Reza Pishro & Yas & Tech N9ne'])
        self.assertEqual(self.names(), ['Florence & The Machine', 'Reza Pishro & Yas & Tech N9ne'])

    def test_no_change_does_not_rewrite_file(self):
        registry.record_artists(['Sia'])
        with patch.object(registry.os, 'replace') as replace:
            self.assertEqual(registry.record_artists(['SIA']), [])
        replace.assert_not_called()

    def test_existing_file_without_newline_is_appended_safely(self):
        registry.ARTISTS_FILE.parent.mkdir()
        registry.ARTISTS_FILE.write_text('Sia', encoding='utf-8')
        registry.record_artists(['Korn'])
        self.assertEqual(self.names(), ['Sia', 'Korn'])

    def test_interrupted_replacement_preserves_previous_registry(self):
        registry.record_artists(['Sia'])
        with patch.object(registry.os, 'replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                registry.record_artists(['Korn'])
        self.assertEqual(self.names(), ['Sia'])

    def test_channel_filter_collects_even_captioned_or_edited_audio(self):
        def post(artist, channel='-100', key='channel_post'):
            return {key: dict(chat={'id': channel}, audio={'performer': artist}, caption='Ready #Pop')}
        updates = [post('Sia'), post('Korn', key='edited_channel_post'), post('Wrong channel', channel='-200'),
                   {'message': {'audio': {'performer': 'Unpublished'}}}]
        registry.collect_channel_artists(updates, '-100')
        self.assertEqual(self.names(), ['Sia', 'Korn'])

    def test_missing_channel_configuration_collects_nothing(self):
        registry.collect_channel_artists([{'channel_post': {'audio': {'performer': 'Sia'}}}], '')
        self.assertFalse(registry.ARTISTS_FILE.exists())

    def test_history_seeding_reads_only_added_performer_fields(self):
        diff = '+    "performer": "Sia",\n-    "performer": "Removed",\n+    "title": "A song",\n+    "performer": "Guns N\' Roses",\n'
        result = subprocess.CompletedProcess([], 0, stdout=diff)
        with patch.object(registry.subprocess, 'run', return_value=result):
            registry.seed_from_git_history()
        self.assertEqual(self.names(), ['Sia', "Guns N' Roses"])

    def test_listener_collects_fully_captioned_and_already_queued_tracks(self):
        Path('daily_log.json').write_text(json.dumps([{'message_id': 2}]))
        payload = {'ok': True, 'result': [
            {'update_id': 1, 'channel_post': {'message_id': 1, 'chat': {'id': -100},
             'audio': {'performer': 'Sia'}, 'caption': 'Done #Pop'}},
            {'update_id': 2, 'channel_post': {'message_id': 2, 'chat': {'id': -100},
             'audio': {'performer': 'Korn'}, 'caption': ''}}]}
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        with patch.object(listener, 'BOT_TOKEN', 'token'), patch.object(listener, 'CHANNEL_ID', '-100'), patch.object(listener.urllib.request, 'urlopen', return_value=response):
            listener.main()
        self.assertEqual(self.names(), ['Sia', 'Korn'])
        self.assertEqual(json.loads(Path('daily_log.json').read_text()), [{'message_id': 2}])

    def test_downloader_poll_also_collects_target_channel_posts(self):
        update = {'update_id': 1, 'channel_post': {'chat': {'id': -100}, 'audio': {'performer': 'Sia'}}}
        with patch.object(downloader, 'BOT_TOKEN', 'token'), patch.object(downloader, 'CHANNEL_ID', '-100'), patch.object(downloader, 'ADMIN_ID', '123'), patch.object(telegram_api, 'get_updates', return_value=[update]), patch.object(telegram_api, 'send_audio_file_id') as send:
            downloader.main()
        self.assertEqual(self.names(), ['Sia'])
        send.assert_not_called()

    def test_bootstrap_from_queue_is_idempotent(self):
        Path('daily_log.json').write_text(json.dumps([{'performer': 'Sia'}, {'performer': 'Korn'}]))
        with patch.object(sys, 'argv', ['artist_registry.py']):
            registry.main()
            registry.main()
        self.assertEqual(self.names(), ['Sia', 'Korn'])


if __name__ == '__main__':
    unittest.main()
