import random
import discord
from discord.ext import commands
from discord import app_commands


# ==============================
# 설정
# ==============================

LEAVE_LOG_CHANNEL_ID = 1520647014709329940


# ZIP 내 상시 패널의 고정 custom_id. 임시 게임 버튼은 포함하지 않습니다.
PERMANENT_PANEL_CUSTOM_IDS = frozenset({
    "boss_panel_kill_btn",
    "calculator:distribute:sale", "calculator:distribute:received",
    "calculator:exp:detail", "calculator:cash:open",
    "games:bomb:v1", "games:duck:v1", "games:raid:v1",
    "manyong_license_request_v1", "main_suggestion_btn",
    "ticket_close_btn", "main_verify_btn", "invest_upload_btn",
    "admin_approve", "admin_hold", "admin_deny",
})


def is_protected_panel(message, bot_user_id):
    """고정 메시지와 이 봇의 상시 패널을 재시작 후에도 보호합니다."""
    if message.pinned:
        return True
    if message.author.id != bot_user_id:
        return False

    def is_panel_component(component):
        custom_id = getattr(component, "custom_id", None)
        if custom_id in PERMANENT_PANEL_CUSTOM_IDS:
            return True
        if isinstance(custom_id, str) and custom_id.startswith("manyong_thread_"):
            return True
        # DownloadView는 custom_id 없는 링크 버튼입니다.
        url = getattr(component, "url", None)
        if isinstance(url, str) and url.startswith(
            "https://github.com/jj20140502-cell/-/releases/download/"
        ) and url.endswith("/ManyongDetector.exe"):
            return True
        return any(is_panel_component(child) for child in getattr(component, "children", ()))

    return any(is_panel_component(component) for component in message.components)


# ==============================
# 상식퀴즈 문제
# ==============================
import json
from pathlib import Path

QUIZ_FILE = Path(__file__).parent / "jara_quiz.json"

with open(QUIZ_FILE, "r", encoding="utf-8") as f:
    QUIZ_DATA = json.load(f)

QUIZ_LIST = QUIZ_DATA["상식퀴즈"]

# ==============================
# 가위바위보 버튼
# ==============================

