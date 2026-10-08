import discord
from discord.ext import commands
from discord import app_commands


# ==============================
# 설정
# ==============================

LEAVE_LOG_CHANNEL_ID = 1520647014709329940


class Jara(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ==============================
    # 🧹 /purge all
    # ==============================

    @app_commands.command(
        name="purge",
        description="현재 채널의 메시지를 모두 삭제합니다."
    )
    @app_commands.describe(
        action="실행할 작업"
    )
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
            await interaction.response.send_message(
                "사용할 수 없는 명령입니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        channel = interaction.channel

        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send(
                "텍스트 채널에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        deleted = await channel.purge(limit=None)

        await interaction.followup.send(
            f"🧹 메시지 {len(deleted)}개를 삭제했습니다.",
            ephemeral=True
        )

    # ==============================
    # 🚪 서버 퇴장 로그
    # ==============================

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):

        channel = self.bot.get_channel(LEAVE_LOG_CHANNEL_ID)

        if channel is None:
            print(
                f"❌ 퇴장 로그 채널을 찾을 수 없습니다: "
                f"{LEAVE_LOG_CHANNEL_ID}"
            )
            return

        # 서버에서 사용하던 별명
        nickname = member.nick if member.nick else "없음"

        # 기본 사용자명
        username = member.name

        embed = discord.Embed(
            title="🚪 서버 퇴장",
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
            value=username,
            inline=True
        )

        embed.add_field(
            name="사용자 ID",
            value=str(member.id),
            inline=False
        )

        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)

        embed.set_footer(
            text=f"{member} 님이 서버를 나갔습니다."
        )

        await channel.send(embed=embed)


    # ==============================
    # 오류 처리
    # ==============================

    @purge.error
    async def purge_error(
        self,
        interaction: discord.Interaction,
        error
    ):
        if isinstance(
            error,
            app_commands.errors.MissingPermissions
        ):
            await interaction.response.send_message(
                "❌ 메시지 관리 권한이 필요합니다.",
                ephemeral=True
            )
            return

        print(f"❌ /purge 오류: {error}")

        if interaction.response.is_done():
            await interaction.followup.send(
                "❌ 명령 실행 중 오류가 발생했습니다.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ 명령 실행 중 오류가 발생했습니다.",
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(Jara(bot))