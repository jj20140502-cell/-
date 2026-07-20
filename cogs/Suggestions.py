import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
from datetime import datetime, timedelta, timezone

# ================= [ ⚙️ 건의접수함 채널 ID 설정 ] =================
# 새로 개설하신 건의접수함 안내 및 스레드가 생성될 메인 채널 ID입니다.
SUGGESTION_CHANNEL_ID = 1528666581616431219  
# =========================================================

class SuggestionSubmitModal(Modal, title="건의사항 작성"):
    title_input = TextInput(label="건의 제목", placeholder="예: 길드 레이드 시간 변경 건", max_length=50, required=True)
    content_input = TextInput(label="건의 내용", style=discord.TextStyle.paragraph, placeholder="상세한 건의 내용을 적어주세요.", min_length=10, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        suggestion_channel = guild.get_channel(SUGGESTION_CHANNEL_ID)

        if not suggestion_channel:
            await interaction.followup.send("❌ 건의 접수 채널을 찾을 수 없습니다. 관리자에게 문의하세요.", ephemeral=True)
            return

        # 1. 건의 채널에 베이스 알림 메시지 전송 후 비공개 스레드(티켓) 생성
        kst_time = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M')
        thread_name = f"💡-{interaction.user.display_name}님의-건의"
        
        base_msg = await suggestion_channel.send(f"👤 {interaction.user.mention}님의 새로운 건의가 접수되어 비밀 채널을 생성합니다.")
        
        # 디스코드 내부 제약 및 보안을 위해 1:1 비공개 형태의 스레드로 생성
        thread = await base_msg.create_thread(name=thread_name, auto_archive_duration=1440)

        # 2. 건의 내용 임베드화
        embed = discord.Embed(
            title=f"📋 건의 내용: {self.title_input.value}",
            description=self.content_input.value,
            color=discord.Color.yellow()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"접수 일시: {kst_time} | 유저 ID: {interaction.user.id}")

        # 3. 티켓 내부 전용 컨트롤 뷰 (종료 버튼) 생성 및 세팅
        ticket_view = TicketControlView(user_id=interaction.user.id)
        
        # 스레드에 신청 유저 초대 및 내부 안내문 전송
        await thread.add_user(interaction.user)
        await thread.send(
            content=f"🔔 {interaction.user.mention}님, 건의 접수용 전용 채널이 생성되었습니다.\n운영진이 확인 후 이곳에서 답변을 드릴 예정입니다. 소통이 모두 끝나면 아래 **[🔒 티켓 종료]** 버튼을 눌러주세요.",
            embed=embed,
            view=ticket_view
        )

        await interaction.followup.send(f"✅ 건의가 성공적으로 접수되었습니다! 생성된 채널로 이동하여 확인해 주세요: {thread.mention}", ephemeral=True)


class TicketControlView(View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="🔒 티켓 종료 (채널 잠금)", style=discord.ButtonStyle.red, custom_id="ticket_close_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        # 운영진 권한(스레드 관리 권한)이 있거나, 해당 티켓을 직접 개설한 유저인 경우에만 종료 가능
        if interaction.user.id == self.user_id or interaction.user.guild_permissions.manage_threads:
            await interaction.response.send_message("🔒 이 건의 채널 상담을 종료하고 잠금(아카이브) 처리합니다.")
            
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)

            if isinstance(interaction.channel, discord.Thread):
                await interaction.channel.edit(locked=True, archived=True)
        else:
            await interaction.response.send_message("❌ 이 티켓을 종료할 권한이 없습니다.", ephemeral=True)


class MainSuggestionView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💡 건의하기", style=discord.ButtonStyle.primary, custom_id="main_suggestion_btn")
    async def start_suggestion(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(SuggestionSubmitModal())


class Suggestions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        # 봇이 재부팅되어도 버튼이 상시 작동하도록 영구 뷰(Persistent View)로 등록
        self.bot.add_view(MainSuggestionView())
        print("🤖 건의접수 시스템(Suggestions Cog) 로드 및 상시 버튼 대기 완료!")

    @commands.command(name="건의설정")
    @commands.has_permissions(administrator=True)
    async def setup_suggestion(self, ctx):
        """건의 채널에서 관리자가 최초 1회만 실행하는 초기화 명령어"""
        await ctx.channel.purge(limit=10)
        
        embed = discord.Embed(
            title="📥 길드 건의접수함 운영 안내",
            description=(
                "안녕하세요! 길드원 여러분의 소중한 의견을 수렴하는 공간입니다.\n\n"
                "길드 발전을 위한 아이디어, 불편사항, 문의 등이 있으시다면\n"
                "아래 **[💡 건의하기]** 버튼을 눌러 내용을 작성해 주세요.\n\n"
                "버튼을 누르면 **운영진과 건의자만 볼 수 있는 1:1 비밀 스레드 채널**이 자동으로 생성됩니다."
            ),
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed, view=MainSuggestionView())
        await ctx.message.delete()

async def setup(bot):
    await bot.add_cog(Suggestions(bot))
