import io
import os
import tempfile
import unittest

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key")
os.environ.setdefault(
    "ID_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)

from app import Claim, Item, User, create_app, db


class HanapBalikTests(unittest.TestCase):
    def setUp(self):
        self.uploads = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "unit-test-secret-key",
                "ID_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "PRIVATE_UPLOAD_FOLDER": os.path.join(
                    self.uploads.name, "private"
                ),
                "ITEM_UPLOAD_FOLDER": os.path.join(self.uploads.name, "photos"),
            }
        )
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.client = self.app.test_client()
        self.token(self.client)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()
        self.uploads.cleanup()

    @staticmethod
    def token(client):
        with client.session_transaction() as session:
            return session.get("csrf_token")

    def csrf(self, client):
        token = self.token(client)
        if token is None:
            client.get("/")
            token = self.token(client)
        return {"X-CSRF-Token": token}

    def signup(self, client, name, email):
        response = client.post(
            "/api/auth/signup",
            data={
                "full_name": name,
                "contact_number": "09171234567",
                "email": email,
                "password": "secure-password-123",
                "id_type": "School ID",
                "id_number": "TEST-123",
                "terms": "true",
                "id_file": (io.BytesIO(b"\x89PNG\r\n\x1a\nvalid-test-image"), "id.png"),
            },
            headers=self.csrf(client),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["user"]

    def login_admin(self):
        admin = User(
            full_name="Test Admin",
            contact_number="09171234567",
            email="admin@example.com",
            id_type="School ID",
            id_number="ADMIN",
            id_file_path="",
            is_admin=True,
            is_verified=True,
        )
        admin.set_password("admin-password-123")
        db.session.add(admin)
        db.session.commit()
        client = self.app.test_client()
        client.get("/")
        response = client.post(
            "/api/auth/login",
            json={"email": admin.email, "password": "admin-password-123"},
            headers=self.csrf(client),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return client

    def create_item(self, client, report_type="Lost", title="Black wallet"):
        return client.post(
            "/api/items",
            data={
                "report_type": report_type,
                "category": "Wallets & bags",
                "title": title,
                "description": "Small black leather wallet.",
                "event_date": "2026-10-25",
                "location": "Main library",
                "identifying_details": "Private blue stitching",
            },
            headers=self.csrf(client),
        )

    def test_registration_login_and_item_crud(self):
        user = self.signup(self.client, "Test Owner", "owner@example.com")
        account = db.session.get(User, user["id"])
        self.assertNotEqual(account.id_number, "TEST-123")
        with open(
            os.path.join(
                self.app.config["PRIVATE_UPLOAD_FOLDER"], account.id_file_path
            ),
            "rb",
        ) as stored_file:
            encrypted_id = stored_file.read()
        self.assertNotIn(b"valid-test-image", encrypted_id)
        admin = self.login_admin()
        identity = admin.get(f"/api/admin/identity/{account.id}").get_json()
        self.assertEqual(identity["id_number"], "TEST-123")
        identity_file = admin.get(identity["id_file_url"])
        self.assertEqual(identity_file.data, b"\x89PNG\r\n\x1a\nvalid-test-image")

        created = self.create_item(self.client)
        self.assertEqual(created.status_code, 201, created.get_json())
        item = created.get_json()["item"]
        self.assertEqual(item["identifying_details"], "Private blue stitching")
        stored_item = db.session.get(Item, item["id"])
        self.assertNotIn("Private blue stitching", stored_item.identifying_details)

        public = self.app.test_client().get("/api/items").get_json()["items"]
        self.assertEqual(public[0]["title"], "Black wallet")
        self.assertNotIn("identifying_details", public[0])
        self.assertNotIn("owner_id", public[0])

        changed = self.client.patch(
            f"/api/items/{item['id']}",
            json={
                "report_type": "Lost",
                "category": "Electronics",
                "title": "Updated wallet",
                "description": "Updated item description",
                "event_date": "2026-10-26",
                "location": "Cafeteria",
                "identifying_details": "Private detail",
            },
            headers=self.csrf(self.client),
        )
        self.assertEqual(changed.status_code, 200, changed.get_json())
        self.assertEqual(changed.get_json()["item"]["title"], "Updated wallet")

        deleted = self.client.delete(
            f"/api/items/{item['id']}", headers=self.csrf(self.client)
        )
        self.assertEqual(deleted.status_code, 200, deleted.get_json())
        self.assertIsNone(db.session.get(Item, item["id"]))
        self.assertEqual(user["email"], "owner@example.com")

    def test_claim_review_and_item_return(self):
        self.signup(self.client, "Finder", "finder@example.com")
        found = self.create_item(self.client, "Found", "Black wallet")
        self.assertEqual(found.status_code, 201, found.get_json())
        item_id = found.get_json()["item"]["id"]

        claimant = self.app.test_client()
        self.signup(claimant, "Owner", "claimant@example.com")
        claim = claimant.post(
            "/api/claims",
            data={
                "item_id": str(item_id),
                "evidence": "I can describe the wallet contents and a distinctive mark.",
                "evidence_file": (
                    io.BytesIO(b"\x89PNG\r\n\x1a\nclaim-test-image"),
                    "receipt.png",
                ),
            },
            headers=self.csrf(claimant),
        )
        self.assertEqual(claim.status_code, 201, claim.get_json())
        claim_id = claim.get_json()["claim"]["id"]
        stored_claim = db.session.get(Claim, claim_id)
        self.assertNotIn("distinctive mark", stored_claim.evidence)

        duplicate = claimant.post(
            "/api/claims",
            data={
                "item_id": str(item_id),
                "evidence": "A second claim for the same item.",
            },
            headers=self.csrf(claimant),
        )
        self.assertEqual(duplicate.status_code, 409)

        admin = self.login_admin()
        admin_claim = admin.get("/api/claims?all=1").get_json()["claims"][0]
        self.assertIn("distinctive mark", admin_claim["evidence"])
        evidence_file = admin.get(admin_claim["evidence_file_url"])
        self.assertEqual(evidence_file.data, b"\x89PNG\r\n\x1a\nclaim-test-image")
        approved = admin.patch(
            f"/api/admin/claims/{claim_id}",
            json={"status": "Approved"},
            headers=self.csrf(admin),
        )
        self.assertEqual(approved.status_code, 200, approved.get_json())
        self.assertEqual(approved.get_json()["claim"]["status"], "Approved")
        self.assertEqual(db.session.get(Item, item_id).status, "Matched")

        returned = admin.patch(
            f"/api/admin/claims/{claim_id}",
            json={"status": "Returned"},
            headers=self.csrf(admin),
        )
        self.assertEqual(returned.status_code, 200, returned.get_json())
        self.assertEqual(db.session.get(Item, item_id).status, "Returned")

    def test_authorization_and_csrf(self):
        self.signup(self.client, "Owner", "owner@example.com")
        created = self.create_item(self.client)
        item_id = created.get_json()["item"]["id"]

        denied = self.app.test_client().delete(
            f"/api/items/{item_id}", headers={"X-CSRF-Token": "invalid"}
        )
        self.assertEqual(denied.status_code, 400)

        stranger = self.app.test_client()
        self.signup(stranger, "Stranger", "stranger@example.com")
        response = stranger.delete(
            f"/api/items/{item_id}", headers=self.csrf(stranger)
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
