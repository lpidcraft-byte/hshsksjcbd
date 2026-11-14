"""
VANTORIUM - TEK DOSYALIK WEB PUSH SUNUCUSU
-----------------------------------------
- Flask API + Firebase Admin doğrulaması + Web Push
- Service Worker kodu bu dosyanın içinden servis edilir.
- Vantorium HTML arayüzü sıkıştırılmış olarak bu dosyanın içine gömülüdür.
- Firebase Cloud Messaging (FCM) kullanılmaz.
- Firebase Service Account yalnızca Render Environment Variable'da tutulur.

Render Build Command:
pip install flask flask-cors firebase-admin pywebpush cryptography gunicorn

Render Start Command:
gunicorn app:app --workers 1 --threads 4 --timeout 120

Gerekli Render Environment Variable:
FIREBASE_SERVICE_ACCOUNT_JSON = Service Account JSON dosyasının TAM içeriği
FIREBASE_PROJECT_ID = vantoriumapps
FIREBASE_DATABASE_URL = https://vantoriumapps-default-rtdb.firebaseio.com/
VAPID_EMAIL = mailto:seninmailin@example.com

Kalıcı disk (Render):
Mount Path: /var/data
DATABASE_PATH=/var/data/subscriptions.db
VAPID_KEYS_PATH=/var/data/vapid_keys.json

Not: Firebase Service Account JSON dosyasını asla GitHub'a veya HTML'e koyma.
"""

import base64
import json
import os
import sqlite3
import zlib
from functools import wraps

from flask import Flask, Response, jsonify, request
from flask_cors import CORS

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from firebase_admin import db as firebase_db
from firebase_admin import firestore

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import webpush, WebPushException


# ---------------------------------------------------------------------------
# Gömülü Vantorium arayüzü. Tek app.py dosyası hem HTML'i hem API'yi sunar.
# ---------------------------------------------------------------------------
HTML_COMPRESSED_B64 = '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'
HTML_BYTES = zlib.decompress(base64.b64decode(HTML_COMPRESSED_B64))
HTML_PAGE = HTML_BYTES.decode("utf-8")


# ---------------------------------------------------------------------------
# Ayarlar ve Firebase Admin başlatma
# ---------------------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = "/var/data" if os.path.isdir("/var/data") else os.path.join(APP_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.getenv("DATABASE_PATH", os.path.join(DATA_DIR, "subscriptions.db"))
VAPID_KEYS_PATH = os.getenv("VAPID_KEYS_PATH", os.path.join(DATA_DIR, "vapid_keys.json"))
PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "vantoriumapps")
DATABASE_URL = os.getenv(
    "FIREBASE_DATABASE_URL",
    "https://vantoriumapps-default-rtdb.firebaseio.com/"
)
VAPID_EMAIL = os.getenv("VAPID_EMAIL", "mailto:admin@example.com")

service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
if not service_account_json:
    raise RuntimeError(
        "FIREBASE_SERVICE_ACCOUNT_JSON eksik. Render > Environment bölümüne "
        "Firebase Service Account JSON dosyasının tam içeriğini ekle."
    )

try:
    service_account_info = json.loads(service_account_json)
except json.JSONDecodeError as exc:
    raise RuntimeError(
        "FIREBASE_SERVICE_ACCOUNT_JSON geçerli JSON değil. Dosyanın tüm içeriğini "
        "tek environment variable olarak eklediğinden emin ol."
    ) from exc

if not firebase_admin._apps:
    firebase_credential = credentials.Certificate(service_account_info)
    firebase_admin.initialize_app(
        firebase_credential,
        {
            "projectId": PROJECT_ID,
            "databaseURL": DATABASE_URL,
        },
    )

firestore_db = firestore.client()


# ---------------------------------------------------------------------------
# VAPID anahtarları: ilk çalıştırmada otomatik üretilir, diskte saklanır.
# ---------------------------------------------------------------------------
def load_or_create_vapid_keys():
    if os.path.exists(VAPID_KEYS_PATH):
        with open(VAPID_KEYS_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if saved.get("private_key") and saved.get("public_key"):
            return saved["private_key"], saved["public_key"]

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")

    public_numbers = private_key.public_key().public_numbers()
    public_bytes = (
        b"\x04"
        + public_numbers.x.to_bytes(32, "big")
        + public_numbers.y.to_bytes(32, "big")
    )
    public_b64 = base64.urlsafe_b64encode(public_bytes).decode("ascii").rstrip("=")

    os.makedirs(os.path.dirname(VAPID_KEYS_PATH) or ".", exist_ok=True)
    temp_path = VAPID_KEYS_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump({"private_key": private_pem, "public_key": public_b64}, f)
    os.replace(temp_path, VAPID_KEYS_PATH)
    try:
        os.chmod(VAPID_KEYS_PATH, 0o600)
    except OSError:
        pass

    return private_pem, public_b64


VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY = load_or_create_vapid_keys()


# ---------------------------------------------------------------------------
# Flask / CORS
# ---------------------------------------------------------------------------
app = Flask(__name__)
allowed_origins = [
    item.strip()
    for item in os.getenv("FRONTEND_ORIGINS", "*").split(",")
    if item.strip()
]
CORS(
    app,
    origins=allowed_origins,
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "OPTIONS"],
)


def db_connect():
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subscriptions (
            uid TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            data TEXT NOT NULL,
            PRIMARY KEY (uid, endpoint)
        )
        """
    )
    conn.commit()
    return conn


def require_firebase_user(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify(error="Firebase oturum tokenı gerekli."), 401
        token = header.split(" ", 1)[1].strip()
        try:
            request.user_claims = firebase_auth.verify_id_token(
                token, check_revoked=True
            )
        except Exception:
            return jsonify(error="Geçersiz veya süresi dolmuş oturum."), 401
        return fn(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Web sayfası ve Service Worker aynı domainden sunulur.
# Böylece Service Worker için ikinci bir JS dosyası gerekmez.
# ---------------------------------------------------------------------------
SERVICE_WORKER_JS = r"""
'use strict';

