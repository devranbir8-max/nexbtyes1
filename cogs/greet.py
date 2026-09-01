from __future__ import annotations

import json
import logging
from pathlib import Path

import discord
from discord.ext import commands


# ============================================================
# CONFIG
# ============================================================

DEFAULT_GREET_CHANNEL_ID = 1540650928019865630

CONFIG_FILE = Path(__file__).resolve().parent.parent / "greet_config.json"

logger = logging.getLogger("PrivateBot.Greet")


# ============================================================
# CONFIG MANAGER
# ============================================================

def load_config() -> dict:
    """
    Load greet configuration from greet_config.json.
    """

    if not CONFIG_FILE.exists():
        return {
            "channel_id": DEFAULT_GREET_CHANNEL_ID
        }

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        channel_id = data.get("channel_id")

        if not isinstance(channel_id, int):
            channel_id = DEFAULT_GREET_CHANNEL_ID

        return {
            "channel_id": channel_id
        }

    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        logger.exception("Failed to load greet_config.json")

        return {
            "channel_id": DEFAULT_GREET_CHANNEL_ID
        }


def save_config(channel_id: int) -> bool:
    """
    Save greet configuration.
    """

    try:
        with CONFIG_FILE.open("w", encoding="utf-8") as file:
            json.dump(
                {
                    "channel_id": channel_id
                },
                file,
                indent=4
            )

        return True

    except OSError:
        logger.exception("Failed to save greet_config.json")
        return False


# ============================================================
# COMPONENTS V2
# ============================================================

class GreetView(discord.ui.LayoutView):
    """
    Components V2 welcome message.
    """

    def __init__(self, member: discord.Member):
        super().__init__(timeout=None)

        # ----------------------------------------------------
        # Mention
        # ----------------------------------------------------

        self.add_item(
            discord.ui.TextDisplay(
                content=f"<:cute:1544331277430161519> {member.mention}"
            )
        )

        # ----------------------------------------------------
        # Main Container
        # ----------------------------------------------------

        self.add_item(
            discord.ui.Container(
                discord.ui.Section(
                    discord.ui.TextDisplay(
                        content=(
                            "### welcome to Nexbyte Headquarters\n"
                            "> <:dot8:1544330803910283275> "
                            "https://discord.com/channels/"
                            "1540639437871120385/"
                            "1540639566954766387\n"
                            "> <:dot8:1544330803910283275> "
                            "https://discord.com/channels/"
                            "1540639437871120385/"
                            "1540648940888784988\n"
                            "> <:dot8:1544330803910283275> "
                            "https://discord.com/channels/"
                            "1540639437871120385/"
                            "1540649738519584778"
                        )
                    ),

                    accessory=discord.ui.Thumbnail(
                        media=member.display_avatar.url
                    ),
                ),

                # White container
            accent_color=discord.Color.from_str("#FFFFFF")
            )
        )


# ============================================================
# HELP COMPONENTS
# ============================================================

class GreetHelpView(discord.ui.LayoutView):
    """
    Components V2 help panel for the greet system.
    """

    def __init__(self):
        super().__init__(timeout=60)

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    content=(
                        "## Greet Commands\n\n"
                        "**`!greet test`**\n"
                        "> Send a test welcome message.\n\n"
                        "**`!greet channel set #channel`**\n"
                        "> Set the channel where welcome messages are sent.\n\n"
                        "**`!greet channel show`**\n"
                        "> Show the currently configured greeting channel.\n\n"
                        "**`!greet help`**\n"
                        "> Show this help panel."
                    )
                ),

                discord.ui.Separator(),

                discord.ui.TextDisplay(
                    content=(
                        "**Example**\n"
                        "`!greet channel set #welcome`\n\n"
                        "The bot will automatically greet new members "
                        "in the configured channel."
                    )
                ),

                accent_color=discord.Color.from_str("#FFFFFF")
            )
        )


# ============================================================
# GREET COG
# ============================================================

