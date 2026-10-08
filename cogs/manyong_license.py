import os, hashlib, secrets, string
import asyncpg
import discord
from discord import app_commands
from discord.ext import commands

ADMIN_ROLE_ID = 1520648377702809659

# 길드원 라이선스 신청 전용 채널
LICENSE_REQUEST_CHANNEL_ID = 1555452985344000091
DATABASE_URL = os.getenv("DATABASE_URL", "")
LICENSE_CHANNEL_ID = int(os.getenv("MANYONG_LICENSE_CHANNEL_ID", "0") or 0)

def key_hash(v):
    return hashlib.sha256(v.encode()).hexdigest()

def new_key():
    chars = string.ascii_uppercase + string.digits
    parts = ["".join(secrets.choice(chars) for _ in range(4)) for _ in range(4)]
    return "MANYONG-" + "-".join(parts)

async def admin_ok(i):
    if not i.guild or not isinstance(i.user, discord.Member):
        return False
    return i.user.id == i.guild.owner_id or any(r.id == ADMIN_ROLE_ID for r in i.user.roles)

async def admin_check(i):
    if await admin_ok(i):
        return True
    await i.response.send_message("❌ 서버 소유자 또는 지정 운영진 역할 보유자만 사용할 수 있습니다.", ephemeral=True)
    return False

class LicenseRequestView(discord.ui.View):
    """Render/봇 재시작 후에도 유지되는 길드원 신청 버튼."""
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="라이선스 신청",
        emoji="🔑",
        style=discord.ButtonStyle.green,
        custom_id="manyong_license_request_v1",
    )
    async def request_button(self, i: discord.Interaction, button: discord.ui.Button):
        await self.cog.submit_request(i)


class DownloadView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="마뇽 감지기 다운로드",
                emoji="📥",
                style=discord.ButtonStyle.link,
                url="https://github.com/jj20140502-cell/-/releases/download/v1.0.0/ManyongDetector.exe",
            )
        )


