# cogs/feedback.py

from __future__ import annotations

import json
import os
from typing import Optional

import discord
from discord.ext import commands


# ============================================================
# CONFIG
# ============================================================

CONFIG_FILE = "feedback_config.json"

WHITE = 0xFFFFFF
RED = 0xED4245
GREEN = 0x57F287

STARRY = "<a:starry:1544343086962970624>"


# ============================================================
# CONFIG STORAGE
# ============================================================

def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}

    try:
        with open(
            CONFIG_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if isinstance(data, dict):
            return data

    except (
        OSError,
        json.JSONDecodeError,
    ):
        pass

    return {}


def save_config(data: dict) -> None:
    temp_file = f"{CONFIG_FILE}.tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            indent=4,
        )

    os.replace(
        temp_file,
        CONFIG_FILE,
    )


# ============================================================
# STARS
# ============================================================

def get_stars(rating: int) -> str:
    return " ".join(
        STARRY
        for _ in range(5)
    )


# ============================================================
# FEEDBACK COLOUR
# ============================================================

def get_rating_colour(
    rating: int,
) -> discord.Colour:

    # 1-3 = RED
    if rating <= 3:
        return discord.Colour(RED)

    # 4-5 = GREEN
    return discord.Colour(GREEN)


# ============================================================
# SIMPLE CV2 MESSAGE
# ============================================================

class SimpleView(
    discord.ui.LayoutView
):

    def __init__(
        self,
        title: str,
        description: str,
        colour: int = WHITE,
    ):
        super().__init__(
            timeout=120
        )

        container = discord.ui.Container(
            discord.ui.TextDisplay(
                f"## {title}"
            ),

            discord.ui.Separator(),

            discord.ui.TextDisplay(
                description
            ),

            accent_color=discord.Colour(
                colour
            ),
        )

        self.add_item(
            container
        )


# ============================================================
# MAIN FEEDBACK PANEL
# ============================================================

class FeedbackPanelView(
    discord.ui.LayoutView
):

    def __init__(self):
        super().__init__(
            timeout=None
        )

        container = discord.ui.Container(

            discord.ui.TextDisplay(
                "## New Feedback"
            ),

            discord.ui.Separator(),

            discord.ui.TextDisplay(
                "We would love to hear your feedback.\n"
                "Click the button below to leave a review."
            ),

            discord.ui.Separator(),

            discord.ui.ActionRow(
                LeaveReviewButton()
            ),

            # WHITE
            accent_color=discord.Colour(
                WHITE
            ),
        )

        self.add_item(
            container
        )


# ============================================================
# LEAVE REVIEW BUTTON
# ============================================================

class LeaveReviewButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="Leave a review",
            style=discord.ButtonStyle.secondary,

            # IMPORTANT:
            # This custom_id never changes.
            # It allows the button to keep working
            # after a bot restart.
            custom_id="feedback:leave_review",
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.send_message(
            view=RatingView(),
            ephemeral=True,
        )


# ============================================================
# RATING VIEW
# ============================================================

class RatingView(
    discord.ui.LayoutView
):

    def __init__(self):

        super().__init__(
            timeout=300
        )

        container = discord.ui.Container(

            discord.ui.TextDisplay(
                "## Your Rating"
            ),

            discord.ui.Separator(),

            discord.ui.TextDisplay(
                "Choose a rating from 1 to 5."
            ),

            discord.ui.Separator(),

            discord.ui.ActionRow(
                RatingButton(1),
                RatingButton(2),
                RatingButton(3),
                RatingButton(4),
                RatingButton(5),
            ),

            accent_color=discord.Colour(
                WHITE
            ),
        )

        self.add_item(
            container
        )


# ============================================================
# RATING BUTTON
# ============================================================

