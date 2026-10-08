import asyncio
import hashlib
import json
import os

import aiohttp
import discord
from bs4 import BeautifulSoup
from discord.ext import commands, tasks


# =========================================================
# 📌 디스코드 채널 ID
# =========================================================

MAINTENANCE_CHANNEL_ID = 1557841882095030302
PATCHNOTE_CHANNEL_ID = 1557841935593513032


# =========================================================
# 📌 메이플플래닛 공식 페이지
# =========================================================

MAINTENANCE_LIST_URL = (
    "https://mapleplanet.co.kr/news/notices?status=maintenance"
)

PATCHNOTE_LIST_URL = (
    "https://mapleplanet.co.kr/news/updates"
)

BASE_URL = "https://mapleplanet.co.kr"


# =========================================================
# 📌 상태 저장 파일
# =========================================================

STATE_FILE = "maple_notice_state.json"


# =========================================================
# MaplePlanet Notice Cog
# =========================================================

class MaplePlanetNotice(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

        self.state = {
            "maintenance": {},
            "patchnote": {}
        }

        self.load_state()

        # 1분마다 공지 확인
        self.notice_checker.start()


    # =====================================================
    # Cog 종료
    # =====================================================

    def cog_unload(self):
        self.notice_checker.cancel()


    # =====================================================
    # 상태 불러오기
    # =====================================================

    def load_state(self):

        if not os.path.exists(STATE_FILE):
            return

        try:

            with open(
                STATE_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

            self.state.update(data)

            # 예전 버전의 상태 파일과 호환
            if not isinstance(
                self.state.get("maintenance"),
                dict
            ):
                self.state["maintenance"] = {}

            if not isinstance(
                self.state.get("patchnote"),
                dict
            ):
                self.state["patchnote"] = {}

        except Exception as e:

            print(
                f"[메이플 공지] "
                f"상태 파일 불러오기 실패: {e}"
            )


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
                    indent=4
                )

        except Exception as e:

            print(
                f"[메이플 공지] "
                f"상태 파일 저장 실패: {e}"
            )


    # =====================================================
    # HTML 가져오기
    # =====================================================

    async def fetch_html(self, url):

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            )
        }

        timeout = aiohttp.ClientTimeout(
            total=20
        )

        async with aiohttp.ClientSession(
            headers=headers,
            timeout=timeout
        ) as session:

            async with session.get(url) as response:

                if response.status != 200:

                    raise Exception(
                        f"HTTP {response.status}"
                    )

                return await response.text()


    # =====================================================
    # 최신 게시글 찾기
    # =====================================================

    async def get_latest_post(
        self,
        url,
        post_type
    ):

        html = await self.fetch_html(url)

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        # -------------------------------------------------
        # 게시글 주소 패턴
        # -------------------------------------------------

        candidates = []

        for a in soup.find_all(
            "a",
            href=True
        ):

            href = a.get("href", "").strip()

            if post_type == "notices":

                if not href.startswith(
                    "/news/notices/"
                ):
                    continue

            elif post_type == "updates":

                if not href.startswith(
                    "/news/updates/"
                ):
                    continue

            else:
                continue


            # 숫자 ID가 붙은 실제 게시글인지 확인
            parts = href.rstrip("/").split("/")

            if not parts:
                continue

            if not parts[-1].isdigit():
                continue


            title = a.get_text(
                " ",
                strip=True
            )

            if not title:
                continue


            candidates.append(
                (
                    href,
                    title
                )
            )


        if not candidates:
            return None


        # -------------------------------------------------
        # 중복 링크 제거
        # -------------------------------------------------

        unique = []

        seen = set()

        for href, title in candidates:

            if href in seen:
                continue

            seen.add(href)

            unique.append(
                (
                    href,
                    title
                )
            )


        if not unique:
            return None


        # 목록에서 가장 먼저 발견된 게시글 = 최신글
        href, title = unique[0]


        if href.startswith("http"):

            full_url = href

        else:

            full_url = (
                BASE_URL + href
            )


        return {
            "url": full_url,
            "title": title
        }


    # =====================================================
    # 게시글 본문 가져오기
    # =====================================================

    async def get_article_content(
        self,
        url
    ):

        html = await self.fetch_html(url)

        soup = BeautifulSoup(
            html,
            "html.parser"
        )


        # -------------------------------------------------
        # 불필요한 태그 제거
        # -------------------------------------------------

        for tag in soup.find_all(
            [
                "script",
                "style",
                "nav",
                "header",
                "footer"
            ]
        ):

            tag.decompose()


        # -------------------------------------------------
        # 게시글 제목 제거
        # -------------------------------------------------

        for tag_name in [
            "h1",
            "h2"
        ]:

            tag = soup.find(tag_name)

            if tag:
                tag.decompose()

                break


        # -------------------------------------------------
        # 본문 후보
        # -------------------------------------------------

        article = (
            soup.find("article")
            or soup.find("main")
            or soup.body
        )


        if not article:

            return (
                "⚠️ 공지 본문을 "
                "가져오지 못했습니다."
            )


        text = article.get_text(
            "\n",
            strip=True
        )


        # -------------------------------------------------
        # 빈 줄 정리
        # -------------------------------------------------

        lines = []

        for line in text.splitlines():

            line = line.strip()

            if not line:
                continue

            lines.append(line)


        text = "\n".join(lines)


        return text.strip()


    # =====================================================
    # 본문 해시
    # =====================================================

    def make_content_hash(
        self,
        content
    ):

        normalized = (
            content
            .replace("\r", "")
            .strip()
        )

        return hashlib.sha256(
            normalized.encode(
                "utf-8"
            )
        ).hexdigest()


    # =====================================================
    # Discord 메시지 길이 분할
    # =====================================================

    def split_message(
        self,
        text,
        max_length=1900
    ):

        chunks = []

        while len(text) > max_length:

            cut = text.rfind(
                "\n",
                0,
                max_length
            )

            if cut < 500:

                cut = max_length


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
    # 새 공지 전송
    # =====================================================

    async def send_new_notice(
        self,
        notice_type,
        post,
        content,
        channel_id
    ):

        channel = self.bot.get_channel(
            channel_id
        )


        if channel is None:

            print(
                "[메이플 공지] "
                f"채널을 찾을 수 없습니다: "
                f"{channel_id}"
            )

            return None


        # -------------------------------------------------
        # 종류별 Embed
        # -------------------------------------------------

        if notice_type == "maintenance":

            embed = discord.Embed(
                title=f"🛠️ {post['title']}",
                description=(
                    "메이플플래닛 공식 홈페이지에 "
                    "새로운 **점검 공지**가 등록되었습니다.\n\n"
                    f"🔗 [공식 공지 원문]({post['url']})"
                ),
                color=0xF39C12
            )

        else:

            embed = discord.Embed(
                title=f"📜 {post['title']}",
                description=(
                    "메이플플래닛 공식 홈페이지에 "
                    "새로운 **패치노트**가 등록되었습니다.\n\n"
                    f"🔗 [공식 패치노트]({post['url']})"
                ),
                color=0x3498DB
            )


        embed.set_footer(
            text="MAPLEPLANET 공식 공지 자동 알림"
        )


        # -------------------------------------------------
        # 메인 메시지
        # -------------------------------------------------

        message = await channel.send(
            embed=embed
        )


        # -------------------------------------------------
        # 스레드 생성
        # -------------------------------------------------

        thread = await message.create_thread(
            name=post["title"][:100],
            auto_archive_duration=1440
        )


        # -------------------------------------------------
        # 본문 전송
        # -------------------------------------------------

        chunks = self.split_message(
            content
        )


        for index, chunk in enumerate(
            chunks
        ):

            if index == 0:

                await thread.send(
                    "📢 **공식 공지 원문**\n\n"
                    + chunk
                )

            else:

                await thread.send(
                    chunk
                )


            await asyncio.sleep(
                0.3
            )


        # -------------------------------------------------
        # 원문 링크
        # -------------------------------------------------

        await thread.send(
            "🔗 **공식 공지:**\n"
            + post["url"]
        )


        print(
            "[메이플 공지] 새 공지 전송 완료: "
            + post["title"]
        )


        return {
            "message_id": message.id,
            "thread_id": thread.id
        }


    # =====================================================
    # 수정 공지 처리
    # =====================================================

    async def update_existing_notice(
        self,
        notice_type,
        post,
        content,
        previous_state
    ):

        thread_id = previous_state.get(
            "thread_id"
        )

        message_id = previous_state.get(
            "message_id"
        )


        # -------------------------------------------------
        # 스레드 가져오기
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

                except Exception:

                    thread = None


        # -------------------------------------------------
        # 기존 스레드를 찾지 못했다면
        # 새 공지처럼 다시 생성
        # -------------------------------------------------

        if thread is None:

            print(
                "[메이플 공지] "
                "기존 스레드를 찾지 못했습니다. "
                "새 스레드를 생성합니다."
            )

            channel_id = (
                MAINTENANCE_CHANNEL_ID
                if notice_type == "maintenance"
                else PATCHNOTE_CHANNEL_ID
            )


            new_data = await self.send_new_notice(
                notice_type,
                post,
                content,
                channel_id
            )

            return new_data


        # -------------------------------------------------
        # 수정 알림
        # -------------------------------------------------

        if notice_type == "maintenance":

            emoji = "🛠️"
            kind = "점검 공지"

        else:

            emoji = "📜"
            kind = "패치노트"


        await thread.send(
            f"{emoji} **{kind}가 수정되었습니다.**\n\n"
            f"📌 **{post['title']}**\n"
            "공식 홈페이지의 내용이 변경되었습니다.\n\n"
            f"🔗 [수정된 원문 보기]({post['url']})"
        )


        # -------------------------------------------------
        # 수정된 본문
        # -------------------------------------------------

        chunks = self.split_message(
            content
        )


        await thread.send(
            "✏️ **수정된 공지 원문**"
        )


        for chunk in chunks:

            await thread.send(
                chunk
            )

            await asyncio.sleep(
                0.3
            )


        await thread.send(
            f"🔗 {post['url']}"
        )


        # -------------------------------------------------
        # 부모 메시지 제목도 수정
        # -------------------------------------------------

        if message_id:

            try:

                channel = thread.parent

                if channel is None:

                    channel = self.bot.get_channel(
                        thread.parent_id
                    )


                if channel:

                    parent_message = await channel.fetch_message(
                        message_id
                    )


                    if notice_type == "maintenance":

                        new_title = (
                            f"🛠️ {post['title']}"
                        )

                        color = 0xF39C12

                    else:

                        new_title = (
                            f"📜 {post['title']}"
                        )

                        color = 0x3498DB


                    embed = discord.Embed(
                        title=new_title,
                        description=(
                            "메이플플래닛 공식 홈페이지의 "
                            "공지가 수정되었습니다.\n\n"
                            f"🔗 [공식 원문]({post['url']})"
                        ),
                        color=color
                    )

                    embed.set_footer(
                        text="MAPLEPLANET 공식 공지 자동 알림"
                    )


                    await parent_message.edit(
                        embed=embed
                    )


            except Exception as e:

                print(
                    "[메이플 공지] "
                    f"부모 메시지 수정 실패: {e}"
                )


        print(
            "[메이플 공지] 수정 공지 반영 완료: "
            + post["title"]
        )


        return {
            "message_id": message_id,
            "thread_id": thread.id
        }


    # =====================================================
    # 공지 확인
    # =====================================================

    async def check_notice(
        self,
        notice_type,
        list_url,
        post_type,
        channel_id
    ):

        try:

            # -------------------------------------------------
            # 최신 게시글
            # -------------------------------------------------

            latest = await self.get_latest_post(
                list_url,
                post_type
            )


            if not latest:

                return


            # -------------------------------------------------
            # 최신 글 본문
            # -------------------------------------------------

            content = await self.get_article_content(
                latest["url"]
            )


            content_hash = self.make_content_hash(
                content
            )


            # -------------------------------------------------
            # 이전 상태
            # -------------------------------------------------

            previous = self.state.get(
                notice_type,
                {}
            )


            previous_url = previous.get(
                "url"
            )

            previous_hash = previous.get(
                "content_hash"
            )


            # =================================================
            # 🆕 최초 실행
            # =================================================

            if not previous_url:

                self.state[notice_type] = {
                    "url": latest["url"],
                    "title": latest["title"],
                    "content_hash": content_hash,
                    "message_id": None,
                    "thread_id": None
                }

                self.save_state()


                print(
                    "[메이플 공지] 최초 실행 - "
                    f"기존 공지 기록: {latest['title']}"
                )

                return


            # =================================================
            # 🆕 새로운 공지
            # =================================================

            if latest["url"] != previous_url:

                result = await self.send_new_notice(
                    notice_type,
                    latest,
                    content,
                    channel_id
                )


                if result:

                    self.state[notice_type] = {
                        "url": latest["url"],
                        "title": latest["title"],
                        "content_hash": content_hash,
                        "message_id": result["message_id"],
                        "thread_id": result["thread_id"]
                    }

                    self.save_state()


                return


            # =================================================
            # ✏️ 기존 공지 수정
            # =================================================

            if content_hash != previous_hash:

                result = await self.update_existing_notice(
                    notice_type,
                    latest,
                    content,
                    previous
                )


                if result:

                    self.state[notice_type] = {
                        "url": latest["url"],
                        "title": latest["title"],
                        "content_hash": content_hash,
                        "message_id": result.get(
                            "message_id"
                        ),
                        "thread_id": result.get(
                            "thread_id"
                        )
                    }

                    self.save_state()


                return


        except Exception as e:

            print(
                "[메이플 공지] 확인 중 오류 "
                f"({notice_type}): {e}"
            )


    # =====================================================
    # 1분마다 공지 확인
    # =====================================================

    @tasks.loop(minutes=1)
    async def notice_checker(self):

        await self.bot.wait_until_ready()


        # -------------------------------------------------
        # 🛠️ 점검
        # -------------------------------------------------

        await self.check_notice(
            notice_type="maintenance",
            list_url=MAINTENANCE_LIST_URL,
            post_type="notices",
            channel_id=MAINTENANCE_CHANNEL_ID
        )


        # -------------------------------------------------
        # 📜 패치노트
        # -------------------------------------------------

        await self.check_notice(
            notice_type="patchnote",
            list_url=PATCHNOTE_LIST_URL,
            post_type="updates",
            channel_id=PATCHNOTE_CHANNEL_ID
        )


    # =====================================================
    # 봇 시작 전 대기
    # =====================================================

    @notice_checker.before_loop
    async def before_notice_checker(self):

        await self.bot.wait_until_ready()


# =========================================================
# Cog 등록
# =========================================================

async def setup(bot):

    await bot.add_cog(
        MaplePlanetNotice(bot)
    )