class RPSView(discord.ui.View):
    def __init__(self, starter):
        super().__init__(timeout=60)

        self.starter = starter
        self.players = {}

    async def choose(self, interaction: discord.Interaction, choice: str):

        # 이미 참여한 사람
        if interaction.user.id in self.players:
            await interaction.response.send_message(
                "이미 선택하셨습니다.",
                ephemeral=True
            )
            return

        # 게임 시작자는 반드시 참여
        # 첫 번째 사람이 선택한 뒤 다른 사람이 참여 가능
        self.players[interaction.user.id] = {
            "member": interaction.user,
            "choice": choice
        }

        await interaction.response.send_message(
            f"{choice} 선택 완료!",
            ephemeral=True
        )

        # 두 명이 선택하면 결과
        if len(self.players) >= 2:
            await self.finish_game(interaction)

    async def finish_game(self, interaction):

        self.stop()

        players = list(self.players.values())

        player1 = players[0]
        player2 = players[1]

        choice1 = player1["choice"]
        choice2 = player2["choice"]

        winner = None

        if choice1 == choice2:
            result = "무승부입니다."
        elif (
            (choice1 == "가위" and choice2 == "보") or
            (choice1 == "바위" and choice2 == "가위") or
            (choice1 == "보" and choice2 == "바위")
        ):
            winner = player1["member"]
            result = f"{winner.mention} 승리!"
        else:
            winner = player2["member"]
            result = f"{winner.mention} 승리!"

        for item in self.children:
            item.disabled = True

        await interaction.message.edit(view=self)

        await interaction.channel.send(
            f"가위바위보 결과\n\n"
            f"{player1['member'].mention} → {choice1}\n"
            f"{player2['member'].mention} → {choice2}\n\n"
            f"{result}"
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class RPSButton(discord.ui.Button):
    def __init__(self, label, emoji, choice, view):
        super().__init__(
            label=label,
            emoji=emoji,
            style=discord.ButtonStyle.primary
        )

        self.choice = choice
        self.rps_view = view

    async def callback(self, interaction: discord.Interaction):
        await self.rps_view.choose(interaction, self.choice)


# ==============================
# Jara Cog
# ==============================

class Jara(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # 채널별 진행 중인 상식퀴즈
        self.active_quizzes = {}

    # ==============================
    # /purge all
    # ==============================

    @app_commands.command(
        name="purge",
        description="상시 패널과 고정 메시지를 제외하고 현재 채널의 메시지를 삭제합니다."
    )
    @app_commands.describe(action="실행할 작업")
    @app_commands.choices(
        action=[
            app_commands.Choice(
                name="all",
                value="all"
            )
        ]
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str]
    ):

        if action.value != "all":
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "이 채널에서는 사용할 수 없습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        # check는 Discord에서 가져온 메시지의 실제 컴포넌트를 검사합니다.
        # 실행 중 새로 올라오는 메시지는 이번 삭제 범위에 포함하지 않습니다.
        deleted = await interaction.channel.purge(
            limit=None,
            before=interaction.created_at,
            check=lambda message: not is_protected_panel(message, self.bot.user.id),
        )

        await interaction.followup.send(
            f"메시지 {len(deleted)}개를 삭제했습니다. 상시 패널과 고정 메시지는 보존했습니다.",
            ephemeral=True
        )

    @purge.error
    async def purge_error(
        self,
        interaction: discord.Interaction,
        error
    ):

        if isinstance(error, app_commands.errors.MissingPermissions):
            await interaction.response.send_message(
                "메시지 관리 권한이 필요합니다.",
                ephemeral=True
            )
        else:
            print(f"purge 오류: {error}")

            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "명령어 실행 중 오류가 발생했습니다.",
                    ephemeral=True
                )

    # ==============================
    # 서버 퇴장 로그
    # ==============================

    @commands.Cog.listener()
    async def on_member_remove(self, member):

        channel = self.bot.get_channel(LEAVE_LOG_CHANNEL_ID)

        if channel is None:
            print("퇴장 로그 채널을 찾을 수 없습니다.")
            return

        nickname = member.nick if member.nick else "없음"

        embed = discord.Embed(
            title="서버 퇴장",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(
            name="서버 별명",
            value=nickname,
            inline=True
        )

        embed.add_field(
            name="사용자명",
            value=member.name,
            inline=True
        )

        embed.add_field(
            name="사용자 ID",
            value=str(member.id),
            inline=False
        )

        if member.display_avatar:
            embed.set_thumbnail(
                url=member.display_avatar.url
            )

        await channel.send(embed=embed)

    # ==============================
    # 일반 채팅 감지
    # ==============================

    @commands.Cog.listener()
    async def on_message(self, message):

        # 봇 메시지는 무시
        if message.author.bot:
            return

        content = message.content.strip()

        # ------------------------------
        # 상식퀴즈
        # ------------------------------

        if content == "상식퀴즈":

            channel_id = message.channel.id

            # 이미 진행 중이면 새로 시작하지 않음
            if channel_id in self.active_quizzes:
                return

            quiz = random.choice(QUIZ_LIST)

            self.active_quizzes[channel_id] = quiz

            await message.channel.send(
                f"상식퀴즈\n\n"
                f"{quiz['question']}\n\n"
                f"정답을 채팅으로 입력해주세요."
            )

            return

        # ------------------------------
        # 상식퀴즈 정답 확인
        # ------------------------------

        channel_id = message.channel.id

        if channel_id in self.active_quizzes:

            quiz = self.active_quizzes[channel_id]

            user_answer = content.replace(" ", "").lower()
            correct_answer = (
                quiz["answer"]
                .replace(" ", "")
                .lower()
            )

            if user_answer == correct_answer:

                del self.active_quizzes[channel_id]

                await message.channel.send(
                    f"{message.author.mention} 정답입니다!\n\n"
                    f"정답: {quiz['answer']}"
                )

                return

        # ------------------------------
        # 주사위
        # ------------------------------

        if content == "주사위":

            number = random.randint(1, 100)

            await message.channel.send(
                f"{message.author.mention}의 주사위 결과: {number}"
            )

            return

        # ------------------------------
        # 가위바위보
        # ------------------------------

        if content == "가위바위보":

            view = RPSView(message.author)

            view.add_item(
                RPSButton("가위", "✊", "가위", view)
            )

            view.add_item(
                RPSButton("바위", "✋", "바위", view)
            )

            view.add_item(
                RPSButton("보", "✌️", "보", view)
            )

            await message.channel.send(
                f"가위바위보\n\n"
                f"{message.author.mention}님이 가위바위보를 시작했습니다.\n"
                f"참여하려면 아래 버튼을 선택해주세요.",
                view=view
            )

            return

        # 기존 prefix 명령어 작동을 위해 필요
        await self.bot.process_commands(message)


# ==============================
# Cog 등록
# ==============================

async def setup(bot):
    await bot.add_cog(Jara(bot))