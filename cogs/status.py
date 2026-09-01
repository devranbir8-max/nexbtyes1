from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

import discord
from discord.ext import commands


logger = logging.getLogger("PrivateBot.Status")

STATUS_CHANNEL_ID = 1540649329008705598
OWNER_ID = 1438898463038509159

WEBHOOK_NAME = "PrivateBot Status"


class Status(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.webhook: discord.Webhook | None = None
        self._online_sent = False
        self._closing = False

    # =========================================================
    # OWNER CHECK
    # =========================================================

    async def cog_check(self, ctx: commands.Context) -> bool:
        return ctx.author.id == OWNER_ID

    # =========================================================
    # STATUS CHANNEL
    # =========================================================

    async def get_status_channel(
        self,
    ) -> discord.TextChannel | None:

        channel = self.bot.get_channel(STATUS_CHANNEL_ID)

        if channel is None:
            try:
                channel = await self.bot.fetch_channel(
                    STATUS_CHANNEL_ID
                )
            except Exception:
                logger.exception(
                    "Could not fetch status channel."
                )
                return None

        if not isinstance(channel, discord.TextChannel):
            logger.error(
                "Status channel is not a text channel."
            )
            return None

        return channel

    # =========================================================
    # WEBHOOK
    # =========================================================

    async def get_webhook(
        self,
        channel: discord.TextChannel,
    ) -> discord.Webhook | None:

        if self.webhook is not None:
            return self.webhook

        try:
            webhooks = await channel.webhooks()

            for webhook in webhooks:

                if webhook.name != WEBHOOK_NAME:
                    continue

                if webhook.user is None:
                    continue

                if self.bot.user is None:
                    continue

                if webhook.user.id != self.bot.user.id:
                    continue

                self.webhook = webhook

                logger.info(
                    "Reusing status webhook: %s",
                    webhook.id,
                )

                return webhook

            webhook = await channel.create_webhook(
                name=WEBHOOK_NAME,
                reason="PrivateBot status system",
            )

            self.webhook = webhook

            logger.info(
                "Created status webhook: %s",
                webhook.id,
            )

            return webhook

        except discord.Forbidden:
            logger.warning(
                "Manage Webhooks permission unavailable. "
                "Using normal bot messages."
            )

        except discord.HTTPException:
            logger.exception(
                "Failed to create/get status webhook."
            )

        return None

    # =========================================================
    # CV2 STATUS CONTAINER
    # =========================================================

    def create_container(
        self,
        title: str,
        description: str,
    ) -> discord.ui.Container:

        return discord.ui.Container(
            discord.ui.TextDisplay(
                content=f"# {title}"
            ),

            discord.ui.Separator(),

            discord.ui.TextDisplay(
                content=description
            ),

            accent_color=discord.Color.from_rgb(
                255,
                255,
                255,
            ),
        )

    # =========================================================
    # SEND STATUS
    # =========================================================

    async def send_status(
        self,
        title: str,
        description: str,
    ) -> None:

        channel = await self.get_status_channel()

        if channel is None:
            return

        view = discord.ui.LayoutView()

        view.add_item(
            self.create_container(
                title=title,
                description=description,
            )
        )

        # -----------------------------------------------------
        # WEBHOOK
        # -----------------------------------------------------

        webhook = await self.get_webhook(channel)

        if webhook is not None:

            try:
                await webhook.send(
                    view=view,
                    username=(
                        self.bot.user.name
                        if self.bot.user
                        else "PrivateBot"
                    ),
                    avatar_url=(
                        self.bot.user.display_avatar.url
                        if self.bot.user
                        else discord.utils.MISSING
                    ),
                    wait=True,
                )

                logger.info(
                    "Status sent through webhook: %s",
                    title,
                )

                return

            except discord.NotFound:
                self.webhook = None

            except discord.Forbidden:
                self.webhook = None

            except discord.HTTPException:
                logger.exception(
                    "Webhook status send failed."
                )

        # -----------------------------------------------------
        # NORMAL BOT MESSAGE FALLBACK
        # -----------------------------------------------------

        try:
            await channel.send(view=view)

        except discord.Forbidden:
            logger.error(
                "Cannot send status message."
            )

        except discord.HTTPException:
            logger.exception(
                "Failed to send status message."
            )

    # =========================================================
    # ONLINE
    # =========================================================

    @commands.Cog.listener()
    async def on_ready(self):

        if self._online_sent:
            return

        self._online_sent = True

        await self.send_status(
            "Bot Online",
            (
                "The bot is now **online** and ready.\n\n"
                "All systems have been initialized successfully."
            ),
        )

    # =========================================================
    # HELP
    # =========================================================

    @commands.group(
        name="status",
        invoke_without_command=True,
    )
    async def status(
        self,
        ctx: commands.Context,
    ):
        await self.status_help(ctx)

    @status.command(name="help")
    async def status_help(
        self,
        ctx: commands.Context,
    ):

        view = discord.ui.LayoutView()

        view.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    content="# Status Commands"
                ),

                discord.ui.Separator(),

                discord.ui.TextDisplay(
                    content=(
                        "**`!status help`**\n"
                        "Show this command list.\n\n"

                        "**`!status restart`**\n"
                        "Restart the bot process.\n\n"

                        "**`!status stop`**\n"
                        "Gracefully stop the bot.\n\n"

                        "**`!status kill`**\n"
                        "Immediately terminate the bot process.\n\n"

                        "**`!status start`**\n"
                        "Start the bot process if it is not running.\n\n"

                        "Only the configured bot owner can use "
                        "these commands."
                    )
                ),

                accent_color=discord.Color.from_rgb(
                    255,
                    255,
                    255,
                ),
            )
        )

        await ctx.send(view=view)

    # =========================================================
    # RESTART
    # =========================================================

    @status.command(name="restart")
    async def status_restart(
        self,
        ctx: commands.Context,
    ):

        await ctx.message.delete()

        await self.send_status(
            "Bot Restarting",
            (
                "The bot is restarting.\n"
                "Services will be available again shortly."
            ),
        )

        await asyncio.sleep(1)

        python = sys.executable
        script = str(
            Path(__file__).resolve().parent.parent / "bot.py"
        )

        try:
            subprocess.Popen(
                [python, script],
                cwd=str(Path(script).parent),
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    if os.name == "nt"
                    else 0
                ),
            )

        except Exception:
            logger.exception(
                "Failed to start replacement process."
            )
            return

        await self.bot.close()

    # =========================================================
    # STOP
    # =========================================================

    @status.command(name="stop")
    async def status_stop(
        self,
        ctx: commands.Context,
    ):

        await ctx.message.delete()

        await self.send_status(
            "Bot Stopping",
            (
                "The bot is shutting down normally.\n"
                "All services are being stopped."
            ),
        )

        await asyncio.sleep(1)

        await self.bot.close()

    # =========================================================
    # KILL
    # =========================================================

    @status.command(name="kill")
    async def status_kill(
        self,
        ctx: commands.Context,
    ):

        await ctx.message.delete()

        await self.send_status(
            "Bot Terminating",
            (
                "The bot process is being terminated "
                "immediately."
            ),
        )

        await asyncio.sleep(0.5)

        # Immediate process termination.
        os._exit(0)

    # =========================================================
    # START
    # =========================================================

    @status.command(name="start")
    async def status_start(
        self,
        ctx: commands.Context,
    ):

        # If this command is executing, the bot is already running.
        await ctx.send(
            "The bot is already running."
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Status(bot))