self.addEventListener('push', function(event) {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_) {
    data = { body: event.data ? event.data.text() : 'Yeni mesaj' };
  }

  const title = data.title || 'Vantorium';
  const options = {
    body: data.body || 'Sana yeni bir mesaj gönderildi.',
    icon: data.icon || '/favicon.ico',
    badge: data.badge || '/favicon.ico',
    tag: data.tag || ('vantorium-' + Date.now()),
    renotify: true,
    data: { url: data.url || '/' }
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  const targetUrl = new URL(
    (event.notification.data && event.notification.data.url) || '/',
    self.location.origin
  ).href;

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(list) {
      for (const client of list) {
        if (client.url.startsWith(self.location.origin) && 'focus' in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }
      if (clients.openWindow) return clients.openWindow(targetUrl);
    })
  );
});
"""


@app.get("/")
@app.get("/index.html")
def index():
    return Response(HTML_PAGE, mimetype="text/html")


@app.get("/vantorium-sw.js")
def service_worker():
    response = Response(SERVICE_WORKER_JS, mimetype="application/javascript")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/health")
def health():
    return jsonify(status="ok", service="Vantorium Web Push", push="web-push")


@app.get("/api/config")
def public_config():
    return jsonify(vapidPublicKey=VAPID_PUBLIC_KEY)


@app.post("/api/subscribe")
@require_firebase_user
def subscribe():
    body = request.get_json(silent=True) or {}
    subscription = body.get("subscription")

    if (
        not isinstance(subscription, dict)
        or not subscription.get("endpoint")
        or not isinstance(subscription.get("keys"), dict)
    ):
        return jsonify(error="Push abonelik bilgisi eksik."), 400

    uid = request.user_claims["uid"]
    conn = db_connect()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO subscriptions(uid, endpoint, data)
            VALUES (?, ?, ?)
            """,
            (uid, subscription["endpoint"], json.dumps(subscription)),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(ok=True)


@app.post("/api/unsubscribe")
@require_firebase_user
def unsubscribe():
    body = request.get_json(silent=True) or {}
    subscription = body.get("subscription") or {}
    endpoint = subscription.get("endpoint")

    if endpoint:
        conn = db_connect()
        try:
            conn.execute(
                "DELETE FROM subscriptions WHERE uid=? AND endpoint=?",
                (request.user_claims["uid"], endpoint),
            )
            conn.commit()
        finally:
            conn.close()

    return jsonify(ok=True)


@app.post("/api/notify")
@require_firebase_user
def notify():
    body = request.get_json(silent=True) or {}
    sender_uid = request.user_claims["uid"]
    recipient_uid = str(body.get("recipientUid", "")).strip()
    chat_id = str(body.get("chatId", "")).strip()
    message = str(body.get("message", "Yeni mesaj")).strip()[:500]

    if not recipient_uid or not chat_id or recipient_uid == sender_uid:
        return jsonify(error="Alıcı veya sohbet bilgisi hatalı."), 400

    # Vantorium birebir sohbet ID'si UID'lerin alfabetik sıralanmış halidir.
    expected_chat_id = "_".join(sorted([sender_uid, recipient_uid]))
    if chat_id != expected_chat_id:
        return jsonify(error="Bu sohbet için bildirim gönderme yetkin yok."), 403

    # İki kullanıcının da sohbet kaydında bulunduğunu doğrula.
    try:
        sender_chat = firebase_db.reference(
            f"user_chats/{sender_uid}/{chat_id}"
        ).get()
        recipient_chat = firebase_db.reference(
            f"user_chats/{recipient_uid}/{chat_id}"
        ).get()
    except Exception:
        app.logger.exception("Realtime Database sohbet doğrulama hatası")
        return jsonify(error="Sohbet doğrulanamadı."), 503

    if not sender_chat or not recipient_chat:
        return jsonify(error="Sohbet üyeliği doğrulanamadı."), 403

    # Bildirimdeki gönderen adını istemciden değil Firestore profilinden al.
    user_doc = firestore_db.collection("users").document(sender_uid).get()
    user_data = user_doc.to_dict() or {} if user_doc.exists else {}
    sender_name = (
        user_data.get("displayName")
        or user_data.get("username")
        or "Yeni mesaj"
    )[:80]

    payload = json.dumps(
        {
            "title": sender_name,
            "body": message or "Sana yeni bir mesaj gönderdi.",
            "url": "/",
            "tag": "vantorium-" + chat_id,
        },
        ensure_ascii=False,
    )

    conn = db_connect()
    try:
        rows = conn.execute(
            "SELECT endpoint, data FROM subscriptions WHERE uid=?",
            (recipient_uid,),
        ).fetchall()
    finally:
        conn.close()

    sent = removed = failed = 0
    for endpoint, raw_subscription in rows:
        try:
            webpush(
                subscription_info=json.loads(raw_subscription),
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_EMAIL},
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                conn = db_connect()
                try:
                    conn.execute(
                        "DELETE FROM subscriptions WHERE uid=? AND endpoint=?",
                        (recipient_uid, endpoint),
                    )
                    conn.commit()
                finally:
                    conn.close()
                removed += 1
            else:
                failed += 1
                app.logger.warning("Web Push başarısız (%s): %s", status, exc)
        except Exception:
            failed += 1
            app.logger.exception("Web Push gönderim hatası")

    return jsonify(ok=True, sent=sent, removed=removed, failed=failed)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
