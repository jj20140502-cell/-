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
class AdminApprovalView(View):
    def __init__(self, user_id: int, user_nickname: str, embed_data: discord.Embed):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.user_nickname = user_nickname
        self.embed_data = embed_data  # 로그 채널 복사용 원본 임베드 저장

    async def transfer_to_log(self, guild: discord.Guild, status_text: str, color: discord.Color):
        """최종 결과를 🔒｜가입인증-로그 채널로 복사 전송하는 함수"""
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
        
        # 역할 객체 가져오기
        guild_role = guild.get_role(ROLE_ID)        # 정식길드원 역할
        guest_role = guild.get_role(GUEST_ROLE_ID)  # 손님 역할

        if not member:
            await interaction.response.send_message("❌ 서버에 해당 유저가 존재하지 않습니다. (탈퇴했을 수 있음)", ephemeral=True)
            return

        # 정식 역할 부여 및 손님 역할 제거
        if guild_role:
            await member.add_roles(guild_role)      # 정식길드원 추가
        
        if guest_role and guest_role in member.roles:
            await member.remove_roles(guest_role)  # 기존에 손님 역할이 있다면 제거
            role_status = f"✅ `{self.user_nickname}`님께 정식길드원 역할을 부여하고, 손님 역할을 제거했습니다!"
        else:
            role_status = f"✅ `{self.user_nickname}`님 가입 승인 및 정식길드원 역할 부여 완료!"

        await interaction.response.send_message(role_status, ephemeral=True)
        
        # 버튼 비활성화 및 승인대기방 메시지 업데이트
        for child in self.children:
            child.disabled = True
        result_msg = f"🔔 **[승인 완료]** 운영진 {interaction.user.mention}님이 가입을 승인했습니다."
        await interaction.message.edit(content=result_msg, view=self)
        
        # 🔒｜가입인증-로그 채널로 최종 데이터 아카이브 전송
        await self.transfer_to_log(guild, f"승인 완료 (담당: {interaction.user.name})", discord.Color.green())
        
        # 승인대기방 스레드 잠금 및 보관
        if isinstance(interaction.channel, discord.Thread):
            await interaction.channel.edit(locked=True, archived=True)

    @discord.ui.button(label="❌ 거절 (추방)", style=discord.ButtonStyle.red, custom_id="admin_deny")
    async def deny(self, interaction: discord.Interaction, button: Button):
        guild = interaction.guild
        member = guild.get_member(self.user_id)

        if not member:
            await interaction.response.send_message("❌ 서버에 해당 유저가 존재하지 않습니다.", ephemeral=True)
            return

        # 유저 추방(Kick) 처리
        try:
            await member.kick(reason=f"가입인증 거절 (담당 운영진: {interaction.user.name})")
            kick_status = f"🚫 신청자 `{self.user_nickname}`님을 서버에서 추방했습니다."
        except discord.Forbidden:
            kick_status = "⚠️ (봇의 권한 부족으로 추방 실패. 봇 서열을 올려주세요.)"

        await interaction.response.send_message(f"거절 처리 완료: {kick_status}", ephemeral=True)
        
        # 버튼 비활성화 및 승인대기방 메시지 업데이트
        for child in self.children:
            child.disabled = True
        result_msg = f"🔕 **[가입 거절]** 운영진 {interaction.user.mention}님이 가입을 거절하고 유저를 추방했습니다."
        await interaction.message.edit(content=result_msg, view=self)
        
        # 🔒｜가입인증-로그 채널로 최종 데이터 아카이브 전송
        await self.transfer_to_log(guild, f"거절 및 추방 (담당: {interaction.user.name})", discord.Color.red())
        
        # 승인대기방 스레드 잠금 및 보관
        if isinstance(interaction.channel, discord.Thread):
            await interaction.channel.edit(locked=True, archived=True)


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
        
        admin_view = AdminApprovalView(user_id=interaction.user.id, user_nickname=self.nickname, embed_data=embed)
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

# ⚠️ 본인의 디스코드 봇 토큰 입력
import os
token = os.getenv("DISCORD_TOKEN")
bot.run(token)