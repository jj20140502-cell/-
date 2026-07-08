import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput

# 봇 권한(Intents) 설정
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # 유저 별명 변경, 역할 부여, 추방을 위해 필수

bot = commands.Bot(command_prefix="!", intents=intents)

# ================= [ ⚙️ 완벽 반영된 서버/채널/역할 ID 설정 ] =================
# 1. 역할 ID 설정
ROLE_ID = 1520725763488223343         # 승인 시 지급할 '정식길드원' 역할 ID
GUEST_ROLE_ID = 1520650434346352892   # 승인 시 회수할 '손님' 역할 ID

# 2. 채널 ID 설정
APPROVAL_CHANNEL_ID = 1520940070679478313  # 2. 🔒｜인증-승인대기 채널 ID
LOG_CHANNEL_ID = 1520940386111983837       # 3. 🔒｜가입인증-로그 채널 ID
# =========================================================================


# [STEP 4] 운영진 승인/거절 버튼 View
class HoldReasonModal(Modal, title="보류 및 수정 요청 사유"):
    reason_input = TextInput(label="수정 요청 사유", style=discord.TextStyle.paragraph, required=True)

    def __init__(self, user_id, user_nickname, original_interaction):
        super().__init__()
        self.user_id = user_id
        self.user_nickname = user_nickname
        self.original_interaction = original_interaction

    async def on_submit(self, interaction: discord.Interaction):
        hold_embed = discord.Embed(
            title="⚠️ 가입 신청 보류",
            description=f"운영진의 요청을 확인 후 다시 진행해 주세요.\n\n**사유:** {self.reason_input.value}",
            color=discord.Color.red()
        )
        await self.original_interaction.edit_original_response(
            embed=hold_embed, 
            view=ScreenshotUploadView(self.user_nickname, "재신청자")
        )
        await interaction.response.send_message("✅ 유저 화면에 보류 알림을 띄웠습니다.", ephemeral=True)
class AdminApprovalView(View):
    def __init__(self, user_id: int, user_nickname: str, embed_data: discord.Embed, original_interaction: discord.Interaction):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.user_nickname = user_nickname
        self.embed_data = embed_data
        self.original_interaction = original_interaction  # 1단계 수정: 저장

    async def transfer_to_log(self, guild: discord.Guild, status_text: str, color: discord.Color):
        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            log_embed = self.embed_data.copy()
            log_embed.color = color
            log_embed.title = f"📁 가입인증 기록 ({status_text})"
            log_embed.add_field(name="처리 상태", value=status_text, inline=False)
            await log_channel.send(embed=log_embed)

    @discord.ui.button(label="⭕ 승인", style=discord.ButtonStyle.green, custom_id="admin_approve")
    async def approve(self, interaction: discord.Interaction, button: Button):
        guild = interaction.guild
        member = guild.get_member(self.user_id)
        guild_role = guild.get_role(ROLE_ID)
        guest_role = guild.get_role(GUEST_ROLE_ID)
        if not member:
            await interaction.response.send_message("❌ 서버에 해당 유저가 존재하지 않습니다.", ephemeral=True)
            return
        if guild_role: await member.add_roles(guild_role)
        if guest_role and guest_role in member.roles:
            await member.remove_roles(guest_role)
            role_status = f"✅ `{self.user_nickname}`님께 정식길드원 역할을 부여하고, 손님 역할을 제거했습니다!"
        else: role_status = f"✅ `{self.user_nickname}`님 가입 승인 및 정식길드원 역할 부여 완료!"
        await interaction.response.send_message(role_status, ephemeral=True)
        for child in self.children: child.disabled = True
        await interaction.message.edit(content=f"🔔 **[승인 완료]** 운영진 {interaction.user.mention}님이 승인했습니다.", view=self)
        await self.transfer_to_log(guild, f"승인 완료 (담당: {interaction.user.name})", discord.Color.green())
        if isinstance(interaction.channel, discord.Thread): await interaction.channel.edit(locked=True, archived=True)

    @discord.ui.button(label="🟡 보류(수정요청)", style=discord.ButtonStyle.secondary, custom_id="admin_hold")
    async def hold(self, interaction: discord.Interaction, button: Button):
        # 1단계 수정: 모달 호출 시 original_interaction 전달
        await interaction.response.send_modal(HoldReasonModal(self.user_id, self.user_nickname, self.original_interaction))

    @discord.ui.button(label="❌ 거절 (추방)", style=discord.ButtonStyle.red, custom_id="admin_deny")
    async def deny(self, interaction: discord.Interaction, button: Button):
        guild = interaction.guild
        member = guild.get_member(self.user_id)
        if not member:
            await interaction.response.send_message("❌ 서버에 해당 유저가 존재하지 않습니다.", ephemeral=True)
            return
        try:
            await member.kick(reason=f"가입인증 거절 (담당: {interaction.user.name})")
            kick_status = f"🚫 신청자 `{self.user_nickname}`님을 서버에서 추방했습니다."
        except discord.Forbidden:
            kick_status = "⚠️ (봇의 권한 부족으로 추방 실패.)"
        await interaction.response.send_message(f"거절 처리 완료: {kick_status}", ephemeral=True)
        for child in self.children: child.disabled = True
        await interaction.message.edit(content=f"🔕 **[가입 거절]** 운영진 {interaction.user.mention}님이 거절했습니다.", view=self)
        await self.transfer_to_log(guild, f"거절 및 추방 (담당: {interaction.user.name})", discord.Color.red())
        if isinstance(interaction.channel, discord.Thread): await interaction.channel.edit(locked=True, archived=True)


