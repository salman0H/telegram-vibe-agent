"""Regression coverage for long/large audio without making Telegram requests."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import agent_downloader as downloader
import telegram_api


class DownloaderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.directory.name)
        self.patches = [patch.object(downloader, 'BOT_TOKEN', 'test-token'),
                        patch.object(downloader, 'CHANNEL_ID', '-100test'),
                        patch.object(downloader, 'ADMIN_ID', '123'),
                        patch.object(downloader.time, 'sleep')]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        os.chdir(self.old_cwd)
        self.directory.cleanup()

    def audio_update(self, **changes):
        audio = dict(file_id='telegram-audio', file_size=30_000_000, duration=600,
                     performer='Artist', title='Long track', file_name='song.mp3')
        audio.update(changes)
        return dict(update_id=1, message=dict(message_id=2, **{'from': {'id': 123}}, audio=audio))

    def test_ten_minute_large_audio_skips_download_and_local_upload(self):
        update = self.audio_update()
        with patch.object(telegram_api, 'get_updates', return_value=[update]), patch.object(telegram_api, 'send_message', return_value={'result': {'message_id': 3}}), patch.object(telegram_api, 'edit_message_text'), patch.object(telegram_api, 'send_audio_file_id', return_value={'ok': True, 'result': {'message_id': 42}}) as reuse, patch.object(downloader, 'download_telegram_file') as download, patch.object(telegram_api, 'send_audio') as upload:
            downloader.main()
        download.assert_not_called()
        upload.assert_not_called()
        reuse.assert_called_once_with('test-token', '-100test', 'telegram-audio', caption='', performer='Artist', title='Long track')
        self.assertEqual(Path('data/artists.txt').read_text(), 'Artist\n')
        queue = json.loads(Path('daily_log.json').read_text())
        self.assertEqual(queue, [dict(message_id=42, performer='Artist', title='Long track', caption='')])

    def test_failed_reuse_does_not_queue_a_nonexistent_channel_post(self):
        with patch.object(telegram_api, 'get_updates', return_value=[self.audio_update()]), patch.object(telegram_api, 'send_message', return_value=None), patch.object(telegram_api, 'send_audio_file_id', return_value=None):
            downloader.main()
        self.assertEqual(json.loads(Path('daily_log.json').read_text()), [])
        self.assertFalse(Path('data/artists.txt').exists())

    def test_large_document_is_not_resent_as_audio_by_id(self):
        update = self.audio_update()
        update['message']['document'] = update['message'].pop('audio')
        with patch.object(telegram_api, 'get_updates', return_value=[update]), patch.object(telegram_api, 'send_message', return_value={'result': {'message_id': 3}}), patch.object(telegram_api, 'edit_message_text') as status, patch.object(telegram_api, 'send_audio_file_id') as reuse, patch.object(downloader, 'download_telegram_file') as download:
            downloader.main()
        reuse.assert_not_called()
        download.assert_not_called()
        self.assertIn('over 20 MB', status.call_args.args[-1])
        self.assertEqual(json.loads(Path('daily_log.json').read_text()), [])

    def test_small_document_keeps_original_upload_path(self):
        update = self.audio_update(file_size=5_000_000)
        update['message']['document'] = update['message'].pop('audio')
        Path('test.mp3').write_bytes(b'audio')
        with patch.object(telegram_api, 'get_updates', return_value=[update]), patch.object(telegram_api, 'send_message', return_value=None), patch.object(telegram_api, 'send_audio_file_id') as reuse, patch.object(downloader, 'download_telegram_file', return_value='test.mp3') as download, patch.object(telegram_api, 'send_audio', return_value={'ok': True, 'result': {'message_id': 43}}) as upload:
            downloader.main()
        download.assert_called_once_with('telegram-audio', 'song.mp3')
        reuse.assert_not_called()
        self.assertEqual(upload.call_args.args[2], 'test.mp3')
        self.assertFalse(Path('test.mp3').exists())

    def test_unauthorized_sender_cannot_publish_audio(self):
        update = self.audio_update()
        update['message']['from']['id'] = 999
        with patch.object(telegram_api, 'get_updates', return_value=[update]), patch.object(telegram_api, 'send_audio_file_id') as reuse:
            downloader.main()
        reuse.assert_not_called()

    def test_http_error_reports_telegram_reason_without_token(self):
        error = HTTPError('https://example.invalid', 400, 'Bad Request', {},
                          io.BytesIO(b'{"description":"Bad Request: file is too big"}'))
        with patch.object(downloader.urllib.request, 'urlopen', side_effect=error), patch('builtins.print') as output:
            self.assertIsNone(downloader.download_telegram_file('file', 'song.mp3'))
        self.assertIn('file is too big', str(output.call_args))
        self.assertNotIn('test-token', str(output.call_args))


class TelegramAudioTests(unittest.TestCase):
    def test_audio_reuse_is_json_without_a_local_file_read(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true, "result": {"message_id": 42}}'
        with patch.object(telegram_api.urllib.request, 'urlopen', return_value=response) as urlopen, patch('builtins.open') as local_open:
            result = telegram_api.send_audio_file_id('token', 'channel', 'existing-audio', performer='Artist', title='Track')
        local_open.assert_not_called()
        request = urlopen.call_args.args[0]
        self.assertEqual(json.loads(request.data), dict(chat_id='channel', audio='existing-audio', caption='', performer='Artist', title='Track'))
        self.assertEqual(urlopen.call_args.kwargs['timeout'], 180)
        self.assertTrue(result['ok'])

    def test_existing_local_file_upload_still_uses_multipart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'song.mp3'
            path.write_bytes(b'original audio bytes')
            response = MagicMock()
            response.__enter__.return_value.read.return_value = b'{"ok": true}'
            with patch.object(telegram_api.urllib.request, 'urlopen', return_value=response) as urlopen:
                telegram_api.send_audio('token', 'channel', str(path), performer='Artist', title='Track')
        request = urlopen.call_args.args[0]
        self.assertIn(b'original audio bytes', request.data)
        self.assertIn('multipart/form-data', request.get_header('Content-type'))


if __name__ == '__main__':
    unittest.main()
