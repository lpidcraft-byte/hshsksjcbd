
import os
import json
import logging

from flask import Flask, request, jsonify, make_response
import firebase_admin
from firebase_admin import credentials, auth, db, messaging

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

DATABASE_URL = os.environ.get(
    "FIREBASE_DATABASE_URL",
    "https://vantoriumapps-default-rtdb.firebaseio.com"
)


# CORS: Android WebView ve web istemcileri için
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization"
    )
    response.headers["Access-Control-Allow-Methods"] = (
        "GET, POST, OPTIONS"
    )
    return response


def initialize_firebase():
    if firebase_admin._apps:
        return

    raw_credentials = os.environ.get(
        "FIREBASE_SERVICE_ACCOUNT_JSON"
    )

    if not raw_credentials:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_JSON is missing"
        )

    service_account = json.loads(raw_credentials)

    cred = credentials.Certificate(service_account)

    firebase_admin.initialize_app(
        cred,
        {"databaseURL": DATABASE_URL}
    )


def verify_user():
    header = request.headers.get("Authorization", "")

    if not header.startswith("Bearer "):
        return None

    token = header.split(" ", 1)[1].strip()

    if not token:
        return None

    try:
        initialize_firebase()
        return auth.verify_id_token(token)
    except Exception:
        logging.exception("Firebase authentication failed")
        return None


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "ok": True,
        "service": "Vantorium FCM Backend"
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


@app.route("/api/notify", methods=["OPTIONS"])
def notify_options():
    return make_response("", 204)


@app.route("/api/notify", methods=["POST"])
def notify():

    user = verify_user()

    if not user:
        return jsonify({
            "ok": False,
            "error": "unauthorized"
        }), 401

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

        message_data = db.reference(
            f"messages/{chat_id}/{message_id}"
        ).get()

        if not isinstance(message_data, dict):
            return jsonify({
                "ok": False,
                "error": "message_not_found"
            }), 404

        sender_uid = str(message_data.get("senderId", ""))

        if sender_uid != str(user.get("uid", "")):
            return jsonify({
                "ok": False,
                "error": "forbidden"
            }), 403

        # Birebir sohbet desteği
        user_ids = chat_id.split("_")

        if len(user_ids) != 2 or sender_uid not in user_ids:
            return jsonify({
                "ok": True,
                "sent": False,
                "reason": "group_chat_not_supported"
            })

        recipient_uid = next(
            (uid for uid in user_ids if uid != sender_uid),
            None
        )

        if not recipient_uid:
            return jsonify({
                "ok": True,
                "sent": False,
                "reason": "recipient_missing"
            })

        token = db.reference(
            f"fcmTokens/{recipient_uid}/token"
        ).get()

        if not isinstance(token, str) or not token:
            return jsonify({
                "ok": True,
                "sent": False,
                "reason": "recipient_has_no_fcm_token"
            })

        sender_name = str(
            message_data.get("senderName") or "Yeni mesaj"
        )[:80]

        body = str(
            message_data.get("text") or ""
        ).strip()

        if not body and message_data.get("mediaUrl"):
            media_type = str(
                message_data.get("mediaType") or ""
            )

            body = (
                "🎥 Video gönderdi"
                if media_type == "video"
                else "📷 Fotoğraf gönderdi"
            )

        if not body:
            body = "Sana yeni bir mesaj gönderdi"

        body = body[:180]

        fcm_message = messaging.Message(
            token=token,

            notification=messaging.Notification(
                title=sender_name,
                body=body
            ),

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
            result = messaging.send(fcm_message)

            logging.info(
                "FCM sent successfully: %s",
                result
            )

        except messaging.UnregisteredError:
            db.reference(
                f"fcmTokens/{recipient_uid}"
            ).delete()

            return jsonify({
                "ok": True,
                "sent": False,
                "reason": "expired_token"
            })

        return jsonify({
            "ok": True,
            "sent": True
        })

    except Exception:
        logging.exception("FCM notification error")

        return jsonify({
            "ok": False,
            "error": "server_error"
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port
    )