# [STEP 3] 스크린샷 업로드 대기 및 완료 버튼 View
class ScreenshotUploadView(View):
    def __init__(self, nickname: str, job: str):
        super().__init__(timeout=600)  # 10분 제한
        self.nickname = nickname
        self.job = job

    @discord.ui.button(label="📸 스샷 첨부완료", style=discord.ButtonStyle.blurple)
    async def screenshot_done(self, interaction: discord.Interaction, button: Button):
        approval_channel = interaction.guild.get_channel(APPROVAL_CHANNEL_ID)
        if not approval_channel:
            await interaction.response.send_message("승인 대기 채널을 찾을 수 없습니다. 관리자에게 문의하세요.", ephemeral=True)
            return

        target_attachment = None
        user_image_message = None

        # 현재 채널의 최근 메시지 10개 중 해당 유저가 올린 스크린샷 찾기
        async for message in interaction.channel.history(limit=10):
            if message.author.id == interaction.user.id and message.attachments:
                target_attachment = message.attachments[0] # 이미지 파일 객체 자체를 타겟팅
                user_image_message = message
                break

        if not target_attachment:
            await interaction.response.send_message("⚠️ 인식된 이미지가 없습니다. 먼저 안내에 맞게 스크린샷을 업로드(전송)한 후 버튼을 눌러주세요!", ephemeral=True)
            return

        # 1. 🌟 [해결책] 디스코드 파일 객체로 변환 (원본이 지워져도 안전하게 보관됨)
        try:
            image_file = await target_attachment.to_file()
        except Exception as e:
            await interaction.response.send_message("⚠️ 이미지 파일을 처리하는 중 오류가 발생했습니다. 다시 시도해 주세요.", ephemeral=True)
            return

        # 2. 유저가 채널에 직접 올린 일반 사진 메시지는 즉시 삭제 (채널 청소)
        try:
            await user_image_message.delete()
        except:
            pass

        # 3. [🔒｜인증-승인대기 채널] 양식 생성 및 파일 첨부하여 전송
        embed = discord.Embed(title="📝 새로운 가입 신청서", color=discord.Color.orange())
        embed.add_field(name="신청자", value=interaction.user.mention, inline=True)
        embed.add_field(name="변경 닉네임", value=f"{self.nickname} ({self.job})", inline=True)
        
        # 🌟 첨부되는 파일명을 임베드 이미지로 연동하는 방식 (주소 만료 걱정 없음)
        embed.set_image(url=f"attachment://{image_file.filename}")

        # 승인대기 채널에 베이스 메시지와 함께 파일 전송 후 하위 스레드 개설
        thread_message = await approval_channel.send(embed=embed, file=image_file)
        thread = await thread_message.create_thread(
            name=f"📄 {self.nickname}님의 가입인증 요청",
            auto_archive_duration=60
        )
        
        admin_view = AdminApprovalView(
            user_id=interaction.user.id, 
            user_nickname=self.nickname, 
            embed_data=embed,
            original_interaction=interaction  # 이 인자를 추가했습니다
        )
        await thread.send(content="📋 운영진 확인용 메뉴입니다. 하단 스크린샷 내 문구 존재 여부와 닉네임을 확인 후 처리해주세요.", view=admin_view)

        # 4. 유저 화면의 비밀 메시지 창을 '접수 완료' 상태로 변경
        success_embed = discord.Embed(
            title="🎉 접수 완료",
            description="가입 신청서 접수가 최종 완료되었습니다!\n운영진이 스크린샷 확인 후 승인해 드릴 예정이니 잠시만 기다려주세요.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=success_embed, view=None)

# [STEP 2] 닉네임/직업 입력 모달 창
class UserInfoModal(Modal, title="가입 정보 입력"):
    nickname_input = TextInput(label="인게임 닉네임", placeholder="예: 홍길동", max_length=20, required=True)
    job_input = TextInput(label="인게임 직업/클래스", placeholder="예: 전사", max_length=20, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        nickname = self.nickname_input.value
        job = self.job_input.value
        new_nickname = f"{nickname}/{job}"

        # 1. 즉시 유저의 서버 별명(Nickname) 변경
        try:
            await interaction.user.edit(nick=new_nickname)
            nick_success = f"디스코드 별명이 `{new_nickname}`으로 자동 변경되었습니다."
        except discord.Forbidden:
            nick_success = "⚠️ (봇의 권한 부족으로 서버 별명을 변경하지 못했습니다.)"

        # 2. 인게임 스샷 제출 조건 상세 안내
        embed = discord.Embed(
            title="📸 인게임 전체 스크린샷 제출 필수 안내",
            description=(
                f"{nick_success}\n\n"
                "**⚠️ 다음 지시사항을 반드시 지켜서 스크린샷을 올려주세요!**\n\n"
                "1. 게임에 접속하여 인게임 채팅창에 **\"고리 가입요청\"** 이라고 타이핑 후 전송합니다.\n"
                "2. 해당 채팅 내용이 명확하게 화면에 포함된 **[게임 전체 스크린샷]**을 촬영합니다.\n"
                "3. 촬영한 스크린샷 파일을 바로 이 채팅창에 업로드(전송)해 주세요.\n"
                "4. 업로드가 완료되면 아래의 **[📸 스샷 첨부완료]** 버튼을 눌러주셔야 최종 접수됩니다."
            ),
            color=discord.Color.blurple()
        )
        
        view = ScreenshotUploadView(nickname=nickname, job=job)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# [STEP 1] 메인 고정 메시지용 뷰
class MainVerificationView(View):
    def __init__(self):
        super().__init__(timeout=None)  # 영구 작동 버튼

    @discord.ui.button(label="📝 가입 인증하기", style=discord.ButtonStyle.green, custom_id="main_verify_btn")
    async def start_verification(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(UserInfoModal())


@bot.event
async def on_ready():
    print(f'🤖 가입인증 시스템 가동: {bot.user.name}')
    bot.add_view(MainVerificationView())
    bot.add_view(InvestUploadView())


# 🌟 📝｜가입신청서 채널에서 관리자가 최초 1회만 실행하는 명령어
@bot.command(name="최초설정")
@commands.has_permissions(administrator=True)
async def setup_verification(ctx):
    # 채널 깔끔하게 청소
    await ctx.channel.purge(limit=100)
    
    embed = discord.Embed(
        title="🛡️ 길드 가입인증 절차",
        description=(
            "안녕하세요! 우리 서버에 오신 것을 환영합니다.\n\n"
            "아래 **[📝 가입 인증하기]** 버튼을 눌러 정보를 입력하신 뒤,\n"
            "안내에 따라 인게임 인증 스크린샷을 제출해 주세요.\n"
            "운영진이 확인 후 정식 길드원 권한을 부여해 드립니다."
        ),
        color=discord.Color.green()
    )
    await ctx.send(embed=embed, view=MainVerificationView())
    await ctx.message.delete()  # 명령어 메시지 삭제

# [투자 기록용 코드]
# ================= [ ⚙️ 투자 기록용 ID 설정 ] =================
INVEST_CHANNEL_ID = 1524039894316617778  # 📷｜투자 인증
INVEST_LOG_CHANNEL_ID = 1522243952764387389  # 🔒｜길드-투자기록
# =========================================================

class InvestUploadView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📸 투자 인증 완료", style=discord.ButtonStyle.blurple, custom_id="invest_upload_btn")
    async def invest_done(self, interaction: discord.Interaction, button: Button):
        # 1. 메시지 및 파일 확인
        target_attachment = None
        user_image_message = None
        async for message in interaction.channel.history(limit=5):
            if message.author.id == interaction.user.id and message.attachments:
                target_attachment = message.attachments[0]
                user_image_message = message
                break
        
        if not target_attachment:
            await interaction.response.send_message("⚠️ 업로드된 스크린샷을 찾을 수 없습니다.", ephemeral=True)
            return

        # 2. 🔒｜길드-투자기록 채널에서 기존 스레드 검색 (보관된 스레드 포함)
        log_channel = interaction.guild.get_channel(INVEST_LOG_CHANNEL_ID)
        thread_name = f"{interaction.user.display_name}님의 투자인증"
        
        target_thread = None
        # 수정: 모든 스레드(보관된 것 포함)를 순회하며 찾기
        async for thread in log_channel.archived_threads(limit=100):
            if thread.name == thread_name:
                target_thread = thread
                break
        if not target_thread:
            for thread in log_channel.threads:
                if thread.name == thread_name:
                    target_thread = thread
                    break
        
        # 3. 스레드가 없으면 새로 생성, 있으면 아카이브 해제
        if not target_thread:
            msg = await log_channel.send(f"{interaction.user.mention}님의 투자 인증")
            target_thread = await msg.create_thread(name=thread_name, auto_archive_duration=1440)
            await msg.delete()
        else:
            if target_thread.archived:
                await target_thread.edit(archived=False)
        
        # 4. 사진 전송 및 원본 삭제
        await target_thread.send(f"👤 {interaction.user.mention}님의 인증 (일시: {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M')})", file=await target_attachment.to_file())
        try:
            await user_image_message.delete()
        except:
            pass
        
        await interaction.response.send_message("✅ 투자 기록이 기존 스레드에 저장되었습니다!", ephemeral=True)
@bot.command(name="투자설정")
@commands.has_permissions(administrator=True)
async def setup_invest(ctx):
    embed = discord.Embed(
        title="스킬 투자 인증",
        description="인증 사진을 업로드한 후 아래 버튼을 눌러주세요. 개인 스레드에 기록이 누적됩니다.",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=InvestUploadView())

# ================= [ 코드 끝 부분 ] =================
# ⚠️ 본인의 디스코드 봇 토큰 입력
import os
token = os.getenv("DISCORD_TOKEN")
bot.run(token)
