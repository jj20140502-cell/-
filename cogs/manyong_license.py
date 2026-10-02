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

    async def row(self, uid):
        async with self.pool.acquire() as c:
            return await c.fetchrow("SELECT * FROM manyong_licenses WHERE discord_id=$1", uid)

    async def submit_request(self, i):
        """버튼/명령 공통 라이선스 신청 처리."""
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
            await c.execute("""INSERT INTO manyong_licenses(discord_id,discord_name,status,requested_at,updated_at)
            VALUES($1,$2,'pending',NOW(),NOW()) ON CONFLICT(discord_id) DO UPDATE SET
            discord_name=$2,status='pending',requested_at=NOW(),updated_at=NOW()""", i.user.id, str(i.user))

        ch = i.guild.get_channel(LICENSE_CHANNEL_ID) if LICENSE_CHANNEL_ID else None
        if not ch:
            await i.response.send_message("⚠️ 승인 채널이 아직 설정되지 않았습니다.", ephemeral=True)
            return

        e = discord.Embed(
            title="🐉 마뇽 감지기 라이선스 신청",
            description="새 라이선스 신청이 접수되었습니다.",
            color=discord.Color.blurple(),
        )
        e.add_field(name="신청자", value=i.user.mention, inline=False)
        e.add_field(name="Discord ID", value=str(i.user.id), inline=False)
        await ch.send(embed=e, view=ApprovalView(self, i.user.id))
        await i.response.send_message(
            "✅ 라이선스 신청이 접수되었습니다. 운영진 승인을 기다려 주세요.",
            ephemeral=True,
        )

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
                await m.send(f"🐉 **마뇽 감지기 라이선스 승인**\n라이선스 키: `{key}`\n다른 사람에게 공유하지 마세요.")
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
            await 사용자.send(f"🐉 새 마뇽 감지기 라이선스 키: `{key}`")
            msg=f"🔄 {사용자.mention} 재발급 완료. DM 전송 완료."
        except discord.Forbidden:
            msg=f"🔄 재발급 완료. DM 실패 — 키: `{key}`"
        await i.response.send_message(msg,ephemeral=True)

async def setup(bot):
    await bot.add_cog(ManyongLicense(bot))
