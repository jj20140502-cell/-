import os
import hashlib

import asyncpg
from flask import Flask, jsonify, request

app = Flask(__name__)
DATABASE_URL = os.getenv("DATABASE_URL", "")
pool = None


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


@app.before_request
async def ensure_pool():
    global pool
    if pool is None:
        if not DATABASE_URL:
            return jsonify({"ok": False, "code": "server_config_error"}), 500
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)


@app.get("/")
def health():
    return jsonify({"ok": True, "service": "manyong-license-api"})


@app.post("/api/license/verify")
async def verify_license():
    body = request.get_json(silent=True) or {}
    license_key = str(body.get("license_key", "")).strip()
    device_hash = str(body.get("device_hash", "")).strip().lower()

    if not license_key or not device_hash:
        return jsonify({
            "ok": False,
            "code": "missing_fields",
            "message": "라이선스 키와 기기 정보가 필요합니다.",
        }), 400

    # 클라이언트가 원본 하드웨어 정보를 보내지 않고 SHA-256 결과만 보내도록 제한
    if len(device_hash) != 64 or any(c not in "0123456789abcdef" for c in device_hash):
        return jsonify({
            "ok": False,
            "code": "invalid_device_hash",
            "message": "기기 인증 정보 형식이 올바르지 않습니다.",
        }), 400

    license_hash = sha256_text(license_key)

    async with pool.acquire() as con:
        async with con.transaction():
            row = await con.fetchrow("""
                SELECT discord_id, status, device_hash
                FROM manyong_licenses
                WHERE license_key_hash=$1
                FOR UPDATE
            """, license_hash)

            if not row:
                return jsonify({
                    "ok": False,
                    "code": "invalid_license",
                    "message": "유효하지 않은 라이선스 키입니다.",
                }), 401

            if row["status"] != "active":
                return jsonify({
                    "ok": False,
                    "code": "license_not_active",
                    "message": "현재 사용할 수 없는 라이선스입니다.",
                }), 403

            registered = row["device_hash"]

            # 최초 인증 PC 자동 귀속
            if not registered:
                await con.execute("""
                    UPDATE manyong_licenses
                    SET device_hash=$1,
                        activated_at=COALESCE(activated_at, NOW()),
                        updated_at=NOW()
                    WHERE discord_id=$2
                """, device_hash, row["discord_id"])

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


@app.post("/api/license/status")
async def license_status():
    # verify와 동일한 검증을 사용. 향후 클라이언트 주기검증용 엔드포인트.
    return await verify_license()
