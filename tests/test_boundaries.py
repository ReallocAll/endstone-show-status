from __future__ import annotations

import base64
import os
import tempfile
import threading
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from endstone.event import EventPriority
from endstone_show_status.config import load_config
from endstone_show_status.show_status import ShowStatus
from endstone_show_status.web import StatusRequestHandler


class BoundaryTests(unittest.TestCase):
    def test_invalid_existing_config_blocks_all_activation_and_preserves_file(self):
        values = (b'[http', b'http = 2', b'[http]\nauth_password = false',
                  b'[status]\nexpose_chat = "false"', b'[http]\nrate_limit_per_second = nan', b'\xff')
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path = folder/'config.toml'
            for content in values:
                with self.subTest(content=content):
                    path.write_bytes(content)
                    config, _, error = load_config(folder)
                    self.assertIsNotNone(error)
                    self.assertEqual(path.read_bytes(), content)
                    # Missing all server/collector members deliberately proves
                    # on_enable returns before any listener or task is started.
                    plugin = SimpleNamespace(_config_error=error, is_running=False, log_error=lambda msg: None)
                    ShowStatus.on_enable(plugin)
                    self.assertFalse(plugin.is_running)

    def test_read_failure_and_invalid_environment_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            load_config(folder)
            with patch.object(Path, 'open', side_effect=PermissionError('denied')):
                self.assertIsNotNone(load_config(folder)[2])
            with patch.dict(os.environ, {'ENDSTONE_SHOW_STATUS_EXPOSE_CHAT': 'typo'}):
                self.assertIsNotNone(load_config(folder)[2])
            with patch.dict(os.environ, {'ENDSTONE_SHOW_STATUS_EXPOSE_CHAT': 'false'}):
                config, _, error = load_config(folder)
                self.assertIsNone(error)
                self.assertFalse(config.status.expose_chat)

    def test_final_chat_policy_rejects_cancelled_private_and_async_messages(self):
        alice = SimpleNamespace(unique_id='a', name='Alice')
        bob = SimpleNamespace(unique_id='b', name='Bob')
        plugin = SimpleNamespace(
            _plugin_config=SimpleNamespace(status=SimpleNamespace(expose_chat=True, chat_entries=100)),
            chat_log=deque(), chat_lock=threading.Lock(),
            server=SimpleNamespace(online_players=[alice, bob]), _sanitize_line=ShowStatus._sanitize_line)
        event = SimpleNamespace(player=alice, message='final redacted text', is_cancelled=False,
                                is_asynchronous=False, recipients=[alice,bob])
        for change in ({'is_cancelled':True}, {'recipients':[alice]}, {'is_asynchronous':True}):
            denied = SimpleNamespace(**(vars(event)|change))
            ShowStatus.on_player_chat(plugin, denied)
            self.assertFalse(plugin.chat_log)
        ShowStatus.on_player_chat(plugin, event)
        self.assertEqual(plugin.chat_log[0]['message'], 'final redacted text')
        metadata = ShowStatus.on_player_chat
        self.assertEqual(metadata._priority, EventPriority.MONITOR)
        self.assertTrue(metadata._ignore_cancelled)

    def test_basic_auth_handles_unicode_and_malformed_credentials(self):
        handler = SimpleNamespace(server=SimpleNamespace(auth_username='管理员', auth_password='密码'), headers={})
        for credentials, expected in [('管理员:密码', True), ('管理员:wrong', False), ('wrong:密码',False), ('用户:口令',False)]:
            handler.headers['Authorization'] = 'Basic ' + base64.b64encode(credentials.encode()).decode()
            self.assertEqual(StatusRequestHandler._is_authorized(handler), expected)
        for token in ('%%%', base64.b64encode(b'\xff').decode(), base64.b64encode(b'missing-colon').decode()):
            handler.headers['Authorization'] = 'Basic ' + token
            self.assertFalse(StatusRequestHandler._is_authorized(handler))
        handler.server.auth_username, handler.server.auth_password = 'status', 'secret'
        handler.headers['Authorization'] = 'Basic ' + base64.b64encode(b'status:secret').decode()
        self.assertTrue(StatusRequestHandler._is_authorized(handler))
