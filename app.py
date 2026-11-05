import os
import re
import secrets
import uuid
from datetime import date
from functools import wraps
from io import BytesIO
from pathlib import Path

import click
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from flask import (
    Flask,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
    session,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.exceptions import BadRequest

load_dotenv()

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()

CATEGORIES = (
    "Wallets & bags",
    "Keys",
    "Electronics",
    "Documents & IDs",
    "Other",
)
REPORT_TYPES = ("Lost", "Found")
ITEM_STATUSES = ("Open", "Matched", "Returned")
CLAIM_STATUSES = ("Pending", "Approved", "Rejected", "Returned")
PRIVATE_UPLOAD_TYPES = {"pdf", "jpg", "jpeg", "png"}
PHOTO_TYPES = {"jpg", "jpeg", "png", "webp"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    contact_number = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    id_type = db.Column(db.String(50), nullable=False)
    id_number = db.Column(db.String(512), nullable=False)
    id_file_path = db.Column(db.String(255), nullable=False)
    id_file_type = db.Column(db.String(10), nullable=False, default="")
    is_verified = db.Column(db.Boolean, nullable=False, default=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

    items = db.relationship(
        "Item", back_populates="owner", cascade="all, delete-orphan"
    )
    claims = db.relationship(
        "Claim", back_populates="claimant", cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def public_data(self):
        return {
            "id": self.id,
            "full_name": self.full_name,
            "contact_number": self.contact_number,
            "email": self.email,
            "is_admin": self.is_admin,
            "is_verified": self.is_verified,
        }


class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    report_type = db.Column(db.String(10), nullable=False)
    description = db.Column(db.Text, nullable=False)
    identifying_details = db.Column(db.Text, nullable=False, default="")
    location = db.Column(db.String(200), nullable=False)
    event_date = db.Column(db.Date, nullable=False)
    photo_path = db.Column(db.String(255))
    status = db.Column(db.String(20), nullable=False, default="Open")
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    owner = db.relationship("User", back_populates="items")
    claims = db.relationship(
        "Claim", back_populates="item", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "report_type IN ('Lost', 'Found')", name="ck_item_report_type"
        ),
        CheckConstraint(
            "status IN ('Open', 'Matched', 'Returned')", name="ck_item_status"
        ),
    )

    def public_data(self):
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "report_type": self.report_type,
            "description": self.description,
            "location": self.location,
            "event_date": self.event_date.isoformat(),
            "status": self.status,
            "photo_url": f"/media/items/{self.id}" if self.photo_path else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def private_data(self):
        result = self.public_data()
        result["identifying_details"] = decrypt_private(
            self.identifying_details.encode("ascii")
        ).decode("utf-8")
        return result


class Claim(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evidence = db.Column(db.Text, nullable=False)
    evidence_file_path = db.Column(db.String(255))
    evidence_file_type = db.Column(db.String(10), nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="Pending")
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
    reviewed_at = db.Column(db.DateTime)
    item_id = db.Column(db.Integer, db.ForeignKey("item.id"), nullable=False, index=True)
    claimant_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False, index=True
    )

    item = db.relationship("Item", back_populates="claims")
    claimant = db.relationship("User", back_populates="claims")

    __table_args__ = (
        CheckConstraint(
            "status IN ('Pending', 'Approved', 'Rejected', 'Returned')",
            name="ck_claim_status",
        ),
        db.UniqueConstraint("item_id", "claimant_id", name="uq_claim_item_claimant"),
    )

    def public_data(self):
        return {
            "id": self.id,
            "item_id": self.item_id,
            "item_title": self.item.title,
            "item_location": self.item.location,
            "item_date": self.item.event_date.isoformat(),
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        ID_ENCRYPTION_KEY=os.environ.get("ID_ENCRYPTION_KEY"),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL", "sqlite:///hanapbalik.db"
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "").lower()
        in {"1", "true", "yes"},
        PRIVATE_UPLOAD_FOLDER=os.path.join(app.instance_path, "private"),
        ITEM_UPLOAD_FOLDER=os.path.join(app.instance_path, "item_photos"),
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"] or app.config["SECRET_KEY"] == (
        "replace-with-a-random-secret"
    ):
        raise RuntimeError("Set a unique SECRET_KEY before starting HanapBalik.")
    if not app.config["ID_ENCRYPTION_KEY"] or app.config["ID_ENCRYPTION_KEY"] == (
        "replace-with-a-generated-fernet-key"
    ):
        raise RuntimeError("Set a persistent ID_ENCRYPTION_KEY before starting HanapBalik.")
    try:
        app.extensions["private_data_cipher"] = Fernet(
            app.config["ID_ENCRYPTION_KEY"].encode("ascii")
        )
    except (ValueError, UnicodeEncodeError) as error:
        raise RuntimeError("ID_ENCRYPTION_KEY must be a valid Fernet key.") from error
    if app.config["SQLALCHEMY_DATABASE_URI"].startswith(("postgres://", "postgresql://")):
        app.config["SQLALCHEMY_DATABASE_URI"] = app.config[
            "SQLALCHEMY_DATABASE_URI"
        ].replace("postgres://", "postgresql+psycopg://", 1).replace(
            "postgresql://", "postgresql+psycopg://", 1
        )

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["PRIVATE_UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["ITEM_UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "index"

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        return jsonify(error="Please log in to continue."), 401

    @app.before_request
    def protect_api_mutations():
        if (
            request.path.startswith("/api/")
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        ):
            expected = session.get("csrf_token")
            supplied = request.headers.get("X-CSRF-Token")
            if not expected or not supplied or not secrets.compare_digest(
                expected, supplied
            ):
                return jsonify(error="Your session expired. Refresh and try again."), 400

    @app.context_processor
    def inject_csrf_token():
        token = session.setdefault("csrf_token", secrets.token_urlsafe(32))
        return {"csrf_token": token}

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' "
            "https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
        )
        return response

    @app.errorhandler(413)
    def upload_too_large(_error):
        return jsonify(error="Files must be 5 MB or smaller."), 413

    @app.errorhandler(BadRequest)
    def invalid_request(error):
        if request.path.startswith("/api/"):
            return jsonify(error="Send valid request data and try again."), 400
        return error

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        db.session.rollback()
        app.logger.exception("Database operation failed", exc_info=error)
        return jsonify(error="The database is temporarily unavailable."), 503

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/healthz")
    def health():
        try:
            db.session.execute(db.select(1))
        except SQLAlchemyError:
            db.session.rollback()
            return jsonify(status="unavailable"), 503
        return jsonify(status="ok")

    @app.get("/api/me")
    def me():
        token = session.setdefault("csrf_token", secrets.token_urlsafe(32))
        if not current_user.is_authenticated:
            return jsonify(user=None, csrf_token=token)
        return jsonify(user=current_user.public_data(), csrf_token=token)

    @app.post("/api/auth/signup")
    def signup():
        data = request.form
        full_name = data.get("full_name", "").strip()
        contact = data.get("contact_number", "").strip()
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")
        id_type = data.get("id_type", "").strip()
        id_number = data.get("id_number", "").strip()
        id_file = request.files.get("id_file")

        if len(full_name) < 2 or len(full_name) > 150:
            return jsonify(error="Enter a valid full name."), 400
        if len(re.sub(r"\D", "", contact)) < 10 or len(contact) > 30:
            return jsonify(error="Enter a valid contact number."), 400
        if not valid_email(email):
            return jsonify(error="Enter a valid email address."), 400
        if len(password) < 8 or len(password) > 128:
            return jsonify(error="Use a password between 8 and 128 characters."), 400
        if id_type not in {"Driver’s license", "National ID", "Passport", "School ID"}:
            return jsonify(error="Choose a valid ID type."), 400
        if not id_number or len(id_number) > 100:
            return jsonify(error="Enter a valid ID number."), 400
        if data.get("terms") != "true":
            return jsonify(error="Accept the Terms of Service and Privacy Policy."), 400
        if User.query.filter_by(email=email).first():
            return jsonify(error="An account with that email already exists."), 409
        if not id_file or not id_file.filename:
            return jsonify(error="Upload a valid ID image or PDF."), 400
        extension = valid_upload(id_file, PRIVATE_UPLOAD_TYPES)
        if not extension:
            return jsonify(error="ID files must be JPG, PNG, or PDF."), 400

        file_name = f"{uuid.uuid4().hex}.enc"
        encrypted_id = encrypt_private(id_file.read())
        (Path(app.config["PRIVATE_UPLOAD_FOLDER"]) / file_name).write_bytes(
            encrypted_id
        )
        user = User(
            full_name=full_name,
            contact_number=contact,
            email=email,
            id_type=id_type,
            id_number=encrypt_private(id_number.encode("utf-8")).decode("ascii"),
            id_file_path=file_name,
            id_file_type=extension,
        )
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            (Path(app.config["PRIVATE_UPLOAD_FOLDER"]) / file_name).unlink(
                missing_ok=True
            )
            return jsonify(error="An account with that email already exists."), 409
        except SQLAlchemyError:
            (Path(app.config["PRIVATE_UPLOAD_FOLDER"]) / file_name).unlink(
                missing_ok=True
            )
            raise
        login_user(user)
        token = rotate_csrf_token()
        return jsonify(user=user.public_data(), csrf_token=token), 201

    @app.post("/api/auth/login")
    def login():
        data = json_payload()
        email = text_value(data, "email").lower()
        password = data.get("password")
        if not isinstance(password, str):
            password = ""
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            return jsonify(error="Email or password is incorrect."), 401
        login_user(user, remember=data.get("remember") is True)
        return jsonify(user=user.public_data(), csrf_token=rotate_csrf_token())

    @app.post("/api/auth/logout")
    @login_required
    def logout():
        logout_user()
        return jsonify(ok=True, csrf_token=rotate_csrf_token())

    @app.put("/api/account")
    @login_required
    def update_account():
        data = json_payload()
        full_name = text_value(data, "full_name")
        contact = text_value(data, "contact_number")
        if len(full_name) < 2 or len(full_name) > 150:
            return jsonify(error="Enter a valid full name."), 400
        if len(re.sub(r"\D", "", contact)) < 10 or len(contact) > 30:
            return jsonify(error="Enter a valid contact number."), 400
        current_user.full_name = full_name
        current_user.contact_number = contact
        db.session.commit()
        return jsonify(user=current_user.public_data())

    @app.put("/api/account/password")
    @login_required
    def update_password():
        data = json_payload()
        current_password = data.get("current_password")
        new_password = data.get("new_password")
        if not isinstance(current_password, str):
            current_password = ""
        if not isinstance(new_password, str):
            new_password = ""
        if not current_user.check_password(current_password):
            return jsonify(error="Your current password is incorrect."), 400
        if len(new_password) < 8 or len(new_password) > 128:
            return jsonify(error="Use a password between 8 and 128 characters."), 400
        current_user.set_password(new_password)
        db.session.commit()
        return jsonify(ok=True)

    @app.get("/api/items")
    def list_items():
        query = Item.query
        mine = request.args.get("mine") == "1"
        if mine:
            if not current_user.is_authenticated:
                return jsonify(error="Please log in to view your reports."), 401
            query = query.filter_by(user_id=current_user.id)
        else:
            query = query.filter(Item.status != "Returned")
        if request.args.get("exclude_mine") == "1" and current_user.is_authenticated:
            query = query.filter(Item.user_id != current_user.id)
        keyword = request.args.get("q", "").strip()
        if len(keyword) > 120:
            return jsonify(error="Search terms must be 120 characters or fewer."), 400
        report_type = request.args.get("type", "").strip()
        category = request.args.get("category", "").strip()
        event_date = request.args.get("date", "").strip()
        if keyword:
            pattern = f"%{keyword}%"
            query = query.filter(
                or_(
                    Item.title.ilike(pattern),
                    Item.description.ilike(pattern),
                    Item.location.ilike(pattern),
                )
            )
        if report_type in REPORT_TYPES:
            query = query.filter_by(report_type=report_type)
        if category in CATEGORIES:
            query = query.filter_by(category=category)
        if event_date:
            try:
                query = query.filter_by(event_date=date.fromisoformat(event_date))
            except ValueError:
                return jsonify(error="Choose a valid date."), 400
        records = query.order_by(Item.created_at.desc(), Item.id.desc()).limit(100).all()
        return jsonify(items=[serialize_item(item) for item in records])

    @app.post("/api/items")
    @login_required
    def create_item():
        data = request.form
        values, error = validate_item(data)
        if error:
            return jsonify(error=error), 400
        values["identifying_details"] = encrypt_private(
            values["identifying_details"].encode("utf-8")
        ).decode("ascii")
        photo = request.files.get("photo")
        photo_name = None
        if photo and photo.filename:
            extension = valid_upload(photo, PHOTO_TYPES)
            if not extension:
                return jsonify(error="Item photos must be JPG, PNG, or WebP."), 400
            photo_name = f"{uuid.uuid4().hex}.{extension}"
            photo.save(Path(app.config["ITEM_UPLOAD_FOLDER"]) / photo_name)
        item = Item(**values, photo_path=photo_name, owner=current_user)
        db.session.add(item)
        try:
            db.session.commit()
        except SQLAlchemyError:
            if photo_name:
                (Path(app.config["ITEM_UPLOAD_FOLDER"]) / photo_name).unlink(
                    missing_ok=True
                )
            raise
        return jsonify(item=item.private_data()), 201

    @app.patch("/api/items/<int:item_id>")
    @login_required
    def edit_item(item_id):
        item = db.get_or_404(Item, item_id)
        if item.user_id != current_user.id and not current_user.is_admin:
            return jsonify(error="You cannot edit this report."), 403
        data = json_payload()
        if current_user.is_admin and "status" in data:
            if data["status"] not in ITEM_STATUSES:
                return jsonify(error="Choose a valid report status."), 400
            item.status = data["status"]
            if item.status == "Returned":
                for claim in item.claims:
                    if claim.status == "Approved":
                        claim.status = "Returned"
                        claim.reviewed_at = db.func.now()
            db.session.commit()
            return jsonify(item=item.private_data())
        values, error = validate_item(data, require_type=False)
        if error:
            return jsonify(error=error), 400
        if item.status != "Open":
            return jsonify(error="Only open reports can be edited."), 409
        for key, value in values.items():
            if key == "identifying_details":
                value = encrypt_private(value.encode("utf-8")).decode("ascii")
            setattr(item, key, value)
        db.session.commit()
        return jsonify(item=item.private_data())

    @app.delete("/api/items/<int:item_id>")
    @login_required
    def delete_item(item_id):
        item = db.get_or_404(Item, item_id)
        if item.user_id != current_user.id and not current_user.is_admin:
            return jsonify(error="You cannot delete this report."), 403
        if item.claims:
            return jsonify(error="Reports with claims cannot be deleted."), 409
        photo_path = item.photo_path
        db.session.delete(item)
        db.session.commit()
        if photo_path:
            (Path(app.config["ITEM_UPLOAD_FOLDER"]) / photo_path).unlink(
                missing_ok=True
            )
        return jsonify(ok=True)

    @app.get("/api/dashboard")
    @login_required
    def dashboard():
        reports = Item.query.filter_by(user_id=current_user.id)
        recent = reports.order_by(Item.created_at.desc()).limit(5).all()
        return jsonify(
            stats={
                "reports": reports.count(),
                "lost": reports.filter_by(report_type="Lost").count(),
                "found": reports.filter_by(report_type="Found").count(),
                "claims": Claim.query.filter_by(
                    claimant_id=current_user.id, status="Pending"
                ).count(),
                "matches": find_matches(current_user.id),
            },
            reports=[item.private_data() for item in recent],
        )

    @app.get("/api/matches")
    @login_required
    def matches():
        own_items = Item.query.filter_by(user_id=current_user.id, status="Open").all()
        results = []
        for own in own_items:
            opposite = "Found" if own.report_type == "Lost" else "Lost"
            candidates = Item.query.filter(
                Item.user_id != current_user.id,
                Item.status == "Open",
                Item.report_type == opposite,
                Item.category == own.category,
            ).order_by(Item.created_at.desc()).limit(100).all()
            words = set(re.findall(r"[a-z0-9]{3,}", own.title.lower()))
            for candidate in candidates:
                candidate_words = set(re.findall(r"[a-z0-9]{3,}", candidate.title.lower()))
                if words & candidate_words:
                    results.append(candidate.public_data())
        return jsonify(items=results[:50])

    @app.get("/api/claims")
    @login_required
    def list_claims():
        if current_user.is_admin and request.args.get("all") == "1":
            records = Claim.query.order_by(Claim.created_at.desc()).limit(200).all()
            return jsonify(claims=[admin_claim_data(claim) for claim in records])
        records = Claim.query.filter_by(claimant_id=current_user.id).order_by(
            Claim.created_at.desc()
        ).all()
        return jsonify(claims=[claim.public_data() for claim in records])

    @app.post("/api/claims")
    @login_required
    def create_claim():
        data = request.form
        item_id = data.get("item_id", type=int)
        evidence = data.get("evidence", "").strip()
        item = db.session.get(Item, item_id) if item_id else None
        if not item or item.report_type != "Found" or item.status != "Open":
            return jsonify(error="Choose an available found item."), 400
        if item.user_id == current_user.id:
            return jsonify(error="You cannot claim your own report."), 400
        if not evidence or len(evidence) > 3000:
            return jsonify(error="Provide ownership evidence (up to 3,000 characters)."), 400
        if Claim.query.filter_by(item_id=item.id, claimant_id=current_user.id).first():
            return jsonify(error="You have already submitted a claim for this item."), 409
        evidence_file = request.files.get("evidence_file")
        evidence_name = None
        if evidence_file and evidence_file.filename:
            extension = valid_upload(evidence_file, PRIVATE_UPLOAD_TYPES)
            if not extension:
                return jsonify(error="Evidence files must be JPG, PNG, or PDF."), 400
            evidence_name = f"{uuid.uuid4().hex}.enc"
            encrypted_evidence = encrypt_private(evidence_file.read())
            (Path(app.config["PRIVATE_UPLOAD_FOLDER"]) / evidence_name).write_bytes(
                encrypted_evidence
            )
        claim = Claim(
            item=item,
            claimant=current_user,
            evidence=encrypt_private(evidence.encode("utf-8")).decode("ascii"),
            evidence_file_path=evidence_name,
            evidence_file_type=extension if evidence_name else "",
        )
        db.session.add(claim)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            if evidence_name:
                (Path(app.config["PRIVATE_UPLOAD_FOLDER"]) / evidence_name).unlink(
                    missing_ok=True
                )
            return jsonify(error="You have already submitted a claim for this item."), 409
        except SQLAlchemyError:
            if evidence_name:
                (Path(app.config["PRIVATE_UPLOAD_FOLDER"]) / evidence_name).unlink(
                    missing_ok=True
                )
            raise
        return jsonify(claim=claim.public_data()), 201

    @app.get("/api/admin/summary")
    @login_required
    @admin_required
    def admin_summary():
        return jsonify(
            stats={
                "items": Item.query.count(),
                "users": User.query.count(),
                "claims": Claim.query.filter_by(status="Pending").count(),
                "matched": Item.query.filter_by(status="Matched").count(),
                "returned": Item.query.filter_by(status="Returned").count(),
            }
        )

    @app.get("/api/admin/items")
    @login_required
    @admin_required
    def admin_items():
        records = Item.query.order_by(Item.created_at.desc()).limit(200).all()
        return jsonify(
            items=[
                {
                    "id": item.id,
                    "title": item.title,
                    "report_type": item.report_type,
                    "status": item.status,
                    "reporter": item.owner.full_name,
                }
                for item in records
            ]
        )

    @app.get("/api/admin/users")
    @login_required
    @admin_required
    def admin_users():
        users = User.query.order_by(User.created_at.desc()).limit(200).all()
        return jsonify(
            users=[
                {
                    "id": user.id,
                    "full_name": user.full_name,
                    "email": user.email,
                    "is_verified": user.is_verified,
                    "is_admin": user.is_admin,
                    "has_id_document": bool(user.id_file_path),
                }
                for user in users
            ]
        )

    @app.patch("/api/admin/users/<int:user_id>")
    @login_required
    @admin_required
    def update_user_verification(user_id):
        user = db.get_or_404(User, user_id)
        data = json_payload()
        if not isinstance(data.get("is_verified"), bool):
            return jsonify(error="Choose a valid verification status."), 400
        user.is_verified = data["is_verified"]
        db.session.commit()
        return jsonify(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            is_verified=user.is_verified,
        )

    @app.patch("/api/admin/claims/<int:claim_id>")
    @login_required
    @admin_required
    def review_claim(claim_id):
        claim = db.get_or_404(Claim, claim_id)
        data = json_payload()
        status = data.get("status")
        if status not in {"Approved", "Rejected", "Returned"}:
            return jsonify(error="Choose a valid claim action."), 400
        if status == "Returned":
            if claim.status != "Approved":
                return jsonify(error="Only approved claims can be marked returned."), 409
            claim.item.status = "Returned"
        elif claim.status != "Pending":
            return jsonify(error="Only pending claims can be reviewed."), 409
        elif status == "Approved":
            if claim.item.status != "Open":
                return jsonify(error="This item is no longer available."), 409
            claim.item.status = "Matched"
        claim.status = status
        claim.reviewed_at = db.func.now()
        db.session.commit()
        return jsonify(claim=admin_claim_data(claim))

    @app.get("/api/admin/identity/<int:user_id>")
    @login_required
    @admin_required
    def view_identity(user_id):
        user = db.get_or_404(User, user_id)
        return jsonify(
            full_name=user.full_name,
            contact_number=user.contact_number,
            id_type=user.id_type,
            id_number=decrypt_private(user.id_number.encode("ascii")).decode("utf-8"),
            id_file_url=(
                f"/api/admin/identity/{user.id}/file" if user.id_file_path else None
            ),
        )

    @app.get("/api/admin/identity/<int:user_id>/file")
    @login_required
    @admin_required
    def identity_file(user_id):
        user = db.get_or_404(User, user_id)
        if not user.id_file_path:
            return jsonify(error="This account has no ID document."), 404
        document = decrypt_private(
            (Path(app.config["PRIVATE_UPLOAD_FOLDER"]) / user.id_file_path).read_bytes()
        )
        return send_file(
            BytesIO(document),
            as_attachment=True,
            download_name=f"identity-{user.id}.{user.id_file_type}",
            mimetype=upload_mimetype(user.id_file_type),
        )

    @app.get("/api/admin/claims/<int:claim_id>/evidence")
    @login_required
    @admin_required
    def claim_evidence(claim_id):
        claim = db.get_or_404(Claim, claim_id)
        if not claim.evidence_file_path:
            return jsonify(error="This claim has no attached evidence file."), 404
        return send_file(
            BytesIO(
                decrypt_private(
                    (
                        Path(app.config["PRIVATE_UPLOAD_FOLDER"])
                        / claim.evidence_file_path
                    ).read_bytes()
                )
            ),
            as_attachment=True,
            download_name=f"claim-evidence-{claim.id}.{claim.evidence_file_type}",
            mimetype=upload_mimetype(claim.evidence_file_type),
        )

    @app.get("/media/items/<int:item_id>")
    def item_photo(item_id):
        item = db.get_or_404(Item, item_id)
        if not item.photo_path or item.status == "Returned":
            return jsonify(error="Photo not found."), 404
        return send_file(
            Path(app.config["ITEM_UPLOAD_FOLDER"]) / item.photo_path,
            conditional=True,
        )

    @app.cli.command("create-admin")
    @click.argument("email")
    def create_admin_command(email):
        """Create an admin account without exposing credentials in source."""
        email = email.strip().lower()
        if not valid_email(email):
            raise click.ClickException("Enter a valid email address.")
        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
        if len(password) < 12:
            raise click.ClickException("Admin passwords must be at least 12 characters.")
        user = User.query.filter_by(email=email).first()
        if user is None:
            name = click.prompt("Administrator name")
            user = User(
                full_name=name.strip(),
                contact_number="0000000000",
                email=email,
                id_type="School ID",
                id_number=encrypt_private(b"Admin account").decode("ascii"),
                id_file_path="",
                id_file_type="",
                is_verified=True,
            )
            user.set_password(password)
            db.session.add(user)
        else:
            user.set_password(password)
        user.is_admin = True
        db.session.commit()
        click.echo(f"Administrator access enabled for {email}.")

    return app


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            return jsonify(error="Administrator access is required."), 403
        return view(*args, **kwargs)

    return wrapped


def valid_email(value):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value)) and len(value) <= 254


