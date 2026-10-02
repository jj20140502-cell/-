import os
import hashlib

import psycopg
from flask import Flask, jsonify, request

app = Flask(__name__)
DATABASE_URL = os.getenv("DATABASE_URL", "")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


@app.get("/")
def health():
    return jsonify({"ok": True, "service": "manyong-license-api"})


@app.post("/api/license/verify")
def verify_license():
    if not DATABASE_URL:
        return jsonify({
            "ok": False,
            "code": "server_config_error",
            "message": "라이선스 서버 설정 오류입니다.",
        }), 500

    body = request.get_json(silent=True) or {}
    license_key = str(body.get("license_key", "")).strip()
    device_hash = str(body.get("device_hash", "")).strip().lower()

    if not license_key or not device_hash:
        return jsonify({
            "ok": False,
            "code": "missing_fields",
            "message": "라이선스 키와 기기 정보가 필요합니다.",
        }), 400

    if len(device_hash) != 64 or any(c not in "0123456789abcdef" for c in device_hash):
        return jsonify({
            "ok": False,
            "code": "invalid_device_hash",
            "message": "기기 인증 정보 형식이 올바르지 않습니다.",
        }), 400

    license_hash = sha256_text(license_key)

    try:
        with psycopg.connect(DATABASE_URL) as con:
            with con.cursor() as cur:
                cur.execute("""
                    SELECT discord_id, status, device_hash
                    FROM manyong_licenses
                    WHERE license_key_hash=%s
                    FOR UPDATE
                """, (license_hash,))
                row = cur.fetchone()

                if not row:
                    return jsonify({
                        "ok": False,
                        "code": "invalid_license",
                        "message": "유효하지 않은 라이선스 키입니다.",
                    }), 401

                discord_id, status, registered = row

                if status != "active":
                    return jsonify({
                        "ok": False,
                        "code": "license_not_active",
                        "message": "현재 사용할 수 없는 라이선스입니다.",
                    }), 403

                if not registered:
                    cur.execute("""
                        UPDATE manyong_licenses
                        SET device_hash=%s,
                            activated_at=COALESCE(activated_at, NOW()),
                            updated_at=NOW()
                        WHERE discord_id=%s
                    """, (device_hash, discord_id))
                    con.commit()

                    return jsonify({
                        "ok": True,
                        "code": "activated",
                        "message": "라이선스가 이 PC에 등록되었습니다.",
                    })

                if registered != device_hash:
                    return jsonify({
                        "ok": False,
                        "code": "device_mismatch",
                        "message": "이 라이선스는 다른 PC에 등록되어 있습니다.",
                    }), 403

                return jsonify({
                    "ok": True,
                    "code": "valid",
                    "message": "라이선스 인증에 성공했습니다.",
                })

    except Exception:
        app.logger.exception("license verification failed")
        return jsonify({
            "ok": False,
            "code": "server_error",
            "message": "라이선스 서버 내부 오류가 발생했습니다.",
        }), 500


@app.post("/api/license/status")
def license_status():
    return verify_license()
