import asyncio
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote

import aiohttp
import discord
from discord.ext import commands


# =========================================================
# 기본 설정
# =========================================================

BASE_URL = "https://mapleplanet.co.kr"

# 디스코드 채널
MAINTENANCE_CHANNEL_ID = 1557841882095030302
PATCHNOTE_CHANNEL_ID = 1557841935593513032

# 메이플플래닛 메인 페이지
# Render에서 메이플플래닛 직접 접속 시 403이 발생하므로
# Jina Reader를 통해 가져옵니다.
MAPLE_HOME_URL = "https://mapleplanet.co.kr/"

# Jina Reader
JINA_URL = "https://r.jina.ai/"

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
        self.notice_task = None

        self.state = {
            "maintenance": {},
            "patchnote": {}
        }

    # =====================================================
    # Cog 시작
    # =====================================================

    async def cog_load(self):

        print(
            "📢 메이플플래닛 공지 감시 시작",
            flush=True
        )

        self.load_state()

        timeout = aiohttp.ClientTimeout(
            total=30
        )

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/plain,text/markdown,*/*"
        }

        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers=headers
        )

        self.notice_task = asyncio.create_task(
            self.notice_loop()
        )

    # =====================================================
    # Cog 종료
    # =====================================================

    def cog_unload(self):

        if self.notice_task:
            self.notice_task.cancel()

        if self.session:
            asyncio.create_task(
                self.session.close()
            )

    # =====================================================
    # 상태 불러오기
    # =====================================================

    def load_state(self):

        try:

            if not STATE_FILE.exists():

                print(
                    "ℹ️ 기존 상태 파일 없음",
                    flush=True
                )

                return

            with open(
                STATE_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                self.state = json.load(f)

            print(
                "📂 기존 공지 상태 불러오기 완료",
                flush=True
            )

        except Exception as e:

            print(
                f"⚠️ 상태 파일 불러오기 실패: {e}",
                flush=True
            )

            self.state = {
                "maintenance": {},
                "patchnote": {}
            }

    # =====================================================
    # 상태 저장
    # =====================================================

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

            print(
                f"⚠️ 상태 저장 실패: {e}",
                flush=True
            )

    # =====================================================
    # Jina Reader를 통해 페이지 가져오기
    # =====================================================

    async def fetch_page(self, target_url):

        try:

            # URL 안전하게 인코딩
            jina_url = (
                JINA_URL
                + target_url
            )

            print(
                f"🌐 Jina 요청: {target_url}",
                flush=True
            )

            async with self.session.get(
                jina_url
            ) as response:

                print(
                    f"🌐 Jina HTTP 상태: "
                    f"{response.status}",
                    flush=True
                )

                if response.status != 200:

                    error_text = await response.text()

                    print(
                        f"❌ Jina 오류 "
                        f"{response.status}",
                        flush=True
                    )

                    print(
                        f"❌ 응답: "
                        f"{error_text[:300]}",
                        flush=True
                    )

                    return None

                text = await response.text(
                    encoding="utf-8",
                    errors="ignore"
                )

                print(
                    f"📄 Jina 응답 수신: "
                    f"{len(text)} bytes",
                    flush=True
                )

                return text

        except asyncio.CancelledError:

            raise

        except Exception as e:

            print(
                f"❌ Jina 요청 실패: "
                f"{type(e).__name__}: {e}",
                flush=True
            )

            return None

    # =====================================================
    # 게시글 링크 추출
    # =====================================================

    def extract_posts(
        self,
        text,
        board_type
    ):

        posts = {}

        if not text:
            return posts

        # -------------------------------------------------
        # Markdown 링크
        #
        # [제목](https://mapleplanet.co.kr/news/updates/742)
        #
        # 또는
        #
        # [제목](/news/updates/742)
        # -------------------------------------------------

        pattern = re.compile(
            r"\[([^\]]+)\]"
            r"\("
            r"(https?://mapleplanet\.co\.kr)?"
            r"(/news/"
            + re.escape(board_type)
            + r"/(\d+))"
            r"\)"
        )

        for match in pattern.finditer(text):

            title = match.group(1).strip()
            post_id = int(match.group(4))

            relative_url = match.group(3)

            url = (
                BASE_URL
                + relative_url
            )

            # ------------------------------------------------
            # 점검 게시판이면 "점검" 글만
            # ------------------------------------------------

            if board_type == "notices":

                if "점검" not in title:

                    continue

            posts[post_id] = (
                url,
                title
            )

        # -------------------------------------------------
        # 혹시 Markdown 링크 형식이 다를 경우
        # URL만 다시 검색
        # -------------------------------------------------

        if not posts:

            url_pattern = re.compile(
                r"https?://mapleplanet\.co\.kr"
                r"/news/"
                + re.escape(board_type)
                + r"/(\d+)"
            )

            for match in url_pattern.finditer(text):

                post_id = int(
                    match.group(1)
                )

                url = (
                    BASE_URL
                    + f"/news/{board_type}/{post_id}"
                )

                # 제목을 주변 텍스트에서 찾기
                start = max(
                    0,
                    match.start() - 150
                )

                nearby = text[
                    start:match.start()
                ]

                lines = [
                    x.strip()
                    for x in nearby.splitlines()
                    if x.strip()
                ]

                title = (
                    lines[-1]
                    if lines
                    else f"메이플플래닛 게시글 {post_id}"
                )

                if board_type == "notices":

                    if "점검" not in title:

                        continue

                posts[post_id] = (
                    url,
                    title
                )

        return posts

    # =====================================================
    # 최신 게시글 찾기
    # =====================================================

    async def get_latest_post(
        self,
        category
    ):

        text = await self.fetch_page(
            MAPLE_HOME_URL
        )

        if not text:

            print(
                "❌ 메이플플래닛 메인 페이지를 "
                "가져오지 못했습니다.",
                flush=True
            )

            return None

        # -------------------------------------------------
        # 카테고리별 게시판
        # -------------------------------------------------

        if category == "maintenance":

            board_type = "notices"

        else:

            board_type = "updates"

        posts = self.extract_posts(
            text,
            board_type
        )

        # -------------------------------------------------
        # 검색 결과
        # -------------------------------------------------

        if not posts:

            print(
                f"❌ {category} 게시글 링크를 "
                f"찾지 못했습니다.",
                flush=True
            )

            print(
                "🔎 Jina 응답 앞부분:",
                text[:1000].replace(
                    "\n",
                    " "
                ),
                flush=True
            )

            return None

        latest_id = max(
            posts.keys()
        )

        url, title = posts[
            latest_id
        ]

        print(
            f"🔎 최신 {category} 발견:",
            flush=True
        )

        print(
            f"   ID: {latest_id}",
            flush=True
        )

        print(
            f"   제목: {title}",
            flush=True
        )

        print(
            f"   URL: {url}",
            flush=True
        )

        return (
            url,
            title
        )

    # =====================================================
    # 게시글 본문 가져오기
    # =====================================================

    async def get_article(
        self,
        url
    ):

        text = await self.fetch_page(
            url
        )

        if not text:

            return None

        # -------------------------------------------------
        # Jina Markdown에서 기본적인 불필요 요소 제거
        # -------------------------------------------------

        lines = []

        for line in text.splitlines():

            line = line.strip()

            if not line:
                continue

            # 너무 긴 사이트 메뉴 등은 일단 유지
            lines.append(line)

        text = "\n".join(lines)

        # -------------------------------------------------
        # 너무 앞쪽의 사이트 공통 메뉴 제거
        # -------------------------------------------------

        # 제목 위치를 찾는다.
        title_match = re.search(
            r"^# .+",
            text,
            re.MULTILINE
        )

        if title_match:

            text = text[
                title_match.start():
            ]

        # -------------------------------------------------
        # 너무 많은 연속 빈 줄 정리
        # -------------------------------------------------

        text = re.sub(
            r"\n{3,}",
            "\n\n",
            text
        )

        return text.strip()

    # =====================================================
    # 내용 해시
    # =====================================================

    def make_hash(
        self,
        text
    ):

        normalized = re.sub(
            r"\s+",
            " ",
            text
        ).strip()

        return hashlib.sha256(
            normalized.encode(
                "utf-8"
            )
        ).hexdigest()

    # =====================================================
    # Discord 2000자 제한 분할
    # =====================================================

    def split_text(
        self,
        text,
        limit=1900
    ):

        chunks = []

        while len(text) > limit:

            cut = text.rfind(
                "\n",
                0,
                limit
            )

            if cut <= 0:

                cut = limit

            chunks.append(
                text[:cut].strip()
            )

            text = text[
                cut:
            ].strip()

        if text:

            chunks.append(
                text
            )

        return chunks

    # =====================================================
    # 새 공지 생성
    # =====================================================

    async def create_notice(
        self,
        channel_id,
        category,
        title,
        url,
        content
    ):

        channel = self.bot.get_channel(
            channel_id
        )

        if not channel:

            print(
                f"❌ Discord 채널을 찾을 수 없음: "
                f"{channel_id}",
                flush=True
            )

            return None

        # -------------------------------------------------
        # Embed
        # -------------------------------------------------

        if category == "maintenance":

            embed_title = (
                "🔧 메이플플래닛 점검 안내"
            )

            embed_color = (
                discord.Color.orange()
            )

        else:

            embed_title = (
                "📢 메이플플래닛 패치노트"
            )

            embed_color = (
                discord.Color.blue()
            )

        embed = discord.Embed(
            title=embed_title,
            description=title,
            url=url,
            color=embed_color
        )

        embed.set_footer(
            text="메이플플래닛 공식 홈페이지"
        )

        # -------------------------------------------------
        # 부모 메시지
        # -------------------------------------------------

        message = await channel.send(
            embed=embed
        )

        print(
            f"📨 부모 메시지 생성: "
            f"{message.id}",
            flush=True
        )

        # -------------------------------------------------
        # Thread
        # -------------------------------------------------

        thread = await message.create_thread(
            name=title[:100],
            auto_archive_duration=10080
        )

        print(
            f"🧵 스레드 생성: "
            f"{thread.id}",
            flush=True
        )

        # -------------------------------------------------
        # 본문
        # -------------------------------------------------

        chunks = self.split_text(
            content
        )

        for chunk in chunks:

            await thread.send(
                chunk
            )

        # -------------------------------------------------
        # 원문
        # -------------------------------------------------

        await thread.send(
            f"🔗 **공식 원문:**\n{url}"
        )

        return {
            "message_id": message.id,
            "thread_id": thread.id,
            "url": url,
            "title": title,
            "hash": self.make_hash(
                content
            )
        }

    # =====================================================
    # 수정된 공지 처리
    # =====================================================

    async def update_notice(
        self,
        category,
        channel_id,
        data,
        title,
        url,
        content
    ):

        channel = self.bot.get_channel(
            channel_id
        )

        if not channel:

            return None

        message_id = data.get(
            "message_id"
        )

        thread_id = data.get(
            "thread_id"
        )

        # -------------------------------------------------
        # 기존 부모 메시지
        # -------------------------------------------------

        message = None

        if message_id:

            try:

                message = await channel.fetch_message(
                    message_id
                )

            except Exception as e:

                print(
                    f"⚠️ 기존 메시지 조회 실패: {e}",
                    flush=True
                )

        # -------------------------------------------------
        # 기존 스레드
        # -------------------------------------------------

        thread = None

        if thread_id:

            thread = self.bot.get_channel(
                thread_id
            )

            if thread is None:

                try:

                    thread = await self.bot.fetch_channel(
                        thread_id
                    )

                except Exception as e:

                    print(
                        f"⚠️ 기존 스레드 조회 실패: {e}",
                        flush=True
                    )

        # -------------------------------------------------
        # 부모 메시지가 사라졌으면 새 공지
        # -------------------------------------------------

        if message is None:

            print(
                "⚠️ 기존 공지 메시지가 없어 "
                "새 공지를 생성합니다.",
                flush=True
            )

            return await self.create_notice(
                channel_id,
                category,
                title,
                url,
                content
            )

        # -------------------------------------------------
        # 기존 스레드에 수정 내용 추가
        # -------------------------------------------------

        if thread:

            try:

                if thread.archived:

                    await thread.edit(
                        archived=False
                    )

                await thread.send(
                    "⚠️ **이 공지가 수정되었습니다.**"
                )

                await thread.send(
                    "📌 **수정된 최신 내용**"
                )

                chunks = self.split_text(
                    content
                )

                for chunk in chunks:

                    await thread.send(
                        chunk
                    )

                await thread.send(
                    f"🔗 **공식 원문:**\n{url}"
                )

            except Exception as e:

                print(
                    f"⚠️ 수정 내용 전송 실패: {e}",
                    flush=True
                )

        # -------------------------------------------------
        # 부모 Embed 수정
        # -------------------------------------------------

        try:

            if category == "maintenance":

                embed_title = (
                    "🔧 메이플플래닛 점검 안내"
                )

                color = discord.Color.orange()

            else:

                embed_title = (
                    "📢 메이플플래닛 패치노트"
                )

                color = discord.Color.blue()

            embed = discord.Embed(
                title=embed_title,
                description=title,
                url=url,
                color=color
            )

            embed.set_footer(
                text="메이플플래닛 공식 홈페이지"
            )

            await message.edit(
                embed=embed
            )

        except Exception as e:

            print(
                f"⚠️ Embed 수정 실패: {e}",
                flush=True
            )

        # -------------------------------------------------
        # 상태 업데이트
        # -------------------------------------------------

        data["title"] = title
        data["url"] = url
        data["hash"] = self.make_hash(
            content
        )

        return data

    # =====================================================
    # 공지 확인
    # =====================================================

    async def check_notice(
        self,
        category,
        channel_id
    ):

        try:

            latest = await self.get_latest_post(
                category
            )

            if not latest:

                print(
                    f"❌ {category} 최신 글을 찾지 못했습니다.",
                    flush=True
                )

                return

            url, title = latest

            # ------------------------------------------------
            # 본문 가져오기
            # ------------------------------------------------

            content = await self.get_article(
                url
            )

            if not content:

                print(
                    f"❌ 본문 가져오기 실패: {url}",
                    flush=True
                )

                return

            content_hash = self.make_hash(
                content
            )

            previous = self.state.get(
                category,
                {}
            )

            # =================================================
            # 첫 실행
            # =================================================

            if not previous:

                print(
                    f"🟡 {category}: "
                    f"첫 실행 기준점 저장",
                    flush=True
                )

                self.state[category] = {
                    "url": url,
                    "title": title,
                    "hash": content_hash
                }

                self.save_state()

                return

            # =================================================
            # 새 글
            # =================================================

            if previous.get("url") != url:

                print(
                    f"🆕 새로운 {category} 발견!",
                    flush=True
                )

                data = await self.create_notice(
                    channel_id,
                    category,
                    title,
                    url,
                    content
                )

                if data:

                    self.state[category] = data

                    self.save_state()

                return

            # =================================================
            # 기존 글 수정
            # =================================================

            if previous.get("hash") != content_hash:

                print(
                    f"✏️ {category} 수정 감지!",
                    flush=True
                )

                updated = await self.update_notice(
                    category,
                    channel_id,
                    previous,
                    title,
                    url,
                    content
                )

                if updated:

                    self.state[category] = updated

                    self.save_state()

                return

            # =================================================
            # 변경 없음
            # =================================================

            print(
                f"🟢 {category}: 변경 없음",
                flush=True
            )

        except Exception as e:

            print(
                f"❌ {category} 확인 오류: "
                f"{type(e).__name__}: {e}",
                flush=True
            )

    # =====================================================
    # 자동 감시
    # =====================================================

    async def notice_loop(self):

        await self.bot.wait_until_ready()

        print(
            "🚀 메이플플래닛 공지 자동 감시 시작",
            flush=True
        )

        while not self.bot.is_closed():

            try:

                print(
                    "\n==============================",
                    flush=True
                )

                print(
                    "🔄 메이플플래닛 공지 확인",
                    flush=True
                )

                print(
                    "==============================",
                    flush=True
                )

                # 점검
                await self.check_notice(
                    "maintenance",
                    MAINTENANCE_CHANNEL_ID
                )

                # 패치노트
                await self.check_notice(
                    "patchnote",
                    PATCHNOTE_CHANNEL_ID
                )

            except asyncio.CancelledError:

                raise

            except Exception as e:

                print(
                    f"❌ 자동 감시 오류: {e}",
                    flush=True
                )

            await asyncio.sleep(
                CHECK_INTERVAL
            )

    # =====================================================
    # !공지테스트
    # =====================================================

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

        msg = await ctx.send(
            "🔎 최신 점검 공지를 가져오는 중입니다..."
        )

        latest = await self.get_latest_post(
            "maintenance"
        )

        if not latest:

            await msg.edit(
                content=(
                    "❌ 최신 점검 공지를 찾지 못했습니다."
                )
            )

            return

        url, title = latest

        content = await self.get_article(
            url
        )

        if not content:

            await msg.edit(
                content=(
                    "❌ 점검 공지 본문을 "
                    "가져오지 못했습니다."
                )
            )

            return

        await self.create_notice(
            MAINTENANCE_CHANNEL_ID,
            "maintenance",
            title,
            url,
            content
        )

        await msg.edit(
            content=(
                "✅ 최신 점검 공지를 "
                "테스트 전송했습니다.\n\n"
                f"**{title}**"
            )
        )

    # =====================================================
    # !패치노트테스트
    # =====================================================

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

        msg = await ctx.send(
            "🔎 최신 패치노트를 가져오는 중입니다..."
        )

        latest = await self.get_latest_post(
            "patchnote"
        )

        if not latest:

            await msg.edit(
                content=(
                    "❌ 최신 패치노트를 찾지 못했습니다."
                )
            )

            return

        url, title = latest

        content = await self.get_article(
            url
        )

        if not content:

            await msg.edit(
                content=(
                    "❌ 패치노트 본문을 "
                    "가져오지 못했습니다."
                )
            )

            return

        await self.create_notice(
            PATCHNOTE_CHANNEL_ID,
            "patchnote",
            title,
            url,
            content
        )

        await msg.edit(
            content=(
                "✅ 최신 패치노트를 "
                "테스트 전송했습니다.\n\n"
                f"**{title}**"
            )
        )


# =========================================================
# Cog 등록
# =========================================================

async def setup(bot):

    await bot.add_cog(
        MapleNotice(bot)
    )