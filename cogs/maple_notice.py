import discord
from discord.ext import commands, tasks

import aiohttp
import asyncio
import hashlib
import json
import re

from pathlib import Path
from urllib.parse import quote


# =========================================================
# 기본 설정
# =========================================================

BASE_URL = "https://mapleplanet.co.kr"

# Jina Reader
JINA_URL = "https://r.jina.ai/"

# 디스코드 채널
MAINTENANCE_CHANNEL_ID = 1557841882095030302
PATCHNOTE_CHANNEL_ID = 1557841935593513032

# 메이플플래닛 게시판
MAINTENANCE_LIST_URL = (
    "https://mapleplanet.co.kr/news/notices?status=maintenance"
)

PATCHNOTE_LIST_URL = (
    "https://mapleplanet.co.kr/news/updates"
)

# 자동 확인 주기
CHECK_INTERVAL = 60

# 상태 저장 파일
STATE_FILE = Path("maple_notice_state.json")


# =========================================================
# Cog
# =========================================================

class MapleNotice(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

        self.session = None

        self.state = {
            "maintenance": None,
            "patchnote": None,
        }

        self.load_state()

        self.check_loop.start()

    # -----------------------------------------------------
    # Cog 종료
    # -----------------------------------------------------

    def cog_unload(self):
        self.check_loop.cancel()

        if self.session and not self.session.closed:
            asyncio.create_task(self.session.close())

    # -----------------------------------------------------
    # 상태 파일
    # -----------------------------------------------------

    def load_state(self):
        try:
            if STATE_FILE.exists():
                with open(
                    STATE_FILE,
                    "r",
                    encoding="utf-8"
                ) as f:
                    self.state = json.load(f)

                print("📂 maple_notice 상태 파일 로드 완료")

        except Exception as e:
            print(f"⚠️ 상태 파일 로드 실패: {e}")

    def save_state(self):
        try:
            with open(
                STATE_FILE,
                "w",
                encoding="utf-8"
            ) as f:
                json.dump(
                    self.state,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

        except Exception as e:
            print(f"⚠️ 상태 파일 저장 실패: {e}")

    # -----------------------------------------------------
    # HTTP 세션
    # -----------------------------------------------------

    async def ensure_session(self):

        if self.session is None or self.session.closed:

            timeout = aiohttp.ClientTimeout(
                total=40
            )

            self.session = aiohttp.ClientSession(
                timeout=timeout
            )

    # -----------------------------------------------------
    # Jina Reader 요청
    # -----------------------------------------------------

    async def fetch_jina(self, target_url):

        await self.ensure_session()

        # 중요:
        # target_url에 ?status=maintenance 같은 query가 있기 때문에
        # 그대로 붙이면 Jina의 query로 잘못 해석될 수 있음.
        # 그래서 URL 자체를 encode해서 전달한다.
        encoded_url = quote(
            target_url,
            safe=":/"
        )

        jina_target = JINA_URL + encoded_url

        headers = {
            "Accept": "text/plain",
            "X-Respond-With": "markdown",
            "X-No-Cache": "true",
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "Chrome/140.0 Safari/537.36"
            ),
        }

        print("🌐 Jina 요청:")
        print(target_url)

        try:

            async with self.session.get(
                jina_target,
                headers=headers
            ) as response:

                print(
                    f"🌐 Jina HTTP 상태: {response.status}"
                )

                text = await response.text()

                if response.status != 200:

                    print(
                        f"❌ Jina HTTP 오류 {response.status}"
                    )

                    print(
                        text[:1000]
                    )

                    return None

                print(
                    f"✅ Jina 응답 수신 "
                    f"({len(text):,}자)"
                )

                return text

        except Exception as e:

            print(
                f"❌ Jina 요청 실패: {type(e).__name__}: {e}"
            )

            return None

    # -----------------------------------------------------
    # 게시글 링크 추출
    # -----------------------------------------------------

    def extract_posts(
        self,
        text,
        category
    ):

        posts = []

        if not text:
            return posts

        # -------------------------------------------------
        # 1. Markdown 링크
        #
        # [2026.10.07 패치노트](https://mapleplanet.co.kr/news/updates/742)
        # -------------------------------------------------

        markdown_pattern = re.compile(
            r"\[([^\]]+)\]\("
            r"(https://mapleplanet\.co\.kr/news/"
            r"(?:notices|updates)/(\d+))"
            r"\)"
        )

        for match in markdown_pattern.finditer(text):

            title = match.group(1).strip()
            url = match.group(2)
            post_id = int(match.group(3))

            posts.append(
                {
                    "id": post_id,
                    "title": title,
                    "url": url,
                }
            )

        # -------------------------------------------------
        # 2. Markdown이 아닌 일반 URL도 보조적으로 찾기
        # -------------------------------------------------

        url_pattern = re.compile(
            r"https://mapleplanet\.co\.kr/news/"
            r"(?:notices|updates)/(\d+)"
        )

        for match in url_pattern.finditer(text):

            post_id = int(match.group(1))

            if category == "patchnote":
                url = (
                    f"{BASE_URL}/news/updates/{post_id}"
                )
            else:
                url = (
                    f"{BASE_URL}/news/notices/{post_id}"
                )

            if not any(
                p["id"] == post_id
                for p in posts
            ):
                posts.append(
                    {
                        "id": post_id,
                        "title": "",
                        "url": url,
                    }
                )

        # -------------------------------------------------
        # 중복 제거
        # -------------------------------------------------

        unique = {}

        for post in posts:

            unique[post["id"]] = post

        posts = list(unique.values())

        # -------------------------------------------------
        # 점검 공지만 필터링
        # -------------------------------------------------

        if category == "maintenance":

            posts = [
                p
                for p in posts
                if "점검" in p["title"]
            ]

        # 최신 ID 순
        posts.sort(
            key=lambda x: x["id"],
            reverse=True
        )

        return posts

    # -----------------------------------------------------
    # 최신 게시글 가져오기
    # -----------------------------------------------------

    async def get_latest_post(
        self,
        category
    ):

        if category == "maintenance":

            list_url = MAINTENANCE_LIST_URL

        else:

            list_url = PATCHNOTE_LIST_URL

        text = await self.fetch_jina(
            list_url
        )

        if not text:

            print(
                f"❌ {category} 목록을 가져오지 못했습니다."
            )

            return None

        posts = self.extract_posts(
            text,
            category
        )

        if not posts:

            print(
                f"❌ {category} 게시글을 찾지 못했습니다."
            )

            print(
                "🔎 Jina 응답 앞부분:"
            )

            print(
                text[:2000]
            )

            return None

        latest = posts[0]

        print(
            f"🔎 최신 {category} 발견:"
        )

        print(
            f"   ID: {latest['id']}"
        )

        print(
            f"   제목: {latest['title']}"
        )

        print(
            f"   URL: {latest['url']}"
        )

        return latest

    # -----------------------------------------------------
    # 게시글 본문 가져오기
    # -----------------------------------------------------

    async def get_article(
        self,
        url
    ):

        text = await self.fetch_jina(
            url
        )

        if not text:
            return None

        # Jina의 기본 메타정보 제거
        lines = text.splitlines()

        cleaned = []

        for line in lines:

            stripped = line.strip()

            # Jina가 반환하는 대표적인 메타라인 제거
            if stripped.startswith(
                "Title:"
            ):
                continue

            if stripped.startswith(
                "URL Source:"
            ):
                continue

            if stripped.startswith(
                "Published Time:"
            ):
                continue

            if stripped.startswith(
                "Markdown Content:"
            ):
                continue

            cleaned.append(line)

        content = "\n".join(
            cleaned
        ).strip()

        return content

    # -----------------------------------------------------
    # 본문 해시
    # -----------------------------------------------------

    def make_hash(
        self,
        content
    ):

        normalized = re.sub(
            r"\s+",
            " ",
            content
        ).strip()

        return hashlib.sha256(
            normalized.encode(
                "utf-8"
            )
        ).hexdigest()

    # -----------------------------------------------------
    # 디스코드 채널
    # -----------------------------------------------------

    async def get_channel(
        self,
        category
    ):

        if category == "maintenance":

            channel_id = MAINTENANCE_CHANNEL_ID

        else:

            channel_id = PATCHNOTE_CHANNEL_ID

        channel = self.bot.get_channel(
            channel_id
        )

        if channel is None:

            try:

                channel = await self.bot.fetch_channel(
                    channel_id
                )

            except Exception as e:

                print(
                    f"❌ 디스코드 채널 가져오기 실패: {e}"
                )

                return None

        return channel

    # -----------------------------------------------------
    # 기존 부모 메시지 찾기
    # -----------------------------------------------------

    async def find_parent_message(
        self,
        channel,
        url
    ):

        try:

            async for message in channel.history(
                limit=100
            ):

                for embed in message.embeds:

                    if embed.url == url:

                        return message

        except Exception as e:

            print(
                f"⚠️ 기존 메시지 검색 실패: {e}"
            )

        return None

    # -----------------------------------------------------
    # 본문 분할
    # -----------------------------------------------------

    def split_content(
        self,
        content,
        limit=1900
    ):

        chunks = []

        while len(content) > limit:

            split_at = content.rfind(
                "\n",
                0,
                limit
            )

            if split_at <= 0:

                split_at = limit

            chunks.append(
                content[:split_at]
            )

            content = content[
                split_at:
            ].lstrip()

        if content:

            chunks.append(
                content
            )

        return chunks

    # -----------------------------------------------------
    # 새 공지 등록
    # -----------------------------------------------------

    async def create_notice(
        self,
        category,
        post,
        content
    ):

        channel = await self.get_channel(
            category
        )

        if channel is None:
            return None

        if category == "maintenance":

            prefix = "🔧 점검 안내"

        else:

            prefix = "📝 패치노트"

        embed = discord.Embed(
            title=f"{prefix} | {post['title']}",
            url=post["url"],
            description=(
                "메이플플래닛 공식 홈페이지에 "
                "새로운 게시글이 등록되었습니다.\n\n"
                "자세한 내용은 아래 스레드에서 확인해주세요."
            ),
            color=discord.Color.blue()
        )

        embed.set_footer(
            text="메이플플래닛 공식 홈페이지"
        )

        # 부모 메시지
        parent = await channel.send(
            embed=embed
        )

        # 스레드 생성
        thread = await parent.create_thread(
            name=post["title"][:100],
            auto_archive_duration=10080
        )

        # 본문
        chunks = self.split_content(
            content
        )

        for chunk in chunks:

            await thread.send(
                chunk
            )

        await thread.send(
            f"🔗 공식 게시글\n{post['url']}"
        )

        print(
            f"🟢 새 {category} 게시글 등록 완료:"
            f" {post['title']}"
        )

        return parent.id

    # -----------------------------------------------------
    # 기존 공지 수정
    # -----------------------------------------------------

    async def update_notice(
        self,
        category,
        post,
        content,
        parent_id
    ):

        channel = await self.get_channel(
            category
        )

        if channel is None:
            return

        try:

            parent = await channel.fetch_message(
                int(parent_id)
            )

        except Exception as e:

            print(
                f"⚠️ 기존 부모 메시지 가져오기 실패: {e}"
            )

            return

        thread = parent.thread

        if thread is None:

            print(
                "⚠️ 기존 스레드를 찾지 못했습니다."
            )

            return

        try:

            if thread.archived:

                await thread.edit(
                    archived=False
                )

        except Exception as e:

            print(
                f"⚠️ 스레드 복구 실패: {e}"
            )

        # 수정 알림
        await thread.send(
            "⚠️ **이 공지가 수정되었습니다.**"
        )

        # 수정된 본문
        chunks = self.split_content(
            content
        )

        for chunk in chunks:

            await thread.send(
                chunk
            )

        await thread.send(
            f"🔗 공식 게시글\n{post['url']}"
        )

        # 부모 Embed도 갱신
        if parent.embeds:

            embed = parent.embeds[0]

            embed.title = (
                f"{'🔧 점검 안내' if category == 'maintenance' else '📝 패치노트'}"
                f" | {post['title']}"
            )

            embed.url = post["url"]

            await parent.edit(
                embed=embed
            )

        print(
            f"🟡 수정된 {category} 게시글 반영 완료:"
            f" {post['title']}"
        )

    # -----------------------------------------------------
    # 하나의 카테고리 확인
    # -----------------------------------------------------

    async def check_category(
        self,
        category
    ):

        try:

            post = await self.get_latest_post(
                category
            )

            if not post:
                return

            content = await self.get_article(
                post["url"]
            )

            if not content:

                print(
                    f"❌ 본문을 가져오지 못했습니다:"
                    f" {post['url']}"
                )

                return

            content_hash = self.make_hash(
                content
            )

            previous = self.state.get(
                category
            )

            # -------------------------------------------------
            # 최초 실행
            # -------------------------------------------------

            if previous is None:

                self.state[category] = {
                    "id": post["id"],
                    "url": post["url"],
                    "title": post["title"],
                    "hash": content_hash,
                    "parent_id": None,
                }

                self.save_state()

                print(
                    f"📌 {category} 최초 실행:"
                    f" 현재 글을 기준점으로 저장했습니다."
                )

                return

            # -------------------------------------------------
            # 새로운 게시글
            # -------------------------------------------------

            if previous.get("url") != post["url"]:

                print(
                    f"🆕 새로운 {category} 발견!"
                )

                parent_id = await self.create_notice(
                    category,
                    post,
                    content
                )

                self.state[category] = {
                    "id": post["id"],
                    "url": post["url"],
                    "title": post["title"],
                    "hash": content_hash,
                    "parent_id": parent_id,
                }

                self.save_state()

                return

            # -------------------------------------------------
            # 같은 게시글 내용 수정
            # -------------------------------------------------

            if previous.get("hash") != content_hash:

                print(
                    f"✏️ 기존 {category} 게시글 수정 감지!"
                )

                parent_id = previous.get(
                    "parent_id"
                )

                # 상태에 부모 ID가 없다면
                # 디스코드에서 URL을 검색
                if not parent_id:

                    channel = await self.get_channel(
                        category
                    )

                    if channel:

                        parent = (
                            await self.find_parent_message(
                                channel,
                                post["url"]
                            )
                        )

                        if parent:

                            parent_id = parent.id

                if parent_id:

                    await self.update_notice(
                        category,
                        post,
                        content,
                        parent_id
                    )

                else:

                    print(
                        "⚠️ 기존 디스코드 메시지를 찾지 못했습니다."
                    )

                self.state[category]["hash"] = (
                    content_hash
                )

                self.state[category]["title"] = (
                    post["title"]
                )

                self.save_state()

                return

            # -------------------------------------------------
            # 아무 변화 없음
            # -------------------------------------------------

            print(
                f"✅ {category}: 변경 없음"
            )

        except Exception as e:

            print(
                f"❌ {category} 확인 중 오류:"
                f" {type(e).__name__}: {e}"
            )

    # -----------------------------------------------------
    # 자동 감시
    # -----------------------------------------------------

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def check_loop(self):

        # 봇 준비 전에는 실행하지 않음
        if not self.bot.is_ready():

            return

        print(
            "🔄 메이플플래닛 공지 확인 시작"
        )

        await self.check_category(
            "maintenance"
        )

        # 너무 빠르게 연속 요청하지 않도록
        await asyncio.sleep(3)

        await self.check_category(
            "patchnote"
        )

    # -----------------------------------------------------
    # loop 시작 전
    # -----------------------------------------------------

    @check_loop.before_loop
    async def before_check_loop(self):

        await self.bot.wait_until_ready()

        print(
            "📢 메이플플래닛 공지 감시 시작"
        )

    # -----------------------------------------------------
    # 점검 공지 테스트
    # -----------------------------------------------------

    @commands.command(
        name="공지테스트"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def maintenance_test(
        self,
        ctx
    ):

        await ctx.send(
            "🔎 메이플플래닛 점검 공지를 확인합니다..."
        )

        post = await self.get_latest_post(
            "maintenance"
        )

        if not post:

            await ctx.send(
                "❌ 점검 공지를 찾지 못했습니다."
            )

            return

        content = await self.get_article(
            post["url"]
        )

        if not content:

            await ctx.send(
                "❌ 게시글 본문을 가져오지 못했습니다."
            )

            return

        await ctx.send(
            f"🟢 찾았습니다!\n"
            f"**{post['title']}**\n"
            f"{post['url']}"
        )

    # -----------------------------------------------------
    # 패치노트 테스트
    # -----------------------------------------------------

    @commands.command(
        name="패치노트테스트"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def patchnote_test(
        self,
        ctx
    ):

        await ctx.send(
            "🔎 메이플플래닛 패치노트를 확인합니다..."
        )

        post = await self.get_latest_post(
            "patchnote"
        )

        if not post:

            await ctx.send(
                "❌ 패치노트를 찾지 못했습니다."
            )

            return

        content = await self.get_article(
            post["url"]
        )

        if not content:

            await ctx.send(
                "❌ 패치노트 본문을 가져오지 못했습니다."
            )

            return

        await ctx.send(
            f"🟢 찾았습니다!\n"
            f"**{post['title']}**\n"
            f"{post['url']}"
        )


# =========================================================
# setup
# =========================================================

async def setup(bot):

    await bot.add_cog(
        MapleNotice(bot)
    )