def valid_upload(upload, allowed_extensions):
    extension = Path(upload.filename or "").suffix.lower().lstrip(".")
    if extension not in allowed_extensions:
        return None
    header = upload.stream.read(12)
    upload.stream.seek(0)
    valid_signatures = {
        "jpg": header.startswith(b"\xff\xd8\xff"),
        "jpeg": header.startswith(b"\xff\xd8\xff"),
        "png": header.startswith(b"\x89PNG\r\n\x1a\n"),
        "webp": header.startswith(b"RIFF") and header[8:12] == b"WEBP",
        "pdf": header.startswith(b"%PDF-"),
    }
    return extension if valid_signatures.get(extension, False) else None


def validate_item(data, require_type=True):
    title = text_value(data, "title")
    description = text_value(data, "description")
    category = text_value(data, "category")
    location = text_value(data, "location")
    report_type = text_value(data, "report_type")
    identifying = text_value(data, "identifying_details")
    event_date_value = text_value(data, "event_date")
    if not title or len(title) > 150:
        return None, "Enter an item name (up to 150 characters)."
    if not description or len(description) > 5000:
        return None, "Enter a description (up to 5,000 characters)."
    if category not in CATEGORIES:
        return None, "Choose a valid category."
    if not location or len(location) > 200:
        return None, "Enter a location (up to 200 characters)."
    if require_type and report_type not in REPORT_TYPES:
        return None, "Choose Lost or Found."
    try:
        event_date = date.fromisoformat(event_date_value)
    except ValueError:
        return None, "Choose a valid lost or found date."
    values = {
        "title": title,
        "category": category,
        "description": description,
        "identifying_details": identifying[:3000],
        "location": location,
        "event_date": event_date,
    }
    if require_type:
        values["report_type"] = report_type
    return values, None