class RatingButton(
    discord.ui.Button
):

    def __init__(
        self,
        rating: int,
    ):

        self.rating = rating

        if rating <= 3:
            style = discord.ButtonStyle.danger
        else:
            style = discord.ButtonStyle.success

        super().__init__(
            label=f"{rating} / 5",
            style=style,

            # Unique persistent ID.
            custom_id=f"feedback:rating:{rating}",
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.send_modal(
            FeedbackModal(
                rating=self.rating
            )
        )


# ============================================================
# FEEDBACK MODAL
# ============================================================

class FeedbackModal(
    discord.ui.Modal
):

    def __init__(
        self,
        rating: int,
    ):

        super().__init__(
            title=f"Feedback - {rating}/5",
            timeout=300,
        )

        self.rating = rating

        self.review = discord.ui.TextInput(
            label="Your review",
            placeholder="Tell us what you think...",
            style=discord.TextStyle.paragraph,
            required=True,
            min_length=3,
            max_length=1000,
        )

        self.add_item(
            self.review
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):

        cog = interaction.client.get_cog(
            "Feedback"
        )

        if cog is None:

            await interaction.response.send_message(
                view=SimpleView(
                    "Unavailable",
                    "The feedback system is currently unavailable.",
                    RED,
                ),
                ephemeral=True,
            )

            return

        await cog.submit_feedback(
            interaction=interaction,
            rating=self.rating,
            review=str(
                self.review.value
            ).strip(),
        )


# ============================================================
# SUBMITTED FEEDBACK
# ============================================================

class SubmittedFeedbackView(
    discord.ui.LayoutView
):

    def __init__(
        self,
        user: discord.abc.User,
        rating: int,
        review: str,
    ):

        super().__init__(
            timeout=None
        )

        username = getattr(
            user,
            "display_name",
            user.name,
        )

        avatar_url = str(
            user.display_avatar.url
        )

        stars = get_stars(
            rating
        )

        # ----------------------------------------------------
        # Main feedback text
        # ----------------------------------------------------

        feedback_text = discord.ui.TextDisplay(

            "## New Feedback\n\n"

            f"> {review}\n\n"

            f"{stars}\n"
            f"**Rating:** {rating} / 5\n\n"

            f"**User:** {username}\n"
            f"**User ID:** `{user.id}`"
        )

        # ----------------------------------------------------
        # User avatar
        # ----------------------------------------------------

        try:

            thumbnail = discord.ui.Thumbnail(
                media=avatar_url
            )

            section = discord.ui.Section(
                feedback_text,
                accessory=thumbnail,
            )

            container = discord.ui.Container(

                section,

                discord.ui.Separator(),

                discord.ui.ActionRow(
                    LeaveReviewButton()
                ),

                accent_color=get_rating_colour(
                    rating
                ),
            )

        except Exception:

            # Safe fallback for Discord.py versions
            # that don't support the thumbnail format.

            container = discord.ui.Container(

                feedback_text,

                discord.ui.Separator(),

                discord.ui.ActionRow(
                    LeaveReviewButton()
                ),

                accent_color=get_rating_colour(
                    rating
                ),
            )

        self.add_item(
            container
        )


# ============================================================
# HELP VIEW
# ============================================================

class FeedbackHelpView(
    discord.ui.LayoutView
):

    def __init__(self):

        super().__init__(
            timeout=120
        )

        container = discord.ui.Container(

            discord.ui.TextDisplay(
                "## Feedback System"
            ),

            discord.ui.Separator(),

            discord.ui.TextDisplay(

                "**Commands**\n\n"

                "`!feedback help`\n"
                "Show feedback commands.\n\n"

                "`!feedback channel set`\n"
                "Set the current channel as the feedback channel.\n\n"

                "`!feedback channel set #channel`\n"
                "Set a specific feedback channel.\n\n"

                "`!feedback start`\n"
                "Send the feedback panel."
            ),

            accent_color=discord.Colour(
                WHITE
            ),
        )

        self.add_item(
            container
        )


# ============================================================
# FEEDBACK COG
# ============================================================

class Feedback(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ):

        self.bot = bot

        # Load saved channel configuration.
        self.config = load_config()

    # ========================================================
    # COG LOAD
    # ========================================================

    async def cog_load(self):

        # IMPORTANT:
        #
        # Register the persistent panel view AFTER the bot
        # is loading the cog.
        #
        # Because timeout=None and every button has a fixed
        # custom_id, old panels continue working after restart.

        self.bot.add_view(
            FeedbackPanelView()
        )

    # ========================================================
    # !feedback
    # ========================================================

    @commands.group(
        name="feedback",
        aliases=["fb"],
        invoke_without_command=True,
        case_insensitive=True,
    )
    async def feedback(
        self,
        ctx: commands.Context,
    ):

        await ctx.send(
            view=FeedbackHelpView()
        )

    # ========================================================
    # !feedback help
    # ========================================================

    @feedback.command(
        name="help"
    )
    async def feedback_help(
        self,
        ctx: commands.Context,
    ):

        await ctx.send(
            view=FeedbackHelpView()
        )

    # ========================================================
    # !feedback channel
    # ========================================================

    @feedback.group(
        name="channel",
        invoke_without_command=True,
        case_insensitive=True,
    )
    @commands.guild_only()
    async def feedback_channel(
        self,
        ctx: commands.Context,
    ):

        if not self.is_staff(ctx):

            await self.send_permission_error(
                ctx
            )

            return

        guild_id = str(
            ctx.guild.id
        )

        channel_id = self.config.get(
            guild_id
        )

        if channel_id:

            channel = ctx.guild.get_channel(
                int(channel_id)
            )

            if channel:

                await ctx.send(
                    view=SimpleView(
                        "Feedback Channel",
                        f"Current feedback channel: {channel.mention}",
                        WHITE,
                    )
                )

                return

        await ctx.send(
            view=SimpleView(
                "Feedback Channel",
                "No feedback channel has been configured.\n\n"
                "`!feedback channel set #feedback`",
                WHITE,
            )
        )

    # ========================================================
    # !feedback channel set
    # ========================================================

    @feedback_channel.command(
        name="set",
        aliases=["setup"],
    )
    @commands.guild_only()
    async def feedback_channel_set(
        self,
        ctx: commands.Context,
        channel: Optional[discord.TextChannel] = None,
    ):

        if not self.is_staff(ctx):

            await self.send_permission_error(
                ctx
            )

            return

        target = channel or ctx.channel

        if not isinstance(
            target,
            discord.TextChannel,
        ):

            await ctx.send(
                view=SimpleView(
                    "Invalid Channel",
                    "Please provide a normal text channel.",
                    RED,
                )
            )

            return

        guild_id = str(
            ctx.guild.id
        )

        # Save permanently.
        self.config[guild_id] = target.id

        save_config(
            self.config
        )

        await ctx.send(
            view=SimpleView(
                "Feedback Channel Set",
                f"Feedback channel has been set to {target.mention}.\n\n"
                "Use `!feedback start` to send the panel.",
                GREEN,
            )
        )

    # ========================================================
    # !feedback start
    # ========================================================

    @feedback.command(
        name="start"
    )
    @commands.guild_only()
    async def feedback_start(
        self,
        ctx: commands.Context,
    ):

        if not self.is_staff(ctx):

            await self.send_permission_error(
                ctx
            )

            return

        guild_id = str(
            ctx.guild.id
        )

        channel_id = self.config.get(
            guild_id
        )

        if not channel_id:

            await ctx.send(
                view=SimpleView(
                    "Feedback Channel Not Set",
                    "Set the feedback channel first.\n\n"
                    "`!feedback channel set #feedback`",
                    RED,
                )
            )

            return

        channel = ctx.guild.get_channel(
            int(channel_id)
        )

        if channel is None:

            await ctx.send(
                view=SimpleView(
                    "Channel Not Found",
                    "The configured feedback channel could not be found.\n\n"
                    "Set it again with:\n"
                    "`!feedback channel set #feedback`",
                    RED,
                )
            )

            return

        try:

            await channel.send(
                view=FeedbackPanelView()
            )

        except discord.Forbidden:

            await ctx.send(
                view=SimpleView(
                    "Permission Error",
                    f"I cannot send messages in {channel.mention}.",
                    RED,
                )
            )

            return

        except discord.HTTPException:

            await ctx.send(
                view=SimpleView(
                    "Error",
                    "Discord rejected the feedback panel.",
                    RED,
                )
            )

            return

        await ctx.send(
            view=SimpleView(
                "Feedback Panel Sent",
                f"The feedback panel has been sent to {channel.mention}.",
                GREEN,
            )
        )

    # ========================================================
    # SUBMIT FEEDBACK
    # ========================================================

    async def submit_feedback(
        self,
        interaction: discord.Interaction,
        rating: int,
        review: str,
    ):

        if not interaction.guild:

            await interaction.response.send_message(
                view=SimpleView(
                    "Unavailable",
                    "Feedback can only be submitted inside a server.",
                    RED,
                ),
                ephemeral=True,
            )

            return

        # ----------------------------------------------------
        # Rating validation
        # ----------------------------------------------------

        if rating < 1 or rating > 5:

            await interaction.response.send_message(
                view=SimpleView(
                    "Invalid Rating",
                    "Please select a rating from 1 to 5.",
                    RED,
                ),
                ephemeral=True,
            )

            return

        # ----------------------------------------------------
        # Review validation
        # ----------------------------------------------------

        review = review.strip()

        if not review:

            await interaction.response.send_message(
                view=SimpleView(
                    "Invalid Feedback",
                    "Please write a review before submitting.",
                    RED,
                ),
                ephemeral=True,
            )

            return

        if len(review) < 3:

            await interaction.response.send_message(
                view=SimpleView(
                    "Feedback Too Short",
                    "Please write a little more about your experience.",
                    RED,
                ),
                ephemeral=True,
            )

            return

        if len(review) > 1000:

            await interaction.response.send_message(
                view=SimpleView(
                    "Feedback Too Long",
                    "Your feedback must be 1000 characters or less.",
                    RED,
                ),
                ephemeral=True,
            )

            return

        # ----------------------------------------------------
        # Find channel
        # ----------------------------------------------------

        guild_id = str(
            interaction.guild.id
        )

        channel_id = self.config.get(
            guild_id
        )

        if not channel_id:

            await interaction.response.send_message(
                view=SimpleView(
                    "Feedback Unavailable",
                    "The feedback channel has not been configured.",
                    RED,
                ),
                ephemeral=True,
            )

            return

        channel = interaction.guild.get_channel(
            int(channel_id)
        )

        if channel is None:

            await interaction.response.send_message(
                view=SimpleView(
                    "Channel Missing",
                    "The configured feedback channel could not be found.",
                    RED,
                ),
                ephemeral=True,
            )

            return

        # ----------------------------------------------------
        # Defer
        # ----------------------------------------------------

        await interaction.response.defer(
            ephemeral=True
        )

        # ----------------------------------------------------
        # Send feedback
        # ----------------------------------------------------

        try:

            await channel.send(
                view=SubmittedFeedbackView(
                    user=interaction.user,
                    rating=rating,
                    review=review,
                )
            )

        except discord.Forbidden:

            await interaction.followup.send(
                view=SimpleView(
                    "Permission Error",
                    "I cannot send feedback to the configured channel.",
                    RED,
                ),
                ephemeral=True,
            )

            return

        except discord.HTTPException:

            await interaction.followup.send(
                view=SimpleView(
                    "Submission Failed",
                    "Discord rejected the feedback message. Please try again.",
                    RED,
                ),
                ephemeral=True,
            )

            return

        # ----------------------------------------------------
        # Success message
        # ----------------------------------------------------

        await interaction.followup.send(
            view=SimpleView(
                "Thank You",
                "Your feedback has been submitted successfully.\n\n"
                "We appreciate you taking the time to leave a review.",
                GREEN,
            ),
            ephemeral=True,
        )

        # ----------------------------------------------------
        # DM
        # ----------------------------------------------------

        await self.send_feedback_dm(
            user=interaction.user,
            rating=rating,
        )

    # ========================================================
    # USER DM
    # ========================================================

    async def send_feedback_dm(
        self,
        user: discord.abc.User,
        rating: int,
    ):

        # 1-3 = bad feedback
        if rating <= 3:

            title = "We received your feedback"

            description = (
                "Thank you for taking the time to leave feedback.\n\n"
                f"Your rating: **{rating} / 5**\n\n"
                "We're sorry that your experience wasn't as good "
                "as it should have been.\n\n"
                "If you need help with something, you can create "
                "a support ticket and our team will be happy to "
                "help you.\n\n"
                "We'd really appreciate the chance to make things better."
            )

            colour = RED

        # 4-5 = good feedback
        else:

            title = "Thank you for your feedback"

            description = (
                "Thank you for taking the time to leave feedback.\n\n"
                f"Your rating: **{rating} / 5**\n\n"
                "We really appreciate your support and we're glad "
                "you had a good experience.\n\n"
                "Your feedback helps us keep improving."
            )

            colour = GREEN

        try:

            await user.send(
                view=SimpleView(
                    title,
                    description,
                    colour,
                )
            )

        except discord.Forbidden:
            # DMs disabled.
            pass

        except discord.HTTPException:
            pass

    # ========================================================
    # STAFF
    # ========================================================

    @staticmethod
    def is_staff(
        ctx: commands.Context,
    ) -> bool:

        if not ctx.guild:
            return False

        permissions = (
            ctx.author.guild_permissions
        )

        return (
            permissions.administrator
            or permissions.manage_guild
        )

    # ========================================================
    # PERMISSION ERROR
    # ========================================================

    @staticmethod
    async def send_permission_error(
        ctx: commands.Context,
    ):

        await ctx.send(
            view=SimpleView(
                "Permission Denied",
                "You need Administrator or Manage Server permission to use this command.",
                RED,
            )
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        Feedback(bot)
    )