class Greet(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        config = load_config()
        self.channel_id: int = config["channel_id"]

        logger.info(
            "Greet cog loaded | Channel ID: %s",
            self.channel_id
        )

    # ========================================================
    # INTERNAL
    # ========================================================

    def get_greet_channel(
        self,
        guild: discord.Guild
    ) -> discord.TextChannel | None:
        """
        Get the configured greeting channel.
        """

        channel = guild.get_channel(self.channel_id)

        if isinstance(channel, discord.TextChannel):
            return channel

        return None

    async def send_greeting(
        self,
        channel: discord.TextChannel,
        member: discord.Member
    ) -> bool:
        """
        Send the welcome Components V2 message.
        """

        try:
            view = GreetView(member)

            await channel.send(
                view=view,
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False
                )
            )

            return True

        except discord.Forbidden:
            logger.error(
                "No permission to send greeting in #%s (%s)",
                channel.name,
                channel.id
            )

            return False

        except discord.HTTPException as error:
            logger.error(
                "Discord API error while sending greeting: %s",
                error
            )

            return False

        except Exception:
            logger.exception(
                "Unexpected error while sending greeting"
            )

            return False

    # ========================================================
    # MEMBER JOIN
    # ========================================================

    @commands.Cog.listener()
    async def on_member_join(
        self,
        member: discord.Member
    ):
        """
        Automatically greet new members.
        """

        logger.info(
            "Member joined: %s (%s) in %s (%s)",
            member,
            member.id,
            member.guild.name,
            member.guild.id
        )

        channel = self.get_greet_channel(member.guild)

        if channel is None:
            logger.warning(
                "Configured greet channel %s was not found "
                "in guild %s",
                self.channel_id,
                member.guild.id
            )
            return

        success = await self.send_greeting(
            channel,
            member
        )

        if success:
            logger.info(
                "Welcome message sent for %s in #%s",
                member,
                channel.name
            )

    # ========================================================
    # !GREET
    # ========================================================

    @commands.group(
        name="greet",
        invoke_without_command=True
    )
    @commands.guild_only()
    async def greet(
        self,
        ctx: commands.Context
    ):
        """
        Greet system commands.
        """

        await ctx.send(
            "Use `!greet help` to see all available greet commands.",
            delete_after=10
        )

    # ========================================================
    # !GREET HELP
    # ========================================================

    @greet.command(name="help")
    async def greet_help(
        self,
        ctx: commands.Context
    ):
        """
        Show greet command help.
        """

        await ctx.send(
            view=GreetHelpView()
        )

    # ========================================================
    # !GREET TEST
    # ========================================================

    @greet.command(name="test")
    async def greet_test(
        self,
        ctx: commands.Context
    ):
        """
        Send a test greeting using the command user.
        """

        channel = self.get_greet_channel(ctx.guild)

        if channel is None:
            await ctx.send(
                "The configured greeting channel could not be found.",
                delete_after=10
            )
            return

        success = await self.send_greeting(
            channel,
            ctx.author
        )

        if success:
            await ctx.send(
                f"Test greeting sent in {channel.mention}.",
                delete_after=10
            )
        else:
            await ctx.send(
                "I couldn't send the test greeting. "
                "Check my permissions in the greeting channel.",
                delete_after=10
            )

    # ========================================================
    # !GREET CHANNEL
    # ========================================================

    @greet.group(
        name="channel",
        invoke_without_command=True
    )
    async def greet_channel(
        self,
        ctx: commands.Context
    ):
        """
        Greeting channel commands.
        """

        await ctx.send(
            "Use `!greet channel set #channel` or "
            "`!greet channel show`.",
            delete_after=10
        )

    # ========================================================
    # !GREET CHANNEL SET
    # ========================================================

    @greet_channel.command(name="set")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def greet_channel_set(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel
    ):
        """
        Set the greeting channel.
        """

        self.channel_id = channel.id

        if not save_config(self.channel_id):
            await ctx.send(
                "The channel was changed, but I couldn't save the "
                "configuration to disk.",
                delete_after=10
            )
            return

        await ctx.send(
            f"Greeting channel has been set to {channel.mention}.",
            delete_after=10
        )

        logger.info(
            "Greeting channel changed to #%s (%s) by %s (%s)",
            channel.name,
            channel.id,
            ctx.author,
            ctx.author.id
        )

    # ========================================================
    # !GREET CHANNEL SHOW
    # ========================================================

    @greet_channel.command(name="show")
    @commands.guild_only()
    async def greet_channel_show(
        self,
        ctx: commands.Context
    ):
        """
        Show current greeting channel.
        """

        channel = self.get_greet_channel(ctx.guild)

        if channel is None:
            await ctx.send(
                f"Configured channel ID: `{self.channel_id}`\n"
                "I cannot find this channel in this server.",
                delete_after=10
            )
            return

        await ctx.send(
            f"Current greeting channel: {channel.mention}",
            delete_after=10
        )

    # ========================================================
    # COMMAND ERROR HANDLER
    # ========================================================

    @greet.error
    async def greet_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError
    ):
        if isinstance(error, commands.NoPrivateMessage):
            return

        if isinstance(error, commands.MissingPermissions):
            await ctx.send(
                "You need Administrator permission to use that command.",
                delete_after=10
            )
            return

        if isinstance(error, commands.ChannelNotFound):
            await ctx.send(
                "I couldn't find that channel. Use a channel mention, "
                "for example: `!greet channel set #welcome`.",
                delete_after=10
            )
            return

        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                "You're missing a required argument.\n"
                "Use `!greet help` for the correct syntax.",
                delete_after=10
            )
            return

        logger.error(
            "Greet command error: %s",
            error,
            exc_info=True
        )

        await ctx.send(
            "Something went wrong while processing the greet command.",
            delete_after=10
        )


# ============================================================
# SETUP
# ============================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(Greet(bot))