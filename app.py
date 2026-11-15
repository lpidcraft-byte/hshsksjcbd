import os
import json
import logging
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, auth, db, messaging

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

DATABASE_URL = os.environ.get(
    "FIREBASE_DATABASE_URL",
    "https://vantoriumapps-default-rtdb.firebaseio.com"
)

def initialize_firebase():
    if firebase_admin._apps:
        return

    raw_credentials = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not raw_credentials:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON environment variable is missing")

    try:
        service_account = json.loads(raw_credentials)
    except json.JSONDecodeError as exc:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON") from exc

    cred = credentials.Certificate(service_account)
    firebase_admin.initialize_app(cred, {"databaseURL": DATABASE_URL})

def verify_user():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header.split(" ", 1)[1].strip()
    if not token:
        return None
    try:
        return auth.verify_id_token(token)
    except Exception:
        logging.exception("Firebase ID token verification failed")
        return None

@app.get("/")
def health():
    return jsonify({"ok": True, "service": "Vantorium FCM backend"})

@app.get("/health")
def health_check():
    return jsonify({"ok": True})

@app.post("/api/notify")
def notify():
    user = verify_user()
    if not user:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    chat_id = str(payload.get("chatId", "")).strip()
    message_id = str(payload.get("messageId", "")).strip()

    if not chat_id or not message_id:
        return jsonify({
            "ok": False,
            "error": "chatId and messageId are required"
        }), 400

    try:
        initialize_firebase()
        message_ref = db.reference(f"messages/{chat_id}/{message_id}")
        message_data = message_ref.get()

        if not isinstance(message_data, dict):
            return jsonify({"ok": False, "error": "message_not_found"}), 404

        sender_uid = str(message_data.get("senderId", ""))
        if sender_uid != str(user.get("uid", "")):
            return jsonify({"ok": False, "error": "forbidden"}), 403

        # Current Vantorium direct-chat format: sorted UIDs joined with "_".
        user_ids = chat_id.split("_")
        if len(user_ids) != 2 or sender_uid not in user_ids:
            return jsonify({
                "ok": True,
                "sent": False,
                "reason": "group_or_non_direct_chat_not_supported"
            }), 200

        recipient_uid = next((uid for uid in user_ids if uid != sender_uid), None)
        if not recipient_uid:
            return jsonify({"ok": True, "sent": False, "reason": "recipient_missing"}), 200

        token_data = db.reference(f"fcmTokens/{recipient_uid}/token").get()
        if not isinstance(token_data, str) or not token_data:
            return jsonify({"ok": True, "sent": False, "reason": "recipient_has_no_fcm_token"}), 200

        sender_name = str(message_data.get("senderName") or "Yeni mesaj")[:80]
        body = str(message_data.get("text") or "").strip()
        if not body and message_data.get("mediaUrl"):
            media_type = str(message_data.get("mediaType") or "")
            body = "🎥 Video gönderdi" if media_type == "video" else "📷 Fotoğraf gönderdi"
        if not body:
            body = "Sana yeni bir mesaj gönderdi"
        body = body[:180]

        notification = messaging.Message(
            token=token_data,
            notification=messaging.Notification(title=sender_name, body=body),
            data={
                "type": "chat_message",
                "chatId": chat_id,
                "messageId": message_id,
                "senderId": sender_uid
            },
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    sound="default",
                    channel_id="vantorium_messages"
                )
            )
        )

        try:
            messaging.send(notification)
        except messaging.UnregisteredError:
            db.reference(f"fcmTokens/{recipient_uid}").delete()
            logging.info("Removed expired FCM token for %s", recipient_uid)
            return jsonify({"ok": True, "sent": False, "reason": "expired_token"}), 200

        return jsonify({"ok": True, "sent": True}), 200

    except Exception as exc:
        logging.exception("Notification backend error")
        return jsonify({"ok": False, "error": "server_error"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
