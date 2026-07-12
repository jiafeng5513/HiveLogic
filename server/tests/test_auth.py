# -*- coding: utf-8 -*-
"""
Auth 模块单元测试

测试场景:
1. 密码哈希: PBKDF2-SHA256 设置/验证/修改
2. Session: 创建/验证/过期
3. 登录限流: IP 失败计数/窗口过期/成功清除
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def isolated_auth_env(tmp_path, monkeypatch):
    """每个测试使用独立的数据目录和 .env，避免污染全局状态。"""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("ADMIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("ENV_FILE", str(tmp_path / ".env"))
    (tmp_path / ".env").write_text("ADMIN_AUTH_ENABLED=true\n")

    import importlib
    import src.auth as auth_module
    auth_module._auth_enabled = None
    auth_module._session_secret = None
    auth_module._password_hash_salt = None
    auth_module._password_hash_stored = None
    auth_module._rate_limit = {}
    importlib.reload(auth_module)
    yield auth_module
    auth_module._auth_enabled = None
    auth_module._session_secret = None
    auth_module._password_hash_salt = None
    auth_module._password_hash_stored = None


class TestPasswordHashing:
    """密码哈希设置/验证/修改"""

    def test_set_and_verify_password(self, isolated_auth_env):
        auth = isolated_auth_env
        err = auth.set_initial_password("test123456")
        assert err is None
        assert auth.verify_password("test123456") is True
        assert auth.verify_password("wrong") is False

    def test_password_too_short(self, isolated_auth_env):
        auth = isolated_auth_env
        err = auth.set_initial_password("123")
        assert err is not None
        assert "至少" in err

    def test_password_empty(self, isolated_auth_env):
        auth = isolated_auth_env
        err = auth.set_initial_password("")
        assert err is not None

    def test_change_password(self, isolated_auth_env):
        auth = isolated_auth_env
        auth.set_initial_password("old_pass_123")
        err = auth.change_password("old_pass_123", "new_pass_456")
        assert err is None
        assert auth.verify_password("new_pass_456") is True
        assert auth.verify_password("old_pass_123") is False

    def test_change_password_wrong_current(self, isolated_auth_env):
        auth = isolated_auth_env
        auth.set_initial_password("original_123")
        err = auth.change_password("wrong_current", "new_pass_456")
        assert err is not None
        assert auth.verify_password("original_123") is True

    def test_hash_format_stored_on_disk(self, isolated_auth_env):
        auth = isolated_auth_env
        auth.set_initial_password("diskcheck_123")
        cred_path = auth._get_credential_path()
        assert cred_path.exists()
        raw = cred_path.read_text()
        assert ":" in raw
        parts = raw.split(":")
        assert len(parts) == 2
        import base64
        assert len(base64.standard_b64decode(parts[0])) == 32  # salt
        assert len(base64.standard_b64decode(parts[1])) == 32  # hash


class TestSession:
    """Session 创建/验证/过期"""

    def test_create_and_verify_session(self, isolated_auth_env):
        auth = isolated_auth_env
        auth.set_initial_password("session_123")
        token = auth.create_session()
        assert token
        assert auth.verify_session(token) is True

    def test_verify_invalid_session(self, isolated_auth_env):
        auth = isolated_auth_env
        auth.set_initial_password("session_123")
        assert auth.verify_session("invalid.token.here") is False
        assert auth.verify_session("") is False

    def test_session_expiry(self, isolated_auth_env, monkeypatch):
        auth = isolated_auth_env
        auth.set_initial_password("session_123")
        token = auth.create_session()
        assert auth.verify_session(token) is True

        # 模拟时间过期：monkeypatch time.time 返回未来时间
        future_time = time.time() + 25 * 3600
        with patch("src.auth.time.time", return_value=future_time):
            assert auth.verify_session(token) is False

    def test_rotate_session_secret_invalidates_old(self, isolated_auth_env):
        auth = isolated_auth_env
        auth.set_initial_password("session_123")
        token = auth.create_session()
        assert auth.verify_session(token) is True

        auth.rotate_session_secret()
        assert auth.verify_session(token) is False

        new_token = auth.create_session()
        assert auth.verify_session(new_token) is True


class TestLoginRateLimit:
    """登录失败限流"""

    def test_under_limit_allows(self, isolated_auth_env):
        auth = isolated_auth_env
        ip = "192.168.1.100"
        for _ in range(auth.RATE_LIMIT_MAX_FAILURES - 1):
            auth.record_login_failure(ip)
        assert auth.check_rate_limit(ip) is True

    def test_at_limit_blocks(self, isolated_auth_env):
        auth = isolated_auth_env
        ip = "192.168.1.101"
        for _ in range(auth.RATE_LIMIT_MAX_FAILURES):
            auth.record_login_failure(ip)
        assert auth.check_rate_limit(ip) is False

    def test_clear_after_success(self, isolated_auth_env):
        auth = isolated_auth_env
        ip = "192.168.1.102"
        for _ in range(auth.RATE_LIMIT_MAX_FAILURES):
            auth.record_login_failure(ip)
        assert auth.check_rate_limit(ip) is False
        auth.clear_rate_limit(ip)
        assert auth.check_rate_limit(ip) is True

    def test_different_ips_independent(self, isolated_auth_env):
        auth = isolated_auth_env
        ip1 = "192.168.1.110"
        ip2 = "192.168.1.111"
        for _ in range(auth.RATE_LIMIT_MAX_FAILURES):
            auth.record_login_failure(ip1)
        assert auth.check_rate_limit(ip1) is False
        assert auth.check_rate_limit(ip2) is True

    def test_window_expiry(self, isolated_auth_env, monkeypatch):
        auth = isolated_auth_env
        ip = "192.168.1.120"
        for _ in range(auth.RATE_LIMIT_MAX_FAILURES):
            auth.record_login_failure(ip)
        assert auth.check_rate_limit(ip) is False

        # 模拟窗口过期
        future = time.time() + auth.RATE_LIMIT_WINDOW_SEC + 1
        with patch("src.auth.time.time", return_value=future):
            assert auth.check_rate_limit(ip) is True
