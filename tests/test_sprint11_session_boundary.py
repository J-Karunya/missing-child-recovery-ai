import tempfile
import unittest
from pathlib import Path

from services.review_store import AuthorizationError, ReviewStore
from services.session_service import SessionService


class Sprint11SessionBoundaryTests(unittest.TestCase):
    def test_revoked_server_token_cannot_reauthenticate(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReviewStore(Path(directory) / "session.db")
            store.initialize()
            store.create_user("admin", "ADMIN", "HQ", "correct-horse-battery-staple", "admin@example.test")
            sessions = SessionService(store)
            token = sessions.create(store.get_user("admin")["id"])
            self.assertEqual(sessions.validate(token)["username"], "admin")
            sessions.revoke(token)
            with self.assertRaises(AuthorizationError):
                sessions.validate(token)
