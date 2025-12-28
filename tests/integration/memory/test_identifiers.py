"""Tests for identity generation (user_id, thread_id)."""
import pytest

from src.memory.core.identifiers import (
    generate_user_id,
    generate_thread_id,
    validate_thread_id,
    validate_user_id,
)


class TestGenerateUserID:
    """Tests for generate_user_id()."""

    def test_generates_valid_sha256(self):
        """Should generate 64-character hex string (SHA-256)."""
        user_id = generate_user_id()
        assert isinstance(user_id, str)
        assert len(user_id) == 64
        # Verify it's valid hex
        int(user_id, 16)

    def test_stable_with_seed(self):
        """Should generate same ID with same seed."""
        seed = "test-seed-123"
        user_id1 = generate_user_id(stable_seed=seed)
        user_id2 = generate_user_id(stable_seed=seed)
        assert user_id1 == user_id2

    def test_different_without_seed(self):
        """Should generate different IDs without seed."""
        user_id1 = generate_user_id()
        user_id2 = generate_user_id()
        assert user_id1 != user_id2

    def test_deterministic_with_client_info(self):
        """Should be deterministic with same client info."""
        client_info = {"ip": "127.0.0.1", "ua": "Mozilla/5.0"}
        user_id1 = generate_user_id(client_info=client_info)
        user_id2 = generate_user_id(client_info=client_info)
        assert user_id1 == user_id2

    def test_different_with_different_client_info(self):
        """Should generate different IDs with different client info."""
        user_id1 = generate_user_id(client_info={"ip": "127.0.0.1"})
        user_id2 = generate_user_id(client_info={"ip": "192.168.1.1"})
        assert user_id1 != user_id2


class TestGenerateThreadID:
    """Tests for generate_thread_id()."""

    def test_generates_valid_hmac_sha256(self):
        """Should generate 64-character hex string (HMAC-SHA256)."""
        thread_id = generate_thread_id(
            user_id="abc123" + "0" * 58,
            server_secret="test-secret"
        )
        assert isinstance(thread_id, str)
        assert len(thread_id) == 64
        # Verify it's valid hex
        int(thread_id, 16)

    def test_different_for_same_user(self):
        """Should generate different thread IDs for same user."""
        user_id = "abc123" + "0" * 58
        secret = "test-secret"

        thread_id1 = generate_thread_id(user_id, secret)
        thread_id2 = generate_thread_id(user_id, secret)

        # Without seed, should be different (includes timestamp + random)
        assert thread_id1 != thread_id2

    def test_deterministic_with_seed(self):
        """Should be deterministic with same seed."""
        user_id = "abc123" + "0" * 58
        secret = "test-secret"
        seed = "fixed-seed-123"

        thread_id1 = generate_thread_id(user_id, secret, seed)
        thread_id2 = generate_thread_id(user_id, secret, seed)

        assert thread_id1 == thread_id2

    def test_different_with_different_users(self):
        """Should generate different thread IDs for different users."""
        secret = "test-secret"
        seed = "same-seed"

        thread_id1 = generate_thread_id("user1" + "0" * 58, secret, seed)
        thread_id2 = generate_thread_id("user2" + "0" * 58, secret, seed)

        assert thread_id1 != thread_id2

    def test_different_with_different_secrets(self):
        """Should generate different thread IDs with different secrets."""
        user_id = "abc123" + "0" * 58
        seed = "same-seed"

        thread_id1 = generate_thread_id(user_id, "secret1", seed)
        thread_id2 = generate_thread_id(user_id, "secret2", seed)

        assert thread_id1 != thread_id2


class TestValidateThreadID:
    """Tests for validate_thread_id()."""

    def test_valid_thread_id(self):
        """Should accept valid 64-char hex string."""
        valid_id = "abc123" + "0" * 58
        assert validate_thread_id(valid_id) is True

    def test_invalid_length(self):
        """Should reject IDs with wrong length."""
        assert validate_thread_id("abc123") is False
        assert validate_thread_id("a" * 128) is False

    def test_invalid_hex(self):
        """Should reject non-hex strings."""
        invalid_id = "g" * 64  # 'g' is not valid hex
        assert validate_thread_id(invalid_id) is False

    def test_invalid_type(self):
        """Should reject non-string types."""
        assert validate_thread_id(123) is False
        assert validate_thread_id(None) is False
        assert validate_thread_id([]) is False


class TestValidateUserID:
    """Tests for validate_user_id()."""

    def test_valid_user_id(self):
        """Should accept valid 64-char hex string."""
        valid_id = "def456" + "0" * 58
        assert validate_user_id(valid_id) is True

    def test_invalid_user_id(self):
        """Should reject invalid IDs."""
        assert validate_user_id("invalid") is False
        assert validate_user_id("a" * 128) is False


class TestIntegration:
    """Integration tests for identity system."""

    def test_full_flow(self):
        """Test complete flow: generate user_id -> generate thread_id -> validate."""
        # Generate user ID
        user_id = generate_user_id(stable_seed="test-user")
        assert validate_user_id(user_id)

        # Generate thread ID
        thread_id = generate_thread_id(
            user_id=user_id,
            server_secret="test-secret",
            conversation_seed="test-conversation"
        )
        assert validate_thread_id(thread_id)

        # Thread ID should be different from user ID
        assert thread_id != user_id

    def test_multiple_threads_per_user(self):
        """Should allow multiple threads for same user."""
        user_id = generate_user_id(stable_seed="test-user")

        # Generate multiple thread IDs
        thread_ids = [
            generate_thread_id(user_id, "secret", f"conv-{i}")
            for i in range(5)
        ]

        # All should be valid
        assert all(validate_thread_id(tid) for tid in thread_ids)

        # All should be unique
        assert len(set(thread_ids)) == 5
