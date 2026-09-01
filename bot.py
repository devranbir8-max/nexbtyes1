from __future__ import annotations

import os
import logging
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

TOKEN = os.getenv("TOKEN")

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

if not TOKEN:
    raise RuntimeError("TOKEN is missing from .env")

if not OWNER_ID:
    raise RuntimeError("OWNER_ID is missing from .env")

if not GUILD_ID:
    raise RuntimeError("GUILD_ID is missing from .env")


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("PrivateBot")


# ============================================================
# BOT INTENTS
# ============================================================

intents = discord.Intents.default()

intents.message_content = True
intents.members = True


# ============================================================
# BOT
# ============================================================

class PrivateBot(commands.Bot):

    def __init__(self) -> None:
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )

        self._closing = False

    # ========================================================
    # LOAD COGS
    # ========================================================

    async def setup_hook(self) -> None:
        """Automatically load every cog inside /cogs."""

        cogs_path = Path(__file__).parent / "cogs"

        if not cogs_path.exists():
            cogs_path.mkdir(parents=True)

        for file in cogs_path.glob("*.py"):

            if file.name.startswith("_"):
                continue

            extension = f"cogs.{file.stem}"

            try:
                await self.load_extension(extension)

                logger.info(
                    "Loaded cog: %s",
                    extension,
                )

            except Exception:
                logger.exception(
                    "Failed to load cog: %s",
                    extension,
                )

        # ====================================================
        # SYNC SLASH COMMANDS
        # ====================================================

        guild = discord.Object(id=GUILD_ID)

        self.tree.copy_global_to(guild=guild)

        await self.tree.sync(guild=guild)

        logger.info(
            "Slash commands synced to guild %s",
            GUILD_ID,
        )

    # ========================================================
    # READY
    # ========================================================

    async def on_ready(self) -> None:

        logger.info(
            "Logged in as %s (%s)",
            self.user,
            self.user.id,
        )

        logger.info(
            "Private server ID: %s",
            GUILD_ID,
        )

    # ========================================================
    # CLOSE / RESTART STATUS
    # ========================================================

    async def close(self) -> None:

        if self._closing:
            return

        self._closing = True

        logger.info("Bot shutdown requested.")

        # Send RESTARTING status before disconnecting.
        status_cog = self.get_cog("Status")

        if status_cog is not None:

            try:
                await status_cog.send_restarting()

            except Exception:
                logger.exception(
                    "Failed to send restarting status."
                )

        await super().close()


bot = PrivateBot()


# ============================================================
# GLOBAL OWNER + SERVER CHECK
# ============================================================

@bot.check
async def private_bot_check(
    ctx: commands.Context,
) -> bool:

    # Ignore DMs.
    if ctx.guild is None:
        return False

    # Only allow configured server.
    if ctx.guild.id != GUILD_ID:
        return False

    # Only allow owner.
    if ctx.author.id != OWNER_ID:
        return False

    return True


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    bot.run(TOKEN)
