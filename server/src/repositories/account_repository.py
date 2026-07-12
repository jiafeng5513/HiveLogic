# -*- coding: utf-8 -*-
"""
Account Repository — accounts, subscriptions, API tokens, usage records 的 CRUD。

使用 SQLAlchemy ORM via DatabaseManager 单例。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from src.models.accounts import Account, Subscription, ApiToken, UsageRecord
from src.models.tiers import get_tier_config
from src.storage import DatabaseManager

logger = logging.getLogger(__name__)

PBKDF2_ITERATIONS = 100_000
TOKEN_BYTES = 32  # 生成 32 字节随机 token


def _hash_password(password: str) -> str:
    """PBKDF2-SHA256 哈希密码，返回 salt_b64:hash_b64。"""
    salt = secrets.token_bytes(32)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt=salt, iterations=PBKDF2_ITERATIONS)
    salt_b64 = base64.standard_b64encode(salt).decode("ascii")
    hash_b64 = base64.standard_b64encode(derived).decode("ascii")
    return f"{salt_b64}:{hash_b64}"


def _verify_password(password: str, stored: str) -> bool:
    """验证密码。stored 格式: salt_b64:hash_b64。"""
    if not stored or ":" not in stored:
        return False
    parts = stored.split(":", 1)
    if len(parts) != 2:
        return False
    try:
        salt = base64.standard_b64decode(parts[0].strip())
        expected = base64.standard_b64decode(parts[1].strip())
    except (ValueError, TypeError):
        return False
    computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt=salt, iterations=PBKDF2_ITERATIONS)
    return hmac.compare_digest(computed, expected)


def _hash_token(token: str) -> str:
    """SHA256 哈希 token（用于 DB 存储 + 查找）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AccountRepository:
    """账号 / 订阅 / 令牌 / 用量的数据访问层。"""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self._db = db_manager or DatabaseManager.get_instance()

    def _session(self) -> Session:
        return self._db._SessionLocal()

    # ==================== 账号 ====================

    def create_account(self, email: str, password: str, role: str = "user", display_name: Optional[str] = None) -> Account:
        """创建账号。email 唯一，重复抛 ValueError。"""
        with self._session() as session:
            existing = session.query(Account).filter(Account.email == email).first()
            if existing:
                raise ValueError(f"Email '{email}' already exists")
            account = Account(
                email=email,
                password_hash=_hash_password(password),
                role=role,
                display_name=display_name,
            )
            session.add(account)
            session.commit()
            session.refresh(account)
            return account

    def get_account_by_id(self, account_id: int) -> Optional[Account]:
        with self._session() as session:
            return session.query(Account).filter(Account.id == account_id).first()

    def get_account_by_email(self, email: str) -> Optional[Account]:
        with self._session() as session:
            return session.query(Account).filter(Account.email == email).first()

    def verify_credentials(self, email: str, password: str) -> Optional[Account]:
        """验证邮箱+密码，返回 Account 或 None。"""
        account = self.get_account_by_email(email)
        if not account:
            return None
        if account.status != "active":
            return None
        if not _verify_password(password, account.password_hash):
            return None
        return account

    def list_accounts(self, offset: int = 0, limit: int = 100) -> list[Account]:
        with self._session() as session:
            return (
                session.query(Account)
                .order_by(Account.id)
                .offset(offset)
                .limit(limit)
                .all()
            )

    def update_account(self, account_id: int, **kwargs) -> Optional[Account]:
        """更新账号字段（password_hash, role, status, display_name）。"""
        with self._session() as session:
            account = session.query(Account).filter(Account.id == account_id).first()
            if not account:
                return None
            if "password" in kwargs:
                account.password_hash = _hash_password(kwargs.pop("password"))
            for k, v in kwargs.items():
                if hasattr(account, k):
                    setattr(account, k, v)
            account.updated_at = datetime.now()
            session.commit()
            session.refresh(account)
            return account

    def delete_account(self, account_id: int) -> bool:
        with self._session() as session:
            account = session.query(Account).filter(Account.id == account_id).first()
            if not account:
                return False
            session.delete(account)
            session.commit()
            return True

    # ==================== 订阅 ====================

    def get_active_subscription(self, account_id: int) -> Optional[Subscription]:
        """获取账号当前有效的订阅。"""
        with self._session() as session:
            sub = (
                session.query(Subscription)
                .filter(
                    Subscription.account_id == account_id,
                    Subscription.status == "active",
                )
                .order_by(Subscription.created_at.desc())
                .first()
            )
            if not sub:
                return None
            # 检查是否过期
            if sub.expires_at and sub.expires_at < datetime.now():
                sub.status = "expired"
                session.commit()
                session.refresh(sub)
                return None
            return sub

    def get_account_tier(self, account_id: int) -> str:
        """获取账号当前等级（无订阅返回 free）。"""
        sub = self.get_active_subscription(account_id)
        if not sub:
            return "free"
        return sub.tier

    def grant_subscription(
        self,
        account_id: int,
        tier: str,
        duration_days: Optional[int] = None,
    ) -> Subscription:
        """
        授予订阅。自动将旧 active 订阅标记为 cancelled。

        Args:
            tier: free / pro / enterprise
            duration_days: 有效期天数，None = 永不过期
        """
        if not get_tier_config(tier):
            raise ValueError(f"Unknown tier: {tier}")
        with self._session() as session:
            # 取消旧订阅
            old_subs = (
                session.query(Subscription)
                .filter(
                    Subscription.account_id == account_id,
                    Subscription.status == "active",
                )
                .all()
            )
            for old in old_subs:
                old.status = "cancelled"

            starts_at = datetime.now()
            expires_at = starts_at + timedelta(days=duration_days) if duration_days else None
            sub = Subscription(
                account_id=account_id,
                tier=tier,
                starts_at=starts_at,
                expires_at=expires_at,
                status="active",
            )
            session.add(sub)
            session.commit()
            session.refresh(sub)
            return sub

    def list_subscriptions(self, account_id: int) -> list[Subscription]:
        with self._session() as session:
            return (
                session.query(Subscription)
                .filter(Subscription.account_id == account_id)
                .order_by(Subscription.created_at.desc())
                .all()
            )

    # ==================== API Token ====================

    def create_token(
        self,
        account_id: int,
        device_info: Optional[str] = None,
        expires_days: Optional[int] = None,
    ) -> tuple[ApiToken, str]:
        """
        创建 API token。

        Returns:
            (ApiToken 记录, 原始 token 字符串) — 原始 token 只返回一次。
        """
        raw_token = secrets.token_urlsafe(TOKEN_BYTES)
        token_hash = _hash_token(raw_token)
        token_prefix = raw_token[:8]
        expires_at = datetime.now() + timedelta(days=expires_days) if expires_days else None

        with self._session() as session:
            token = ApiToken(
                account_id=account_id,
                token_hash=token_hash,
                token_prefix=token_prefix,
                device_info=device_info,
                expires_at=expires_at,
            )
            session.add(token)
            session.commit()
            session.refresh(token)
            return token, raw_token

    def validate_token(self, raw_token: str) -> Optional[tuple[ApiToken, Account]]:
        """
        验证 token，返回 (ApiToken, Account) 或 None。
        自动更新 last_used_at。
        """
        if not raw_token:
            return None
        token_hash = _hash_token(raw_token)
        with self._session() as session:
            token = session.query(ApiToken).filter(ApiToken.token_hash == token_hash).first()
            if not token:
                return None
            if token.revoked_at is not None:
                return None
            if token.expires_at and token.expires_at < datetime.now():
                return None
            account = session.query(Account).filter(Account.id == token.account_id).first()
            if not account or account.status != "active":
                return None
            # 更新 last_used_at
            token.last_used_at = datetime.now()
            session.commit()
            return token, account

    def revoke_token(self, token_id: int) -> bool:
        with self._session() as session:
            token = session.query(ApiToken).filter(ApiToken.id == token_id).first()
            if not token:
                return False
            token.revoked_at = datetime.now()
            session.commit()
            return True

    def revoke_all_tokens(self, account_id: int) -> int:
        """吊销账号的所有 token，返回吊销数量。"""
        with self._session() as session:
            tokens = session.query(ApiToken).filter(
                ApiToken.account_id == account_id,
                ApiToken.revoked_at.is_(None),
            ).all()
            count = 0
            for t in tokens:
                t.revoked_at = datetime.now()
                count += 1
            session.commit()
            return count

    def list_tokens(self, account_id: int, include_revoked: bool = False) -> list[ApiToken]:
        with self._session() as session:
            q = session.query(ApiToken).filter(ApiToken.account_id == account_id)
            if not include_revoked:
                q = q.filter(ApiToken.revoked_at.is_(None))
            return q.order_by(ApiToken.created_at.desc()).all()

    # ==================== 用量 ====================

    def record_usage(
        self,
        account_id: int,
        endpoint: str,
        method: str,
        market: Optional[str] = None,
        model_used: Optional[str] = None,
        tokens_consumed: int = 0,
    ) -> None:
        """记录一次 API 调用用量。Fire-and-forget，不抛异常。"""
        try:
            with self._session() as session:
                record = UsageRecord(
                    account_id=account_id,
                    endpoint=endpoint,
                    method=method,
                    market=market,
                    model_used=model_used,
                    tokens_consumed=tokens_consumed,
                )
                session.add(record)
                session.commit()
        except Exception as e:
            logger.warning("[UsageRecord] Failed to record usage: %s", e)

    def get_usage_summary(self, account_id: int, days: int = 30) -> dict:
        """获取账号最近 N 天的用量汇总。"""
        since = datetime.now() - timedelta(days=days)
        with self._session() as session:
            records = (
                session.query(UsageRecord)
                .filter(
                    UsageRecord.account_id == account_id,
                    UsageRecord.created_at >= since,
                )
                .all()
            )
            total_requests = len(records)
            total_tokens = sum(r.tokens_consumed or 0 for r in records)
            by_market: dict[str, int] = {}
            for r in records:
                m = r.market or "unknown"
                by_market[m] = by_market.get(m, 0) + 1
            today = datetime.now().date()
            today_requests = sum(1 for r in records if r.created_at and r.created_at.date() == today)
            return {
                "days": days,
                "total_requests": total_requests,
                "total_tokens": total_tokens,
                "today_requests": today_requests,
                "by_market": by_market,
            }


# ==================== 单例 ====================

_repo_instance: Optional[AccountRepository] = None


def get_account_repository() -> AccountRepository:
    """获取 AccountRepository 单例。"""
    global _repo_instance
    if _repo_instance is None:
        _repo_instance = AccountRepository()
    return _repo_instance