class DeleteLicenseConfirmView(discord.ui.View):
    def __init__(self, cog, target_id: int, requester_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.target_id = int(target_id)
        self.requester_id = int(requester_id)

    @discord.ui.button(label="라이선스 완전 삭제", emoji="🗑️",
                       style=discord.ButtonStyle.danger)
    async def confirm_delete(self, i, b):
        if i.user.id != self.requester_id:
            await i.response.send_message(
                "❌ 이 확인 버튼은 명령을 실행한 운영진만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return
        if not await admin_check(i):
            return

        row = await self.cog.row(self.target_id)
        if not row:
            await i.response.send_message(
                "ℹ️ 이미 삭제되었거나 기록이 없습니다.",
                ephemeral=True,
            )
            return

        thread_id = row["thread_id"] if "thread_id" in row else None

        async with self.cog.pool.acquire() as c:
            await c.execute(
                "DELETE FROM manyong_licenses WHERE discord_id=$1",
                self.target_id,
            )

        await i.response.edit_message(
            content=(
                f"🗑️ <@{self.target_id}>의 라이선스 기록을 완전히 삭제했습니다.\n"
                "기존 키·PC 귀속·상태가 모두 폐기되었으며 다시 신청할 수 있습니다."
            ),
            view=None,
        )

        # 관리 스레드가 있으면 삭제 사실을 남긴 뒤 잠금/보관.
        if thread_id:
            try:
                thread = i.guild.get_thread(int(thread_id))
                if thread is None:
                    thread = await i.guild.fetch_channel(int(thread_id))
                if isinstance(thread, discord.Thread):
                    await thread.send(
                        f"🗑️ 라이선스 기록 완전 삭제\n담당 운영진: {i.user.mention}"
                    )
                    await thread.edit(archived=True, locked=True)
            except Exception:
                pass

    @discord.ui.button(label="취소", emoji="✖️",
                       style=discord.ButtonStyle.secondary)
    async def cancel_delete(self, i, b):
        if i.user.id != self.requester_id:
            await i.response.send_message(
                "❌ 이 확인 버튼은 명령을 실행한 운영진만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return
        await i.response.edit_message(
            content="삭제를 취소했습니다.",
            view=None,
        )


class ThreadManageView(discord.ui.View):
    """신청자별 운영진 관리 패널."""
    def __init__(self, cog, uid: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.uid = int(uid)
        for item in self.children:
            if item.custom_id:
                item.custom_id = f"{item.custom_id}:{self.uid}"

    @discord.ui.button(label="승인", emoji="✅", style=discord.ButtonStyle.green,
                       custom_id="manyong_thread_approve")
    async def approve_btn(self, i, b):
        if not await admin_check(i): return
        await self.cog.issue(i, self.uid)
        await self.cog.after_thread_action(i, self.uid, "✅ 라이선스 승인")

    @discord.ui.button(label="거절", emoji="❌", style=discord.ButtonStyle.red,
                       custom_id="manyong_thread_reject")
    async def reject_btn(self, i, b):
        if not await admin_check(i): return
        await self.cog.reject(i, self.uid)
        await self.cog.after_thread_action(i, self.uid, "❌ 신청 거절")

    @discord.ui.button(label="차단", emoji="🔴", style=discord.ButtonStyle.danger,
                       custom_id="manyong_thread_block")
    async def block_btn(self, i, b):
        if not await admin_check(i): return
        await self.cog.thread_block(i, self.uid)

    @discord.ui.button(label="차단해제", emoji="🟢", style=discord.ButtonStyle.success,
                       custom_id="manyong_thread_unblock")
    async def unblock_btn(self, i, b):
        if not await admin_check(i): return
        await self.cog.thread_unblock(i, self.uid)

    @discord.ui.button(label="기기초기화", emoji="♻️", style=discord.ButtonStyle.secondary,
                       custom_id="manyong_thread_reset")
    async def reset_btn(self, i, b):
        if not await admin_check(i): return
        await self.cog.thread_reset_device(i, self.uid)

    @discord.ui.button(label="재발급", emoji="🔄", style=discord.ButtonStyle.primary,
                       custom_id="manyong_thread_reissue")
    async def reissue_btn(self, i, b):
        if not await admin_check(i): return
        await self.cog.thread_reissue(i, self.uid)

    @discord.ui.button(label="추가발급", emoji="➕", style=discord.ButtonStyle.success,
                       custom_id="manyong_thread_extra_issue")
    async def extra_issue_btn(self, i, b):
        if not await admin_check(i): return
        await self.cog.thread_issue_extra(i, self.uid)

    @discord.ui.button(label="추가재발급", emoji="🔁", style=discord.ButtonStyle.primary,
                       custom_id="manyong_thread_extra_reissue")
    async def extra_reissue_btn(self, i, b):
        if not await admin_check(i): return
        await self.cog.thread_reissue_extra(i, self.uid)

    @discord.ui.button(label="추가기기초기화", emoji="🖥️", style=discord.ButtonStyle.secondary,
                       custom_id="manyong_thread_extra_reset")
    async def extra_reset_btn(self, i, b):
        if not await admin_check(i): return
        await self.cog.thread_reset_extra_device(i, self.uid)

    @discord.ui.button(label="상태 새로고침", emoji="📋", style=discord.ButtonStyle.secondary,
                       custom_id="manyong_thread_refresh")
    async def refresh_btn(self, i, b):
        if not await admin_check(i): return
        await self.cog.refresh_thread_card(i.guild, self.uid)
        await i.response.send_message("📋 상태 카드를 새로고침했습니다.", ephemeral=True)


class ApprovalView(discord.ui.View):
    def __init__(self, cog, uid):
        super().__init__(timeout=86400)
        self.cog, self.uid = cog, uid

    @discord.ui.button(label="승인", emoji="✅", style=discord.ButtonStyle.green)
    async def yes(self, i, b):
        if not await admin_check(i): return
        await self.cog.issue(i, self.uid)
        for x in self.children: x.disabled = True
        try: await i.message.edit(view=self)
        except: pass

    @discord.ui.button(label="거절", emoji="❌", style=discord.ButtonStyle.red)
    async def no(self, i, b):
        if not await admin_check(i): return
        await self.cog.reject(i, self.uid)
        for x in self.children: x.disabled = True
        try: await i.message.edit(view=self)
        except: pass

class ManyongLicense(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pool = None

    async def cog_load(self):
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL 환경변수가 없습니다.")
        self.pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)

        # 재시작 후에도 기존 '라이선스 신청' 버튼이 계속 작동하도록 등록
        self.bot.add_view(LicenseRequestView(self))

        async with self.pool.acquire() as c:
            await c.execute("""
            CREATE TABLE IF NOT EXISTS manyong_licenses(
              discord_id BIGINT PRIMARY KEY,
              discord_name TEXT NOT NULL,
              license_key_hash TEXT,
              status TEXT NOT NULL DEFAULT 'pending',
              device_hash TEXT,
              requested_at TIMESTAMPTZ DEFAULT NOW(),
              approved_at TIMESTAMPTZ,
              approved_by BIGINT,
              activated_at TIMESTAMPTZ,
              updated_at TIMESTAMPTZ DEFAULT NOW()
            )""")
            await c.execute(
                "ALTER TABLE manyong_licenses ADD COLUMN IF NOT EXISTS thread_id BIGINT"
            )
            await c.execute(
                "ALTER TABLE manyong_licenses ADD COLUMN IF NOT EXISTS manage_message_id BIGINT"
            )

        async with self.pool.acquire() as c:
            await c.execute("""
                CREATE TABLE IF NOT EXISTS manyong_extra_licenses (
                    discord_id BIGINT PRIMARY KEY REFERENCES manyong_licenses(discord_id) ON DELETE CASCADE,
                    license_key_hash TEXT NOT NULL UNIQUE,
                    device_hash TEXT,
                    activated_at TIMESTAMPTZ,
                    issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    issued_by BIGINT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

        # 기존 관리 스레드의 버튼도 Render 재시작 후 계속 동작하도록 복원
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                "SELECT discord_id FROM manyong_licenses WHERE thread_id IS NOT NULL"
            )
        for r in rows:
            self.bot.add_view(ThreadManageView(self, int(r["discord_id"])))

    async def row(self, uid):
        async with self.pool.acquire() as c:
            return await c.fetchrow("SELECT * FROM manyong_licenses WHERE discord_id=$1", uid)

    async def submit_request(self, i):
        """버튼/명령 공통 라이선스 신청 처리 + 운영진 관리 스레드 생성."""
        if i.channel_id != LICENSE_REQUEST_CHANNEL_ID:
            await i.response.send_message(
                f"❌ 라이선스 신청은 <#{LICENSE_REQUEST_CHANNEL_ID}> 채널에서만 가능합니다.",
                ephemeral=True,
            )
            return

        r = await self.row(i.user.id)
        if r and r["status"] == "active":
            await i.response.send_message("ℹ️ 이미 활성 라이선스가 있습니다.", ephemeral=True)
            return
        if r and r["status"] == "blocked":
            await i.response.send_message("❌ 차단된 라이선스입니다. 운영진에게 문의해 주세요.", ephemeral=True)
            return
        if r and r["status"] == "pending":
            await i.response.send_message("⏳ 이미 승인 대기 중입니다.", ephemeral=True)
            return

        async with self.pool.acquire() as c:
            await c.execute(
                """INSERT INTO manyong_licenses
                   (discord_id,discord_name,status,license_key_hash,device_hash,
                    requested_at,updated_at,thread_id,manage_message_id)
                   VALUES($1,$2,'pending',NULL,NULL,NOW(),NOW(),NULL,NULL)
                   ON CONFLICT(discord_id) DO UPDATE SET
                   discord_name=$2,status='pending',license_key_hash=NULL,device_hash=NULL,
                   requested_at=NOW(),updated_at=NOW(),thread_id=NULL,manage_message_id=NULL""",
                i.user.id, str(i.user)
            )

        ch = i.guild.get_channel(LICENSE_CHANNEL_ID) if LICENSE_CHANNEL_ID else None
        if not ch:
            await i.response.send_message("⚠️ 승인 채널이 아직 설정되지 않았습니다.", ephemeral=True)
            return

        e = discord.Embed(
            title="🐉 마뇽 감지기 라이선스 신청",
            description=(
                f"신청자: {i.user.mention}\n"
                f"Discord ID: `{i.user.id}`\n\n"
                "아래 생성된 스레드에서 라이선스를 관리하세요."
            ),
            color=discord.Color.blurple(),
        )
        parent = await ch.send(embed=e)

        thread = await parent.create_thread(
            name=f"🔑 {i.user.display_name[:70]}님의 마뇽 라이선스",
            auto_archive_duration=10080,
        )

        manage_msg = await thread.send(
            embed=await self.make_thread_embed(i.user.id),
            view=ThreadManageView(self, i.user.id),
        )

        async with self.pool.acquire() as c:
            await c.execute(
                "UPDATE manyong_licenses SET thread_id=$1,manage_message_id=$2,updated_at=NOW() "
                "WHERE discord_id=$3",
                thread.id, manage_msg.id, i.user.id
            )

        self.bot.add_view(ThreadManageView(self, i.user.id))
        await thread.send(
            "📌 이 스레드에서 승인·거절·차단·차단해제·기기초기화·재발급을 관리합니다."
        )

        await i.response.send_message(
            "✅ 라이선스 신청이 접수되었습니다. 운영진 승인을 기다려 주세요.",
            ephemeral=True,
        )

    def status_label(self, status):
        return {
            "pending": "🟡 승인 대기",
            "active": "🟢 활성",
            "blocked": "🔴 차단",
            "rejected": "⚫ 거절",
        }.get(status, status)

    async def make_thread_embed(self, uid):
        r = await self.row(uid)
        if not r:
            return discord.Embed(title="라이선스 기록 없음", color=discord.Color.dark_grey())

        colors = {
            "pending": discord.Color.gold(),
            "active": discord.Color.green(),
            "blocked": discord.Color.red(),
            "rejected": discord.Color.dark_grey(),
        }
        e = discord.Embed(
            title="🐉 마뇽 감지기 라이선스 관리",
            color=colors.get(r["status"], discord.Color.blurple()),
        )
        e.add_field(name="사용자", value=f"<@{uid}>", inline=False)
        e.add_field(name="상태", value=self.status_label(r["status"]), inline=True)
        e.add_field(name="PC 등록", value="🖥️ 등록됨" if r["device_hash"] else "➖ 미등록", inline=True)
        e.add_field(name="키", value="🔑 발급됨" if r["license_key_hash"] else "➖ 미발급", inline=True)
        async with self.pool.acquire() as c:
            extra = await c.fetchrow(
                "SELECT device_hash FROM manyong_extra_licenses WHERE discord_id=$1", uid
            )
        e.add_field(name="추가 라이선스", value=(
            "🔑 발급됨 · " + ("🖥️ PC 등록됨" if extra["device_hash"] else "➖ PC 미등록")
            if extra else "➖ 미발급"
        ), inline=False)
        e.set_footer(text="버튼 동작 후 상태가 자동 갱신됩니다.")
        return e

    async def get_manage_thread(self, guild, uid):
        r = await self.row(uid)
        if not r or not r["thread_id"]:
            return None
        thread = guild.get_thread(int(r["thread_id"]))
        if thread:
            return thread
        try:
            ch = await guild.fetch_channel(int(r["thread_id"]))
            return ch if isinstance(ch, discord.Thread) else None
        except Exception:
            return None

    async def refresh_thread_card(self, guild, uid):
        r = await self.row(uid)
        if not r or not r["manage_message_id"]:
            return
        thread = await self.get_manage_thread(guild, uid)
        if not thread:
            return
        try:
            msg = await thread.fetch_message(int(r["manage_message_id"]))
            await msg.edit(embed=await self.make_thread_embed(uid),
                           view=ThreadManageView(self, uid))
        except Exception:
            pass

    async def after_thread_action(self, i, uid, action_text):
        await self.refresh_thread_card(i.guild, uid)
        thread = await self.get_manage_thread(i.guild, uid)
        if thread:
            try:
                await thread.send(f"{action_text}\n담당 운영진: {i.user.mention}")
            except Exception:
                pass

    async def thread_block(self, i, uid):
        async with self.pool.acquire() as c:
            result = await c.execute(
                "UPDATE manyong_licenses SET status='blocked',updated_at=NOW() WHERE discord_id=$1", uid)
        await i.response.send_message(
            "❌ 기록이 없습니다." if result == "UPDATE 0" else "🔴 라이선스를 차단했습니다.",
            ephemeral=True)
        if result != "UPDATE 0":
            await self.after_thread_action(i, uid, "🔴 라이선스 차단")

    async def thread_unblock(self, i, uid):
        r = await self.row(uid)
        if not r:
            await i.response.send_message("❌ 기록이 없습니다.", ephemeral=True); return
        if r["status"] != "blocked":
            await i.response.send_message("ℹ️ 현재 차단 상태가 아닙니다.", ephemeral=True); return
        if not r["license_key_hash"]:
            await i.response.send_message("❌ 기존 키가 없어 재발급이 필요합니다.", ephemeral=True); return
        async with self.pool.acquire() as c:
            await c.execute(
                "UPDATE manyong_licenses SET status='active',updated_at=NOW() WHERE discord_id=$1", uid)
        await i.response.send_message("🟢 차단을 해제했습니다.", ephemeral=True)
        await self.after_thread_action(i, uid, "🟢 라이선스 차단 해제")

    async def thread_reset_device(self, i, uid):
        async with self.pool.acquire() as c:
            result = await c.execute(
                "UPDATE manyong_licenses SET device_hash=NULL,activated_at=NULL,updated_at=NOW() "
                "WHERE discord_id=$1", uid)
        await i.response.send_message(
            "❌ 기록이 없습니다." if result == "UPDATE 0"
            else "♻️ 기기 등록을 초기화했습니다.",
            ephemeral=True)
        if result != "UPDATE 0":
            await self.after_thread_action(i, uid, "♻️ 등록 기기 초기화")

    async def thread_issue_extra(self, i, uid):
        # DB 트랜잭션과 PK 제약으로 동시 클릭에도 1개만 발급.
        key = new_key()
        async with self.pool.acquire() as c:
            async with c.transaction():
                base = await c.fetchrow(
                    "SELECT status,license_key_hash FROM manyong_licenses WHERE discord_id=$1 FOR UPDATE", uid
                )
                if not base or base["status"] != "active" or not base["license_key_hash"]:
                    await i.response.send_message("❌ 기본 라이선스가 활성 상태인 사용자만 추가발급할 수 있습니다.", ephemeral=True)
                    return
                existing = await c.fetchval(
                    "SELECT 1 FROM manyong_extra_licenses WHERE discord_id=$1", uid
                )
                if existing:
                    await i.response.send_message("ℹ️ 이미 추가 라이선스가 발급된 사용자입니다. 중복 발급하지 않았습니다.", ephemeral=True)
                    return
                await c.execute(
                    "INSERT INTO manyong_extra_licenses(discord_id,license_key_hash,issued_by) VALUES($1,$2,$3)",
                    uid, key_hash(key), i.user.id
                )
        member = i.guild.get_member(uid)
        if member is None:
            try: member = await i.guild.fetch_member(uid)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException): pass
        sent = False
        if member:
            try:
                await member.send(
                    "➕ **마뇽 감지기 추가 라이선스**\n\n"
                    f"두 번째 PC용 라이선스 키: `{key}`\n\n"
                    "기존 라이선스는 그대로 유지됩니다. 새 키는 최초 인증한 PC에 등록됩니다.\n"
                    "**GORI GUILD**", view=DownloadView()
                )
                sent = True
            except discord.HTTPException:
                pass
        await i.response.send_message(
            "✅ 추가 라이선스 발급 및 DM 전송 완료." if sent else
            f"⚠️ 추가 라이선스 발급 완료, DM 전송 실패. 이 키를 사용자에게 안전하게 전달하세요: `{key}`",
            ephemeral=True
        )
        await self.after_thread_action(i, uid, "➕ 추가 라이선스 발급")

    async def thread_reissue_extra(self, i, uid):
        """기존 추가 키를 폐기하고 새 키로 교체. 기본 키는 그대로 유지."""
        key = new_key()
        async with self.pool.acquire() as c:
            async with c.transaction():
                base = await c.fetchrow(
                    "SELECT status FROM manyong_licenses WHERE discord_id=$1 FOR UPDATE", uid
                )
                if not base or base["status"] != "active":
                    await i.response.send_message(
                        "❌ 기본 라이선스가 활성 상태인 사용자만 추가 키를 재발급할 수 있습니다.",
                        ephemeral=True,
                    )
                    return
                result = await c.execute(
                    "UPDATE manyong_extra_licenses "
                    "SET license_key_hash=$1, device_hash=NULL, activated_at=NULL, "
                    "issued_at=NOW(), issued_by=$2, updated_at=NOW() "
                    "WHERE discord_id=$3",
                    key_hash(key), i.user.id, uid,
                )
                if result == "UPDATE 0":
                    await i.response.send_message(
                        "❌ 추가 라이선스가 없습니다. 먼저 추가발급을 사용해 주세요.", ephemeral=True
                    )
                    return
        member = i.guild.get_member(uid)
        if member is None:
            try:
                member = await i.guild.fetch_member(uid)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None
        sent = False
        if member:
            try:
                await member.send(
                    "🔁 **마뇽 감지기 추가 라이선스 재발급**\n\n"
                    f"새 두 번째 PC용 라이선스 키: `{key}`\n\n"
                    "이전 추가 키는 폐기되었고 추가 PC 등록도 초기화되었습니다. "
                    "기본 라이선스는 변경되지 않았습니다.\n**GORI GUILD**",
                    view=DownloadView(),
                )
                sent = True
            except discord.HTTPException:
                pass
        await i.response.send_message(
            "✅ 추가 라이선스 재발급 및 DM 전송 완료." if sent else
            f"⚠️ 추가 라이선스 재발급 완료, DM 전송 실패. 새 키를 안전하게 전달하세요: `{key}`",
            ephemeral=True,
        )
        await self.after_thread_action(i, uid, "🔁 추가 라이선스 재발급")

    async def thread_reset_extra_device(self, i, uid):
        async with self.pool.acquire() as c:
            result = await c.execute(
                "UPDATE manyong_extra_licenses SET device_hash=NULL,activated_at=NULL,updated_at=NOW() WHERE discord_id=$1", uid
            )
        await i.response.send_message(
            "♻️ 추가 라이선스 PC 등록을 초기화했습니다." if result != "UPDATE 0" else "❌ 추가 라이선스가 없습니다.",
            ephemeral=True
        )
        if result != "UPDATE 0":
            await self.after_thread_action(i, uid, "♻️ 추가 라이선스 기기초기화")

    async def thread_reissue(self, i, uid):
        r = await self.row(uid)
        if not r:
            await i.response.send_message("❌ 기록이 없습니다.", ephemeral=True); return
        key = new_key()
        async with self.pool.acquire() as c:
            await c.execute(
                "UPDATE manyong_licenses SET license_key_hash=$1,status='active',"
                "device_hash=NULL,activated_at=NULL,approved_at=NOW(),approved_by=$2,updated_at=NOW() "
                "WHERE discord_id=$3", key_hash(key), i.user.id, uid)
        member = i.guild.get_member(uid)
        sent = False
        if member:
            try:
                await member.send(
                    "🔄 **마뇽 감지기 라이선스 재발급**\n\n"
                    "새 라이선스 키\n"
                    f"`{key}`\n\n"
                    "기존 키는 더 이상 사용할 수 없습니다.\n"
                    "아래 버튼에서 감지기를 다운로드할 수 있습니다.\n\n"
                    "**GORI GUILD · MADE BY 이복애**",
                    view=DownloadView(),
                )
                sent = True
            except discord.Forbidden:
                pass
        await i.response.send_message(
            "🔄 재발급 완료. DM 전송 완료." if sent
            else f"🔄 재발급 완료. DM 실패 — 키: `{key}`",
            ephemeral=True)
        await self.after_thread_action(i, uid, "🔄 라이선스 재발급")

    async def issue(self, i, uid):
        r = await self.row(uid)
        if not r:
            await i.response.send_message("❌ 신청 기록이 없습니다.", ephemeral=True); return
        key = new_key()
        async with self.pool.acquire() as c:
            await c.execute("""UPDATE manyong_licenses SET license_key_hash=$1,status='active',
            device_hash=NULL,approved_at=NOW(),approved_by=$2,updated_at=NOW() WHERE discord_id=$3""",
            key_hash(key), i.user.id, uid)
        m = i.guild.get_member(uid)
        sent = False
        if m:
            try:
                await m.send(
                    "🐉 **마뇽 감지기 라이선스 승인**\n\n"
                    "라이선스 키\n"
                    f"`{key}`\n\n"
                    "아래 버튼에서 감지기를 다운로드할 수 있습니다.\n"
                    "라이선스는 최초 인증한 PC 1대에 등록됩니다.\n\n"
                    "**GORI GUILD · MADE BY 이복애**",
                    view=DownloadView(),
                )
                sent = True
            except discord.Forbidden: pass
        msg = f"✅ <@{uid}> 승인 완료."
        msg += " 키를 DM으로 전송했습니다." if sent else f" DM 실패 — 키: `{key}`"
        await i.response.send_message(msg, ephemeral=True)

    async def reject(self, i, uid):
        async with self.pool.acquire() as c:
            result = await c.execute("""UPDATE manyong_licenses SET status='rejected',
            license_key_hash=NULL,device_hash=NULL,updated_at=NOW() WHERE discord_id=$1""", uid)
        await i.response.send_message("❌ 신청 기록이 없습니다." if result=="UPDATE 0"
                                      else f"❌ <@{uid}> 신청을 거절했습니다.", ephemeral=True)

    @app_commands.command(name="마뇽인증_신청", description="마뇽 감지기 라이선스를 신청합니다.")
    @app_commands.guild_only()
    async def request(self, i):
        await self.submit_request(i)



    @app_commands.command(name="마뇽인증_신청버튼설치", description="감지기 라이선스 채널에 신청 버튼을 설치합니다.")
    @app_commands.guild_only()
    async def install_request_button(self, i):
        if not await admin_check(i):
            return

        if i.channel_id != LICENSE_REQUEST_CHANNEL_ID:
            await i.response.send_message(
                f"❌ 이 명령은 <#{LICENSE_REQUEST_CHANNEL_ID}> 채널에서 실행해 주세요.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🐉 마뇽 감지기 라이선스",
            description=(
                "마뇽 감지기 사용을 원하시면 아래 **라이선스 신청** 버튼을 눌러주세요.\n\n"
                "신청 후 운영진 승인이 완료되면 라이선스 키가 DM으로 발급됩니다."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(
            name="신청 안내",
            value=(
                "• 한 사람당 하나의 활성 라이선스를 사용할 수 있습니다.\n"
                "• 이미 신청했다면 중복 신청되지 않습니다.\n"
                "• 발급된 라이선스 키는 다른 사람에게 공유하지 마세요."
            ),
            inline=False,
        )

        await i.channel.send(embed=embed, view=LicenseRequestView(self))
        await i.response.send_message(
            "✅ 라이선스 신청 버튼을 이 채널에 설치했습니다.",
            ephemeral=True,
        )

    @app_commands.command(
        name="마뇽인증_삭제",
        description="사용자의 라이선스 기록을 완전히 삭제합니다.",
    )
    @app_commands.guild_only()
    async def delete_license(
        self,
        i: discord.Interaction,
        discord_id: str = "",
    ):
        if not await admin_check(i):
            return

        # 비워두면 명령 실행자 본인 대상으로 사용 가능 (테스트 편의)
        target_id = i.user.id
        if discord_id.strip():
            try:
                target_id = int(discord_id.strip())
            except ValueError:
                await i.response.send_message(
                    "❌ Discord ID는 숫자로 입력해 주세요.",
                    ephemeral=True,
                )
                return

        row = await self.row(target_id)
        if not row:
            await i.response.send_message(
                "ℹ️ 해당 Discord ID의 라이선스 기록이 없습니다.",
                ephemeral=True,
            )
            return

        await i.response.send_message(
            (
                f"⚠️ 정말 <@{target_id}>의 라이선스를 **완전히 삭제**할까요?\n\n"
                "• 기존 라이선스 키 폐기\n"
                "• 등록 PC 정보 삭제\n"
                "• 승인/차단 상태 삭제\n"
                "• 이후 새 라이선스 신청 가능\n\n"
                "**이 작업은 되돌릴 수 없습니다.**"
            ),
            view=DeleteLicenseConfirmView(self, target_id, i.user.id),
            ephemeral=True,
        )

    @app_commands.command(
        name="마뇽인증_신청초기화",
        description="삭제된 승인카드 등으로 막힌 대기 신청을 초기화합니다.",
    )
    @app_commands.guild_only()
    async def reset_pending_request(
        self,
        i: discord.Interaction,
        discord_id: str = "",
    ):
        if not await admin_check(i):
            return

        # ID를 비워두면 명령 실행자 본인의 신청을 초기화.
        # 사용자 선택 UI 문제를 피하기 위해 Discord ID 직접 입력도 지원.
        target_id = i.user.id
        if discord_id.strip():
            try:
                target_id = int(discord_id.strip())
            except ValueError:
                await i.response.send_message(
                    "❌ Discord ID는 숫자로 입력해 주세요.",
                    ephemeral=True,
                )
                return

        async with self.pool.acquire() as c:
            row = await c.fetchrow(
                "SELECT status FROM manyong_licenses WHERE discord_id=$1",
                target_id,
            )

            if not row:
                await i.response.send_message(
                    "ℹ️ 해당 Discord ID의 신청 기록이 없습니다.",
                    ephemeral=True,
                )
                return

            if row["status"] != "pending":
                await i.response.send_message(
                    f"ℹ️ 현재 상태는 `{row['status']}`입니다. "
                    "승인 대기(pending) 신청만 초기화할 수 있습니다.",
                    ephemeral=True,
                )
                return

            await c.execute(
                "DELETE FROM manyong_licenses "
                "WHERE discord_id=$1 AND status='pending'",
                target_id,
            )

        await i.response.send_message(
            f"♻️ <@{target_id}>의 승인 대기 신청을 초기화했습니다.\n"
            "이제 `감지기 라이선스` 채널의 **🔑 라이선스 신청** 버튼을 "
            "다시 누르면 새 승인/거절 카드가 생성됩니다.",
            ephemeral=True,
        )

    @app_commands.command(name="마뇽인증_목록", description="라이선스 목록을 확인합니다.")
    @app_commands.guild_only()
    async def list_cmd(self, i):
        if not await admin_check(i): return
        async with self.pool.acquire() as c:
            rows = await c.fetch("SELECT discord_id,status,device_hash FROM manyong_licenses ORDER BY requested_at DESC LIMIT 30")
        labels={"pending":"🟡 대기","active":"🟢 활성","blocked":"🔴 차단","rejected":"⚫ 거절"}
        text="\n".join(f"{labels.get(r['status'],r['status'])} · <@{r['discord_id']}> · 기기 {'등록' if r['device_hash'] else '미등록'}" for r in rows)
        await i.response.send_message(text or "등록된 라이선스가 없습니다.", ephemeral=True)

    @app_commands.command(name="마뇽인증_정보", description="사용자의 라이선스 정보를 확인합니다.")
    @app_commands.guild_only()
    async def info_cmd(self, i, 사용자: discord.Member):
        if not await admin_check(i): return
        r=await self.row(사용자.id)
        if not r:
            await i.response.send_message("등록 기록이 없습니다.", ephemeral=True); return
        await i.response.send_message(
            f"**{사용자.mention}**\n상태: `{r['status']}`\nPC: `{'등록됨' if r['device_hash'] else '미등록'}`\n승인일: `{r['approved_at'] or '-'}`",
            ephemeral=True)

    @app_commands.command(name="마뇽인증_승인", description="대기 중인 신청을 승인합니다.")
    @app_commands.guild_only()
    async def approve_cmd(self, i, 사용자: discord.Member):
        if await admin_check(i): await self.issue(i, 사용자.id)

    @app_commands.command(name="마뇽인증_거절", description="라이선스 신청을 거절합니다.")
    @app_commands.guild_only()
    async def reject_cmd(self, i, 사용자: discord.Member):
        if await admin_check(i): await self.reject(i, 사용자.id)

    @app_commands.command(name="마뇽인증_차단", description="라이선스를 즉시 차단합니다.")
    @app_commands.guild_only()
    async def block_cmd(self, i, 사용자: discord.Member):
        if not await admin_check(i): return
        async with self.pool.acquire() as c:
            r=await c.execute("UPDATE manyong_licenses SET status='blocked',updated_at=NOW() WHERE discord_id=$1",사용자.id)
        await i.response.send_message("등록 기록이 없습니다." if r=="UPDATE 0" else f"🔴 {사용자.mention} 차단 완료.",ephemeral=True)

    @app_commands.command(name="마뇽인증_차단해제", description="차단된 라이선스를 다시 활성화합니다.")
    @app_commands.guild_only()
    async def unblock_cmd(self, i, discord_id: str = ""):
        if not await admin_check(i):
            return

        if not discord_id.strip():
            await i.response.send_message(
                "❌ 차단을 해제할 사용자의 Discord ID를 숫자로 입력해 주세요.",
                ephemeral=True,
            )
            return

        try:
            target_id = int(discord_id.strip())
        except ValueError:
            await i.response.send_message(
                "❌ Discord ID는 숫자로 입력해 주세요.",
                ephemeral=True,
            )
            return

        async with self.pool.acquire() as c:
            row = await c.fetchrow(
                "SELECT status, license_key_hash, device_hash "
                "FROM manyong_licenses WHERE discord_id=$1",
                target_id,
            )

            if not row:
                await i.response.send_message(
                    "❌ 해당 Discord ID의 라이선스 기록이 없습니다.",
                    ephemeral=True,
                )
                return

            if row["status"] != "blocked":
                await i.response.send_message(
                    f"ℹ️ 현재 상태는 `{row['status']}`입니다. 차단된 라이선스만 해제할 수 있습니다.",
                    ephemeral=True,
                )
                return

            if not row["license_key_hash"]:
                await i.response.send_message(
                    "❌ 기존 라이선스 키 정보가 없어 차단해제할 수 없습니다. 재발급을 사용해 주세요.",
                    ephemeral=True,
                )
                return

            await c.execute(
                "UPDATE manyong_licenses "
                "SET status='active', updated_at=NOW() "
                "WHERE discord_id=$1",
                target_id,
            )

        await i.response.send_message(
            f"🟢 <@{target_id}>의 라이선스 차단을 해제했습니다.\n"
            "기존 라이선스 키와 등록 PC 정보는 그대로 유지됩니다.",
            ephemeral=True,
        )

    @app_commands.command(name="마뇽인증_기기초기화", description="등록 PC 정보를 초기화합니다.")
    @app_commands.guild_only()
    async def reset_cmd(self, i, 사용자: discord.Member):
        if not await admin_check(i): return
        async with self.pool.acquire() as c:
            r=await c.execute("UPDATE manyong_licenses SET device_hash=NULL,activated_at=NULL,updated_at=NOW() WHERE discord_id=$1",사용자.id)
        await i.response.send_message("등록 기록이 없습니다." if r=="UPDATE 0" else f"♻️ {사용자.mention} 기기 초기화 완료.",ephemeral=True)

    @app_commands.command(name="마뇽인증_재발급", description="새 라이선스 키를 발급합니다.")
    @app_commands.guild_only()
    async def reissue_cmd(self, i, 사용자: discord.Member):
        if not await admin_check(i): return
        if not await self.row(사용자.id):
            await i.response.send_message("등록 기록이 없습니다.",ephemeral=True); return
        key=new_key()
        async with self.pool.acquire() as c:
            await c.execute("""UPDATE manyong_licenses SET license_key_hash=$1,status='active',
            device_hash=NULL,activated_at=NULL,updated_at=NOW() WHERE discord_id=$2""",key_hash(key),사용자.id)
        try:
            await 사용자.send(
                "🔄 **마뇽 감지기 라이선스 재발급**\n\n"
                "새 라이선스 키\n"
                f"`{key}`\n\n"
                "기존 키는 더 이상 사용할 수 없습니다.\n"
                "아래 버튼에서 감지기를 다운로드할 수 있습니다.\n\n"
                "**GORI GUILD · MADE BY 이복애**",
                view=DownloadView(),
            )
            msg=f"🔄 {사용자.mention} 재발급 완료. DM 전송 완료."
        except discord.Forbidden:
            msg=f"🔄 재발급 완료. DM 실패 — 키: `{key}`"
        await i.response.send_message(msg,ephemeral=True)

async def setup(bot):
    await bot.add_cog(ManyongLicense(bot))