def serialize_item(item):
    if request.args.get("mine") == "1" and current_user.is_authenticated and (
        item.user_id == current_user.id or current_user.is_admin
    ):
        return item.private_data()
    return item.public_data()


def json_payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequest("Expected a JSON object.")
    return data


def text_value(data, key):
    value = data.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def find_matches(user_id):
    own_items = Item.query.filter_by(user_id=user_id, status="Open").all()
    count = 0
    for own in own_items:
        opposite = "Found" if own.report_type == "Lost" else "Lost"
        title_words = set(re.findall(r"[a-z0-9]{3,}", own.title.lower()))
        candidates = Item.query.filter(
            Item.user_id != user_id,
            Item.status == "Open",
            Item.report_type == opposite,
            Item.category == own.category,
        ).all()
        count += sum(
            bool(title_words & set(re.findall(r"[a-z0-9]{3,}", item.title.lower())))
            for item in candidates
        )
    return count


def admin_claim_data(claim):
    return {
        **claim.public_data(),
        "claimant_name": claim.claimant.full_name,
        "claimant_email": claim.claimant.email,
        "evidence": decrypt_private(claim.evidence.encode("ascii")).decode("utf-8"),
        "evidence_file_url": (
            f"/api/admin/claims/{claim.id}/evidence"
            if claim.evidence_file_path
            else None
        ),
    }


def encrypt_private(value):
    return current_app.extensions["private_data_cipher"].encrypt(value)


def decrypt_private(value):
    return current_app.extensions["private_data_cipher"].decrypt(value)


def upload_mimetype(extension):
    return {
        "pdf": "application/pdf",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
    }.get(extension, "application/octet-stream")


def rotate_csrf_token():
    token = secrets.token_urlsafe(32)
    session["csrf_token"] = token
    return token
