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
        return [entry['artist'] for entry in registry.load_catalogue()]

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
        self.assertEqual(registry.load_catalogue(), [])

    def test_group_names_and_collaboration_credits_stay_intact(self):
        registry.record_artists(['Florence & The Machine', 'Reza Pishro & Yas & Tech N9ne'])
        self.assertEqual(self.names(), ['Florence & The Machine', 'Reza Pishro & Yas & Tech N9ne'])

    def test_no_change_does_not_rewrite_file(self):
        registry.record_artists(['Sia'])
        with patch.object(registry.os, 'replace') as replace:
            self.assertEqual(registry.record_artists(['SIA']), [])
        replace.assert_not_called()

    def test_malformed_catalogue_is_not_silently_reset(self):
        registry.ARTISTS_FILE.parent.mkdir()
        registry.ARTISTS_FILE.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ValueError):
            registry.record_tracks([{'performer': 'Sia', 'title': 'Snowman'}])
        self.assertEqual(registry.ARTISTS_FILE.read_text(), '{broken')

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

    def test_history_pairs_titles_from_complete_snapshots(self):
        # A later change can replace only a title; parsing added diff lines loses the artist.
        results = [subprocess.CompletedProcess([], 0, stdout='abc\ndef\n'),
                   subprocess.CompletedProcess([], 0, stdout=json.dumps([
                       {'performer': 'Sia', 'title': 'Snowman'}])),
                   subprocess.CompletedProcess([], 0, stdout=json.dumps([
                       {'performer': 'Sia', 'title': 'Chandelier'},
                       {'performer': 'Korn', 'title': 'Word Up!'}]))]
        with patch.object(registry.subprocess, 'run', side_effect=results):
            registry.seed_from_git_history()
        self.assertEqual(registry.load_catalogue(), [
            {'artist': 'Sia', 'tracks': ['Snowman', 'Chandelier']},
            {'artist': 'Korn', 'tracks': ['Word Up!']}])

    def test_listener_collects_fully_captioned_and_already_queued_tracks(self):
        Path('daily_log.json').write_text(json.dumps([{'message_id': 2}]))
        payload = {'ok': True, 'result': [
            {'update_id': 1, 'channel_post': {'message_id': 1, 'chat': {'id': -100},
             'audio': {'performer': 'Sia', 'title': 'Snowman'}, 'caption': 'Done #Pop'}},
            {'update_id': 2, 'channel_post': {'message_id': 2, 'chat': {'id': -100},
             'audio': {'performer': 'Korn', 'title': 'Word Up!'}, 'caption': ''}}]}
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        with patch.object(listener, 'BOT_TOKEN', 'token'), patch.object(listener, 'CHANNEL_ID', '-100'), patch.object(listener.urllib.request, 'urlopen', return_value=response):
            listener.main()
        self.assertEqual(self.names(), ['Sia', 'Korn'])
        self.assertEqual(json.loads(Path('daily_log.json').read_text()), [{'message_id': 2}])
        self.assertEqual(registry.load_catalogue(), [
            {'artist': 'Sia', 'tracks': ['Snowman']},
            {'artist': 'Korn', 'tracks': ['Word Up!']}])

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

    def test_new_song_updates_same_artist_row_without_duplicate_titles(self):
        registry.record_tracks([{'performer': 'Sia', 'title': 'Snowman'}])
        registry.record_tracks([{'performer': 'SIA', 'title': 'SNOWMAN'},
                                {'performer': 'sia', 'title': 'Chandelier'},
                                {'performer': 'Korn', 'title': 'Snowman'}])
        self.assertEqual(registry.load_catalogue(), [
            {'artist': 'Sia', 'tracks': ['Snowman', 'Chandelier']},
            {'artist': 'Korn', 'tracks': ['Snowman']}])
        table = registry.MARKDOWN_FILE.read_text()
        self.assertIn('| 1 | Sia | 1. Snowman<br>2. Chandelier |', table)
        self.assertEqual(table.count('| Sia |'), 1)

    def test_markdown_escapes_untrusted_metadata(self):
        registry.record_tracks([{'performer': 'A | B', 'title': '<b>Song</b> | [link](url) *test*'}])
        table = registry.MARKDOWN_FILE.read_text()
        self.assertIn('A &#124; B', table)
        self.assertIn('&lt;b&gt;Song&lt;/b&gt; &#124;', table)
        self.assertNotIn('[link](url)', table)
        self.assertEqual(len(table.splitlines()[-1].split('|')), 5)

    def test_lost_markdown_render_is_repaired_without_duplicating_titles(self):
        registry.record_tracks([{'performer': 'Sia', 'title': 'Snowman'}])
        registry.MARKDOWN_FILE.unlink()
        registry.record_tracks([{'performer': 'Sia', 'title': 'Snowman'}])
        self.assertIn('1. Snowman', registry.MARKDOWN_FILE.read_text())
        self.assertEqual(registry.load_catalogue()[0]['tracks'], ['Snowman'])

    def test_legacy_list_migrates_and_unknown_titles_are_not_invented(self):
        registry.LEGACY_FILE.parent.mkdir()
        registry.LEGACY_FILE.write_text('Sia\nKorn\n')
        Path('daily_log.json').write_text(json.dumps([
            {'performer': 'Sia', 'title': 'Snowman'},
            {'performer': 'Korn', 'title': 'Unknown Title'}]))
        with patch.object(sys, 'argv', ['artist_registry.py']):
            registry.main()
            registry.main()
        self.assertEqual(registry.load_catalogue(), [
            {'artist': 'Sia', 'tracks': ['Snowman']}, {'artist': 'Korn', 'tracks': []}])
        self.assertIn('| 2 | Korn | — |', registry.MARKDOWN_FILE.read_text())


if __name__ == '__main__':
    unittest.main()
