# cogs/order.py
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from html import escape
from typing import Optional
from urllib.parse import quote

import discord
import qrcode
from PIL import Image, ImageDraw, ImageFont
import textwrap
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# ============================================================
# CONFIG
# ============================================================

OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# Users can type anything in this channel to create an order.
DEFAULT_ORDER_CHANNEL_ID = int(
    os.getenv("ORDER_CHANNEL_ID", "1540649970921644073")
)

# Transcript screenshots are sent here.
TRANSCRIPT_CHANNEL_ID = int(
    os.getenv("TRANSCRIPT_CHANNEL_ID", "1544356291257041006")
)

# Optional category. If 0, the trigger channel's category is used.
ORDER_CATEGORY_ID = int(os.getenv("ORDER_CATEGORY_ID", "0"))

ORDER_STAFF_ROLE_ID = int(
    os.getenv("ORDER_STAFF_ROLE_ID", "1540937913607528499")
)
ORDER_STAFF_ROLE_NAME = (
    os.getenv("ORDER_STAFF_ROLE_NAME", "Nexbytes Order Staff").strip()
    or "Nexbytes Order Staff"
)

# The QR contains ONLY this UPI address + amount + INR currency.
UPI_ID = os.getenv("UPI_ID", "lord.tiwari@fam").strip() or "lord.tiwari@fam"

DATABASE_PATH = os.getenv("ORDER_DATABASE", "data/orders.db")

# ============================================================
# STATUS
# ============================================================

STATUS_PENDING = "Pending"
STATUS_CONFIRMED = "Confirmed"
STATUS_PAYMENT_PENDING = "Payment Pending"
STATUS_COMPLETED = "Completed"
STATUS_CANCELLED = "Cancelled"

# Only success/error panels use accent colours.
GREEN = 0x22C55E
RED = 0xEF4444

# ============================================================
# BASIC HELPERS
# ============================================================


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_owner(user: discord.abc.User) -> bool:
    return OWNER_ID != 0 and user.id == OWNER_ID


def is_staff(user: discord.Member) -> bool:
    if is_owner(user):
        return True

    if getattr(user.guild_permissions, "administrator", False):
        return True

    if ORDER_STAFF_ROLE_ID:
        role = user.guild.get_role(ORDER_STAFF_ROLE_ID)
        if role and role in user.roles:
            return True

    role = discord.utils.get(
        user.roles,
        name=ORDER_STAFF_ROLE_NAME,
    )
    return role is not None


def safe_channel_name(display_name: str) -> str:
    value = re.sub(
        r"[^a-z0-9-]+",
        "-",
        display_name.lower(),
    ).strip("-")

    return (value[:45] or "customer")


def parse_amount(value: str) -> str:
    raw = (
        value.strip()
        .replace("₹", "")
        .replace(",", "")
    )

    try:
        amount = float(raw)
    except ValueError as exc:
        raise ValueError(
            "Enter a valid positive amount, for example `199`."
        ) from exc

    if amount <= 0:
        raise ValueError(
            "Enter a valid positive amount, for example `199`."
        )

    return f"{amount:.2f}".rstrip("0").rstrip(".")


def make_upi_qr(amount: str) -> io.BytesIO:
    """
    QR payload intentionally contains only:
      pa = lord.tiwari@fam
      am = entered amount
      cu = INR

    No payee name is added.
    """
    payload = (
        "upi://pay?"
        f"pa={quote(UPI_ID, safe='')}"
        f"&am={quote(amount, safe='')}"
        "&cu=INR"
    )

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    image = qr.make_image()

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


# ============================================================
# COMPONENTS V2 HELPERS
# ============================================================


def text_component(content: str) -> discord.ui.TextDisplay:
    return discord.ui.TextDisplay(content=content)


def separator() -> discord.ui.Separator:
    return discord.ui.Separator(
        visible=True,
        spacing=discord.SeparatorSpacing.small,
    )


def white_container(*children) -> discord.ui.Container:
    # No accent_color = Discord's normal/default white container appearance.
    return discord.ui.Container(*children)


def success_container(*children) -> discord.ui.Container:
    return discord.ui.Container(
        *children,
        accent_color=GREEN,
    )


def error_container(*children) -> discord.ui.Container:
    return discord.ui.Container(
        *children,
        accent_color=RED,
    )


def simple_view(
    title: str,
    body: str,
    *,
    success: bool = False,
    error: bool = False,
) -> discord.ui.LayoutView:
    view = discord.ui.LayoutView(timeout=120)

    children = (
        text_component(f"## {title}"),
        separator(),
        text_component(body),
    )

    if success:
        panel = success_container(*children)
    elif error:
        panel = error_container(*children)
    else:
        panel = white_container(*children)

    view.add_item(panel)
    return view


# ============================================================
# DATABASE
# ============================================================


class OrderDB:
    def __init__(self, path: str):
        self.path = path

        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(
            self.path,
            timeout=30,
        )
        db.row_factory = sqlite3.Row
        return db

    async def setup(self) -> None:
        def run() -> None:
            with self.connect() as db:
                db.execute("PRAGMA journal_mode=WAL")

                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS orders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id INTEGER NOT NULL,
                        order_no INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        user_name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        amount TEXT,
                        payment_status TEXT NOT NULL DEFAULT 'unpaid',
                        ticket_channel_id INTEGER,
                        panel_message_id INTEGER,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(guild_id, order_no)
                    )
                    """
                )

                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ticket_settings (
                        guild_id INTEGER PRIMARY KEY,
                        channel_id INTEGER NOT NULL,
                        category_id INTEGER
                    )
                    """
                )

                # Migration for older versions.
                columns = {
                    row["name"]
                    for row in db.execute(
                        "PRAGMA table_info(orders)"
                    ).fetchall()
                }

                if "panel_message_id" not in columns:
                    db.execute(
                        """
                        ALTER TABLE orders
                        ADD COLUMN panel_message_id INTEGER
                        """
                    )

                if "payment_status" not in columns:
                    db.execute(
                        """
                        ALTER TABLE orders
                        ADD COLUMN payment_status TEXT
                        DEFAULT 'unpaid'
                        """
                    )

                if "amount" not in columns:
                    db.execute(
                        """
                        ALTER TABLE orders
                        ADD COLUMN amount TEXT
                        """
                    )

                if "ticket_channel_id" not in columns:
                    db.execute(
                        """
                        ALTER TABLE orders
                        ADD COLUMN ticket_channel_id INTEGER
                        """
                    )

                # Make sure the default trigger channel works even after restart.
                row = db.execute(
                    """
                    SELECT guild_id
                    FROM ticket_settings
                    LIMIT 1
                    """
                ).fetchone()

                # We intentionally don't insert the default here because the bot
                # may be in multiple guilds. Each guild is initialized lazily.
                db.commit()

        await asyncio.to_thread(run)

    async def set_ticket_channel(
        self,
        guild_id: int,
        channel_id: int,
        category_id: Optional[int],
    ) -> None:
        def run() -> None:
            with self.connect() as db:
                db.execute(
                    """
                    INSERT INTO ticket_settings(
                        guild_id,
                        channel_id,
                        category_id
                    )
                    VALUES (?, ?, ?)
                    ON CONFLICT(guild_id)
                    DO UPDATE SET
                        channel_id=excluded.channel_id,
                        category_id=excluded.category_id
                    """,
                    (
                        guild_id,
                        channel_id,
                        category_id,
                    ),
                )
                db.commit()

        await asyncio.to_thread(run)

    async def get_ticket_settings(
        self,
        guild_id: int,
    ) -> Optional[dict]:
        def run() -> Optional[dict]:
            with self.connect() as db:
                row = db.execute(
                    """
                    SELECT *
                    FROM ticket_settings
                    WHERE guild_id=?
                    """,
                    (guild_id,),
                ).fetchone()

                return dict(row) if row else None

        return await asyncio.to_thread(run)

    async def ensure_default_channel(self, guild_id: int) -> None:
        def run() -> None:
            with self.connect() as db:
                db.execute(
                    "INSERT OR IGNORE INTO ticket_settings(guild_id, channel_id, category_id) VALUES (?, ?, ?)",
                    (guild_id, DEFAULT_ORDER_CHANNEL_ID, ORDER_CATEGORY_ID or None),
                )
                db.commit()
        await asyncio.to_thread(run)

    async def create_order(
        self,
        guild_id: int,
        user: discord.Member,
    ) -> dict:
        """
        Allocate the LOWEST available order number.

        Cancelled orders are deleted from the database, therefore their
        number becomes immediately reusable.

        Confirmed/completed orders remain in the database, therefore their
        number is permanently consumed.
        """
        def run() -> dict:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")

                rows = db.execute(
                    """
                    SELECT order_no
                    FROM orders
                    WHERE guild_id=?
                    ORDER BY order_no ASC
                    """,
                    (guild_id,),
                ).fetchall()

                used = {
                    int(row["order_no"])
                    for row in rows
                }

                order_no = 1
                while order_no in used:
                    order_no += 1

                timestamp = utc_now()

                cursor = db.execute(
                    """
                    INSERT INTO orders(
                        guild_id,
                        order_no,
                        user_id,
                        user_name,
                        status,
                        payment_status,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        order_no,
                        user.id,
                        user.display_name,
                        STATUS_PENDING,
                        "unpaid",
                        timestamp,
                        timestamp,
                    ),
                )

                order_id = int(cursor.lastrowid)
                db.commit()

                return {
                    "id": order_id,
                    "guild_id": guild_id,
                    "order_no": order_no,
                    "user_id": user.id,
                    "user_name": user.display_name,
                    "status": STATUS_PENDING,
                    "amount": None,
                    "payment_status": "unpaid",
                    "ticket_channel_id": None,
                    "panel_message_id": None,
                }

        return await asyncio.to_thread(run)

    async def get_order(
        self,
        order_no: int,
        guild_id: int,
    ) -> Optional[dict]:
        def run() -> Optional[dict]:
            with self.connect() as db:
                row = db.execute(
                    """
                    SELECT *
                    FROM orders
                    WHERE guild_id=?
                      AND order_no=?
                    """,
                    (
                        guild_id,
                        order_no,
                    ),
                ).fetchone()

                return dict(row) if row else None

        return await asyncio.to_thread(run)

    async def get_order_by_channel(
        self,
        channel_id: int,
    ) -> Optional[dict]:
        def run() -> Optional[dict]:
            with self.connect() as db:
                row = db.execute(
                    """
                    SELECT *
                    FROM orders
                    WHERE ticket_channel_id=?
                    """,
                    (channel_id,),
                ).fetchone()

                return dict(row) if row else None

        return await asyncio.to_thread(run)

    async def get_user_active_order(
        self,
        guild_id: int,
        user_id: int,
    ) -> Optional[dict]:
        def run() -> Optional[dict]:
            with self.connect() as db:
                row = db.execute(
                    """
                    SELECT *
                    FROM orders
                    WHERE guild_id=?
                      AND user_id=?
                      AND status != ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (
                        guild_id,
                        user_id,
                        STATUS_COMPLETED,
                    ),
                ).fetchone()

                return dict(row) if row else None

        return await asyncio.to_thread(run)

    async def set_ticket(
        self,
        order_id: int,
        channel_id: int,
        panel_message_id: int,
    ) -> None:
        await self.update(
            order_id,
            ticket_channel_id=channel_id,
            panel_message_id=panel_message_id,
        )

    async def update(
        self,
        order_id: int,
        **values,
    ) -> None:
        allowed = {
            "status",
            "amount",
            "payment_status",
            "ticket_channel_id",
            "panel_message_id",
        }

        values = {
            key: value
            for key, value in values.items()
            if key in allowed
        }

        if not values:
            return

        values["updated_at"] = utc_now()

        assignments = ", ".join(
            f"{key}=?"
            for key in values
        )

        params = list(values.values())
        params.append(order_id)

        def run() -> None:
            with self.connect() as db:
                db.execute(
                    f"""
                    UPDATE orders
                    SET {assignments}
                    WHERE id=?
                    """,
                    params,
                )
                db.commit()

        await asyncio.to_thread(run)

    async def confirm(
        self,
        order_id: int,
    ) -> bool:
        def run() -> bool:
            with self.connect() as db:
                cursor = db.execute(
                    """
                    UPDATE orders
                    SET status=?,
                        updated_at=?
                    WHERE id=?
                      AND status=?
                    """,
                    (
                        STATUS_CONFIRMED,
                        utc_now(),
                        order_id,
                        STATUS_PENDING,
                    ),
                )
                db.commit()
                return cursor.rowcount == 1

        return await asyncio.to_thread(run)

    async def set_payment(
        self,
        order_id: int,
        amount: str,
    ) -> bool:
        def run() -> bool:
            with self.connect() as db:
                cursor = db.execute(
                    """
                    UPDATE orders
                    SET amount=?,
                        payment_status=?,
                        status=?,
                        updated_at=?
                    WHERE id=?
                      AND status=?
                    """,
                    (
                        amount,
                        "pending",
                        STATUS_PAYMENT_PENDING,
                        utc_now(),
                        order_id,
                        STATUS_CONFIRMED,
                    ),
                )
                db.commit()
                return cursor.rowcount == 1

        return await asyncio.to_thread(run)

    async def complete(
        self,
        order_id: int,
    ) -> bool:
        def run() -> bool:
            with self.connect() as db:
                cursor = db.execute(
                    """
                    UPDATE orders
                    SET status=?,
                        updated_at=?
                    WHERE id=?
                      AND status IN (?, ?)
                    """,
                    (
                        STATUS_COMPLETED,
                        utc_now(),
                        order_id,
                        STATUS_CONFIRMED,
                        STATUS_PAYMENT_PENDING,
                    ),
                )
                db.commit()
                return cursor.rowcount == 1

        return await asyncio.to_thread(run)

    async def cancel(
        self,
        order_id: int,
    ) -> Optional[int]:
        """
        Permanently removes the cancelled order row.

        This is deliberate: the order number is NOT saved after cancellation,
        so the same number becomes available for the next order.
        """
        def run() -> Optional[int]:
            with self.connect() as db:
                row = db.execute(
                    """
                    SELECT order_no, status
                    FROM orders
                    WHERE id=?
                    """,
                    (order_id,),
                ).fetchone()

                if not row:
                    return None

                # Cancellation is allowed only while the order has not been
                # completed. This prevents a completed order being cancelled.
                if row["status"] == STATUS_COMPLETED:
                    return None

                order_no = int(row["order_no"])

                db.execute(
                    """
                    DELETE FROM orders
                    WHERE id=?
                    """,
                    (order_id,),
                )

                db.commit()
                return order_no

        return await asyncio.to_thread(run)

    async def active_orders(self) -> list[dict]:
        def run() -> list[dict]:
            with self.connect() as db:
                rows = db.execute(
                    """
                    SELECT *
                    FROM orders
                    WHERE status != ?
                      AND ticket_channel_id IS NOT NULL
                    ORDER BY id ASC
                    """,
                    (STATUS_COMPLETED,),
                ).fetchall()

                return [dict(row) for row in rows]

        return await asyncio.to_thread(run)


# ============================================================
# CONFIRMATION VIEW
# ============================================================


class ConfirmActionView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Order",
        order_no: int,
        action: str,
    ):
        super().__init__(timeout=60)

        self.cog = cog
        self.order_no = order_no
        self.action = action

        yes = discord.ui.Button(
            label="Yes, continue",
            style=discord.ButtonStyle.danger,
            custom_id=(
                f"nexbytes:confirm:{action}:{order_no}:yes"
            ),
        )

        no = discord.ui.Button(
            label="Go back",
            style=discord.ButtonStyle.secondary,
            custom_id=(
                f"nexbytes:confirm:{action}:{order_no}:no"
            ),
        )

        yes.callback = self.yes_callback
        no.callback = self.no_callback

        question = (
            "Are you sure you want to cancel this order?"
            if action == "cancel"
            else "Are you sure this order is complete?"
        )

        self.add_item(
            white_container(
                text_component(
                    "## Confirm Action"
                ),
                separator(),
                text_component(question),
                separator(),
                discord.ui.ActionRow(
                    yes,
                    no,
                ),
            )
        )

    async def no_callback(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.edit_message(
            view=simple_view(
                "Action Cancelled",
                "No changes were made.",
            )
        )

    async def yes_callback(
        self,
        interaction: discord.Interaction,
    ):
        if not isinstance(
            interaction.user,
            discord.Member,
        ) or not is_staff(interaction.user):
            await interaction.response.edit_message(
                view=simple_view(
                    "Permission Denied",
                    "Only the order owner, administrators, or Order Staff can use this control.",
                    error=True,
                )
            )
            return

        if self.action == "cancel":
            await self.cog.cancel_order(
                interaction,
                self.order_no,
            )
            return

        await self.cog.complete_order(
            interaction,
            self.order_no,
        )


# ============================================================
# PAYMENT MODAL
# ============================================================


class PaymentAmountModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "Order",
        order_no: int,
    ):
        super().__init__(
            title=f"Payment — Order #{order_no}"
        )

        self.cog = cog
        self.order_no = order_no

        self.amount = discord.ui.TextInput(
            label="Amount in INR",
            placeholder="Example: 199",
            required=True,
            max_length=15,
        )

        self.add_item(self.amount)

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):
        if not isinstance(
            interaction.user,
            discord.Member,
        ) or not is_staff(interaction.user):
            await interaction.response.send_message(
                view=simple_view(
                    "Permission Denied",
                    "Only the order owner, administrators, or Order Staff can create a payment request.",
                    error=True,
                ),
                ephemeral=True,
            )
            return

        try:
            amount = parse_amount(
                self.amount.value
            )
        except ValueError as error:
            await interaction.response.send_message(
                view=simple_view(
                    "Invalid Amount",
                    str(error),
                    error=True,
                ),
                ephemeral=True,
            )
            return

        if interaction.guild is None:
            return

        order = await self.cog.db.get_order(
            self.order_no,
            interaction.guild.id,
        )

        if not order:
            await interaction.response.send_message(
                view=simple_view(
                    "Order Not Found",
                    "This order is no longer active.",
                    error=True,
                ),
                ephemeral=True,
            )
            return

        if order["status"] != STATUS_CONFIRMED:
            await interaction.response.send_message(
                view=simple_view(
                    "Payment Unavailable",
                    "The order must be accepted before a payment request can be created.",
                    error=True,
                ),
                ephemeral=True,
            )
            return

        updated = await self.cog.db.set_payment(
            int(order["id"]),
            amount,
        )

        if not updated:
            await interaction.response.send_message(
                view=simple_view(
                    "Payment Unavailable",
                    "The order state changed before the payment request was created.",
                    error=True,
                ),
                ephemeral=True,
            )
            return

        qr = make_upi_qr(amount)
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            await self.cog.send_payment_panel(
                interaction.channel, self.order_no, amount, qr.getvalue()
            )
        except Exception as error:
            log.exception("Failed to send QR for order #%s", self.order_no)
            await self.cog.db.update(
                int(order["id"]),
                status=STATUS_CONFIRMED,
                amount=None,
                payment_status="unpaid",
            )
            await interaction.followup.send(
                view=simple_view(
                    "Payment Failed",
                    f"The payment QR could not be sent.\n\n`{error}`",
                    error=True,
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            view=simple_view(
                "Payment Sent",
                f"Payment request created for ₹{amount}.",
                success=True,
            ),
            ephemeral=True,
        )

        await self.cog.refresh_ticket_panel(
            interaction.guild, self.order_no
        )

# ============================================================
# TICKET PANEL
# ============================================================


class TicketView(discord.ui.LayoutView):
    def __init__(
        self,
        cog: "Order",
        order_no: int,
        status: Optional[str] = None,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.order_no = order_no
        self.status = status

        self.accept_button = discord.ui.Button(
            label="Accept",
            style=discord.ButtonStyle.success,
            custom_id=(
                f"nexbytes:ticket:accept:{order_no}"
            ),
        )

        self.cancel_button = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.danger,
            custom_id=(
                f"nexbytes:ticket:cancel:{order_no}"
            ),
        )

        self.payment_button = discord.ui.Button(
            label="Payment",
            style=discord.ButtonStyle.primary,
            custom_id=(
                f"nexbytes:ticket:payment:{order_no}"
            ),
        )

        self.complete_button = discord.ui.Button(
            label="Order Complete",
            style=discord.ButtonStyle.success,
            custom_id=(
                f"nexbytes:ticket:complete:{order_no}"
            ),
        )

        self.transcript_button = discord.ui.Button(
            label="Transcript",
            style=discord.ButtonStyle.secondary,
            custom_id=(
                f"nexbytes:ticket:transcript:{order_no}"
            ),
        )

        self.accept_button.callback = self.accept_callback
        self.cancel_button.callback = self.cancel_callback
        self.payment_button.callback = self.payment_callback
        self.complete_button.callback = self.complete_callback
        self.transcript_button.callback = self.transcript_callback

        # Button state is rebuilt from SQLite, so it survives restart.
        if status != STATUS_PENDING:
            self.accept_button.disabled = True

        if status not in (
            STATUS_CONFIRMED,
            STATUS_PAYMENT_PENDING,
        ):
            self.payment_button.disabled = True

        if status not in (
            STATUS_CONFIRMED,
            STATUS_PAYMENT_PENDING,
        ):
            self.complete_button.disabled = True

        status_text = status or STATUS_PENDING

        self.add_item(
            white_container(
                text_component(
                    f"## Nexbytes Order Ticket — #{order_no}"
                ),
                separator(),
                text_component(
                    f"**Status:** {status_text}\n\n"
                    "An authorized order staff member can manage this ticket using the controls below."
                ),
                separator(),
                discord.ui.ActionRow(
                    self.accept_button,
                    self.cancel_button,
                    self.payment_button,
                ),
                discord.ui.ActionRow(
                    self.complete_button,
                    self.transcript_button,
                ),
            )
        )

    async def require_staff(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if (
            isinstance(interaction.user, discord.Member)
            and is_staff(interaction.user)
        ):
            return True

        await interaction.response.send_message(
            view=simple_view(
                "Permission Denied",
                "This control is available only to the order owner, administrators, or Order Staff.",
                error=True,
            ),
            ephemeral=True,
        )
        return False

    async def get_order(
        self,
        interaction: discord.Interaction,
    ) -> Optional[dict]:
        if interaction.guild is None:
            return None

        return await self.cog.db.get_order(
            self.order_no,
            interaction.guild.id,
        )

    async def accept_callback(
        self,
        interaction: discord.Interaction,
    ):
        if not await self.require_staff(interaction):
            return

        order = await self.get_order(interaction)

        if not order:
            await interaction.response.send_message(
                view=simple_view(
                    "Order Not Found",
                    "This order is no longer active.",
                    error=True,
                ),
                ephemeral=True,
            )
            return

        if order["status"] != STATUS_PENDING:
            await interaction.response.send_message(
                view=simple_view(
                    "Already Accepted",
                    "This order has already been accepted.",
                    error=True,
                ),
                ephemeral=True,
            )
            return

        changed = await self.cog.db.confirm(
            int(order["id"])
        )

        if not changed:
            await interaction.response.send_message(
                view=simple_view(
                    "Order Updated",
                    "This order was already changed by another staff member.",
                    error=True,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            view=simple_view(
                "Order Accepted",
                f"Order #{self.order_no} has been accepted.",
                success=True,
            ),
            ephemeral=True,
        )

        await self.cog.refresh_ticket_panel(
            interaction.guild,
            self.order_no,
        )

    async def cancel_callback(
        self,
        interaction: discord.Interaction,
    ):
        if not await self.require_staff(interaction):
            return

        await interaction.response.send_message(
            view=ConfirmActionView(
                self.cog,
                self.order_no,
                "cancel",
            ),
            ephemeral=True,
        )

    async def payment_callback(
        self,
        interaction: discord.Interaction,
    ):
        if not await self.require_staff(interaction):
            return

        order = await self.get_order(interaction)

        if not order:
            await interaction.response.send_message(
                view=simple_view(
                    "Order Not Found",
                    "This order is no longer active.",
                    error=True,
                ),
                ephemeral=True,
            )
            return

        if order["status"] != STATUS_CONFIRMED:
            await interaction.response.send_message(
                view=simple_view(
                    "Payment Unavailable",
                    "Accept the order before creating its payment request.",
                    error=True,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            PaymentAmountModal(
                self.cog,
                self.order_no,
            )
        )

    async def complete_callback(
        self,
        interaction: discord.Interaction,
    ):
        if not await self.require_staff(interaction):
            return

        await interaction.response.send_message(
            view=ConfirmActionView(
                self.cog,
                self.order_no,
                "complete",
            ),
            ephemeral=True,
        )

    async def transcript_callback(
        self,
        interaction: discord.Interaction,
    ):
        if not await self.require_staff(interaction):
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        ok, message = await self.cog.create_transcript(
            interaction,
            self.order_no,
        )

        await interaction.followup.send(
            view=simple_view(
                "Transcript Created" if ok else "Transcript Failed",
                message,
                success=ok,
                error=not ok,
            ),
            ephemeral=True,
        )


# ============================================================
# COG
# ============================================================


class Order(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self.db = OrderDB(DATABASE_PATH)
        self.ready = False
        self._creating_users: set[tuple[int, int]] = set()

    async def cog_load(self) -> None:
        await self.db.setup()
        self.ready = True

        # Restore persistent ticket buttons after every restart.
        for order in await self.db.active_orders():
            try:
                self.bot.add_view(
                    TicketView(
                        self,
                        int(order["order_no"]),
                        order["status"],
                    )
                )
            except Exception:
                log.exception(
                    "Failed to restore TicketView for order #%s",
                    order["order_no"],
                )

        log.info(
            "Nexbytes order ticket system loaded."
        )

    # ========================================================
    # PERMISSIONS / CHANNEL
    # ========================================================

    async def ensure_staff_role(
        self,
        guild: discord.Guild,
    ) -> Optional[discord.Role]:
        if ORDER_STAFF_ROLE_ID:
            role = guild.get_role(
                ORDER_STAFF_ROLE_ID
            )
            if role:
                return role

        role = discord.utils.get(
            guild.roles,
            name=ORDER_STAFF_ROLE_NAME,
        )

        if role:
            return role

        if not guild.me.guild_permissions.manage_roles:
            return None

        try:
            return await guild.create_role(
                name=ORDER_STAFF_ROLE_NAME,
                reason="Nexbytes order ticket staff role",
            )
        except discord.HTTPException:
            log.exception(
                "Failed to create Nexbytes staff role."
            )
            return None

    async def get_order_category(
        self,
        guild: discord.Guild,
        settings: dict,
    ) -> Optional[discord.CategoryChannel]:
        category_id = (
            settings.get("category_id")
            or ORDER_CATEGORY_ID
        )

        if category_id:
            channel = guild.get_channel(
                int(category_id)
            )
            if isinstance(
                channel,
                discord.CategoryChannel,
            ):
                return channel

        return None

    # ========================================================
    # TICKET CREATION
    # ========================================================

    async def create_ticket(
        self,
        message: discord.Message,
    ) -> None:
        if not self.ready:
            return

        if message.guild is None:
            return

        if message.author.bot:
            return

        if not isinstance(
            message.author,
            discord.Member,
        ):
            return

        # Staff members can chat normally in the order channel.
        # Their messages must NEVER create customer tickets.
        if is_staff(message.author):
            return

        await self.db.ensure_default_channel(
            message.guild.id
        )

        settings = await self.db.get_ticket_settings(
            message.guild.id
        )

        if not settings:
            return

        if int(settings["channel_id"]) != message.channel.id:
            return

        user_key = (
            message.guild.id,
            message.author.id,
        )

        # Prevent two simultaneous messages from allocating two orders.
        if user_key in self._creating_users:
            return

        self._creating_users.add(user_key)

        try:
            existing = await self.db.get_user_active_order(
                message.guild.id,
                message.author.id,
            )

            if existing:
                existing_channel = message.guild.get_channel(
                    existing.get("ticket_channel_id")
                )

                try:
                    await message.delete()
                except discord.HTTPException:
                    pass

                if existing_channel:
                    await message.channel.send(
                        view=simple_view(
                            "Active Order",
                            f"You already have an active order: {existing_channel.mention}",
                        ),
                        delete_after=8,
                    )
                return

            order = await self.db.create_order(
                message.guild.id,
                message.author,
            )

            staff_role = await self.ensure_staff_role(
                message.guild
            )

            category = await self.get_order_category(
                message.guild,
                settings,
            )

            bot_member = message.guild.me

            overwrites = {
                message.guild.default_role:
                    discord.PermissionOverwrite(
                        view_channel=False
                    ),

                message.author:
                    discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        attach_files=True,
                    ),
            }

            if bot_member:
                overwrites[bot_member] = (
                    discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        manage_channels=True,
                        manage_messages=True,
                        attach_files=True,
                    )
                )

            if staff_role:
                overwrites[staff_role] = (
                    discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        attach_files=True,
                    )
                )

            # Admins don't need an explicit overwrite because their
            # Administrator permission bypasses channel overwrites.
            channel = await message.guild.create_text_channel(
                name=(
                    f"order-{order['order_no']}-"
                    f"{safe_channel_name(message.author.display_name)}"
                ),
                category=category,
                overwrites=overwrites,
                reason=(
                    f"Nexbytes order #{order['order_no']} "
                    "ticket created"
                ),
            )

            panel_message = await channel.send(
                view=TicketView(
                    self,
                    int(order["order_no"]),
                    STATUS_PENDING,
                )
            )

            await self.db.set_ticket(
                int(order["id"]),
                channel.id,
                panel_message.id,
            )

            try:
                await message.delete()
            except discord.HTTPException:
                pass

            # Keep the public trigger channel clean.
            await message.channel.send(
                view=simple_view(
                    "Order Created",
                    f"Your private order ticket is ready: {channel.mention}",
                ),
                delete_after=8,
            )

            try:
                await message.author.send(
                    view=simple_view(
                        f"Nexbytes Order #{order['order_no']}",
                        f"Your private order ticket is ready: {channel.mention}",
                    )
                )
            except (
                discord.Forbidden,
                discord.HTTPException,
            ):
                pass

        except discord.Forbidden:
            log.exception(
                "Missing permissions while creating order ticket."
            )

        except Exception:
            log.exception(
                "Failed to create Nexbytes order ticket."
            )

        finally:
            self._creating_users.discard(
                user_key
            )

    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message,
    ) -> None:
        # Order creation is handled independently from command processing.
        # This means normal text, !order, or any other message in the trigger
        # channel can create an order for a customer. Staff messages are
        # ignored by create_ticket().
        await self.create_ticket(message)

    @commands.Cog.listener()
    async def on_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        # A customer is allowed to type ANYTHING in the order channel.
        # Unknown prefix commands must therefore not spam CommandNotFound
        # errors in the console. Other command errors are left untouched so
        # the rest of the bot can handle them normally.
        if isinstance(error, commands.CommandNotFound):
            if (
                ctx.guild is not None
                and ctx.channel is not None
            ):
                settings = await self.db.get_ticket_settings(
                    ctx.guild.id
                )
                if (
                    settings
                    and int(settings["channel_id"]) == ctx.channel.id
                ):
                    return

        # Do not consume errors from other cogs.
        return

    # ========================================================
    # TICKET PANEL REFRESH
    # ========================================================

    async def refresh_ticket_panel(
        self,
        guild: discord.Guild,
        order_no: int,
    ) -> None:
        order = await self.db.get_order(
            order_no,
            guild.id,
        )

        if not order:
            return

        channel_id = order.get(
            "ticket_channel_id"
        )
        panel_id = order.get(
            "panel_message_id"
        )

        if not channel_id or not panel_id:
            return

        channel = guild.get_channel(
            int(channel_id)
        )

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            return

        try:
            panel = await channel.fetch_message(
                int(panel_id)
            )

            await panel.edit(
                view=TicketView(
                    self,
                    order_no,
                    order["status"],
                )
            )

        except discord.NotFound:
            # The panel was deleted. Recreate it.
            try:
                new_panel = await channel.send(
                    view=TicketView(
                        self,
                        order_no,
                        order["status"],
                    )
                )

                await self.db.update(
                    int(order["id"]),
                    panel_message_id=new_panel.id,
                )

            except discord.HTTPException:
                log.exception(
                    "Failed to recreate order panel #%s",
                    order_no,
                )

        except discord.HTTPException:
            log.exception(
                "Failed to refresh order panel #%s",
                order_no,
            )

    # ========================================================
    # PAYMENT
    # ========================================================

    async def send_payment_panel(
        self,
        channel: discord.abc.Messageable,
        order_no: int,
        amount: str,
        qr_bytes: bytes,
    ) -> None:
        view = discord.ui.LayoutView(timeout=None)
        view.add_item(
            white_container(
                text_component(f"## Payment — Order #{order_no}"),
                separator(),
                text_component(
                    f"**Amount:** ₹{amount}\n\n"
                    "Scan the QR code below to complete the payment."
                ),
            )
        )
        # Send the QR as its own Discord attachment first. Keeping the QR
        # upload separate from the Components V2 message makes delivery
        # reliable across Discord clients and guarantees the image is
        # actually attached to the ticket.
        filename = f"order-{order_no}-payment.png"
        qr_file = discord.File(io.BytesIO(qr_bytes), filename=filename)
        await channel.send(file=qr_file)

        # Then send the clean CV2 payment panel.
        await channel.send(view=view)

    # ========================================================
    # CANCEL
    # ========================================================

    async def cancel_order(
        self,
        interaction: discord.Interaction,
        order_no: int,
    ) -> None:
        if interaction.guild is None:
            return

        order = await self.db.get_order(
            order_no,
            interaction.guild.id,
        )

        if not order:
            await interaction.response.edit_message(
                view=simple_view(
                    "Order Not Found",
                    "This order is no longer active.",
                    error=True,
                )
            )
            return

        channel_id = order.get(
            "ticket_channel_id"
        )

        released_number = await self.db.cancel(
            int(order["id"])
        )

        if released_number is None:
            await interaction.response.edit_message(
                view=simple_view(
                    "Unable to Cancel",
                    "This order cannot be cancelled.",
                    error=True,
                )
            )
            return

        await interaction.response.edit_message(
            view=simple_view(
                "Order Cancelled",
                f"Order #{released_number} has been cancelled.",
                success=True,
            )
        )

        channel = (
            interaction.guild.get_channel(
                int(channel_id)
            )
            if channel_id
            else interaction.channel
        )

        await asyncio.sleep(1.2)

        if isinstance(
            channel,
            discord.TextChannel,
        ):
            try:
                await channel.delete(
                    reason=(
                        f"Nexbytes order #{released_number} "
                        "cancelled"
                    )
                )
            except discord.HTTPException:
                log.exception(
                    "Failed to delete cancelled ticket #%s",
                    released_number,
                )

    # ========================================================
    # COMPLETE
    # ========================================================

    async def complete_order(
        self,
        interaction: discord.Interaction,
        order_no: int,
    ) -> None:
        if interaction.guild is None:
            return

        order = await self.db.get_order(
            order_no,
            interaction.guild.id,
        )

        if not order:
            await interaction.response.edit_message(
                view=simple_view(
                    "Order Not Found",
                    "This order is no longer active.",
                    error=True,
                )
            )
            return

        changed = await self.db.complete(
            int(order["id"])
        )

        if not changed:
            await interaction.response.edit_message(
                view=simple_view(
                    "Unable to Complete",
                    "The order must be accepted before it can be completed.",
                    error=True,
                )
            )
            return

        await interaction.response.edit_message(
            view=simple_view(
                "Order Complete",
                f"Order #{order_no} has been marked complete.",
                success=True,
            )
        )

        # The order row remains in SQLite, so its number is permanently used.
        await asyncio.sleep(1.2)

        channel = interaction.channel

        if isinstance(
            channel,
            discord.TextChannel,
        ):
            try:
                await channel.delete(
                    reason=(
                        f"Nexbytes order #{order_no} completed"
                    )
                )
            except discord.HTTPException:
                log.exception(
                    "Failed to delete completed ticket #%s",
                    order_no,
                )

    # ========================================================
    # TRANSCRIPT SCREENSHOT
    # ========================================================

    @staticmethod
    def _font(size: int, bold: bool = False):
        paths = (
            r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        )
        for path in paths:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
        return ImageFont.load_default()

    async def create_transcript(self, interaction: discord.Interaction, order_no: int) -> tuple[bool, str]:
        if interaction.guild is None:
            return False, "This action can only be used inside a server."
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return False, "The ticket channel could not be found."
        order = await self.db.get_order(order_no, interaction.guild.id)
        if not order:
            return False, "This order is no longer active."
        transcript_channel = interaction.guild.get_channel(TRANSCRIPT_CHANNEL_ID)
        if not isinstance(transcript_channel, discord.TextChannel):
            return False, f"Transcript channel `{TRANSCRIPT_CHANNEL_ID}` was not found."
        try:
            messages = [m async for m in channel.history(limit=None, oldest_first=True)]
        except discord.HTTPException as error:
            return False, f"Could not read the ticket history: {error}"

        width, margin = 1400, 55
        title_font=self._font(34,True); sub_font=self._font(17); name_font=self._font(20,True); small_font=self._font(13); body_font=self._font(18)
        rows=[]; height=150
        for m in messages:
            content=m.content.strip() or "[Nexbytes ticket panel / component message]"
            if m.attachments:
                content += "\n[Attachment: " + ", ".join(a.filename for a in m.attachments) + "]"
            lines=[]
            for part in content.splitlines() or [""]:
                lines.extend(textwrap.wrap(part,width=105,break_long_words=True) or [""])
            rh=62+max(1,len(lines))*28+22; rows.append((m,lines,rh)); height+=rh
        height+=70
        image=Image.new("RGB",(width,max(height,400)),"white"); draw=ImageDraw.Draw(image)
        draw.text((margin,35),f"Nexbytes Order Ticket — #{order_no}",font=title_font,fill="#111111")
        draw.text((margin,84),f"Transcript  •  #{channel.name}",font=sub_font,fill="#777777")
        draw.line((margin,125,width-margin,125),fill="#e5e5e5",width=2)
        y=150
        for m,lines,rh in rows:
            ax,ay=margin,y+4; draw.ellipse((ax,ay,ax+46,ay+46),fill="#f0f0f0")
            initial=(m.author.display_name[:1] or "?").upper(); b=draw.textbbox((0,0),initial,font=name_font)
            draw.text((ax+(46-(b[2]-b[0]))/2,ay+(46-(b[3]-b[1]))/2-2),initial,font=name_font,fill="#333333")
            tx=margin+62; draw.text((tx,y),m.author.display_name,font=name_font,fill="#111111")
            nb=draw.textbbox((tx,y),m.author.display_name,font=name_font)
            draw.text((nb[2]+12,y+4),m.created_at.strftime("%d %b %Y, %H:%M"),font=small_font,fill="#888888")
            by=y+31
            for line in lines:
                draw.text((tx,by),line,font=body_font,fill="#222222"); by+=28
            draw.line((tx,y+rh-8,width-margin,y+rh-8),fill="#eeeeee",width=1); y+=rh
        draw.text((margin,y+8),f"Nexbytes Order System  •  Order #{order_no}",font=small_font,fill="#888888")
        buf=io.BytesIO(); image.save(buf,"PNG",optimize=True); buf.seek(0)
        try:
            await transcript_channel.send(
                content=f"**Nexbytes Order Transcript — #{order_no}**\nCustomer: <@{order['user_id']}>",
                file=discord.File(buf,filename=f"order-{order_no}-transcript.png"),
            )
        except discord.HTTPException as error:
            log.exception("Failed to send transcript for order #%s",order_no)
            return False,f"Discord could not send the transcript: {error}"
        return True,f"Order #{order_no} transcript screenshot was saved to {transcript_channel.mention}."

    # ========================================================
    # COMMAND GROUP
    # ========================================================

    @commands.group(
        name="ticket",
        invoke_without_command=True,
    )
    @commands.guild_only()
    async def ticket(
        self,
        ctx: commands.Context,
    ) -> None:
        await ctx.send(
            view=simple_view(
                "Nexbytes Ticket System",
                "Use `!ticket help` for available ticket commands.",
            )
        )

    @ticket.command(
        name="help",
    )
    @commands.guild_only()
    async def ticket_help(
        self,
        ctx: commands.Context,
    ) -> None:
        await ctx.send(
            view=simple_view(
                "Nexbytes Ticket Help",
                "**!ticket setup**\n"
                "Configure the current channel as the order trigger channel.\n\n"
                "**!ticket channelset**\n"
                "Set the current channel as the order trigger channel.\n\n"
                "**!ticket channel reset**\n"
                "Reset the order trigger channel to the configured default channel.\n\n"
                "**!ticket help**\n"
                "Show this help panel.\n\n"
                "Once configured, a normal user message in the order channel creates a private order ticket.",
            )
        )

    @ticket.command(
        name="channelset",
    )
    @commands.guild_only()
    async def ticket_channelset(
        self,
        ctx: commands.Context,
    ) -> None:
        if not is_staff(ctx.author):
            await ctx.send(
                view=simple_view(
                    "Permission Denied",
                    "Only the bot owner, administrators, or Order Staff can configure tickets.",
                    error=True,
                )
            )
            return

        category_id = (
            ctx.channel.category.id
            if isinstance(
                ctx.channel,
                discord.TextChannel,
            ) and ctx.channel.category
            else None
        )

        await self.db.set_ticket_channel(
            ctx.guild.id,
            ctx.channel.id,
            category_id,
        )

        await ctx.send(
            view=simple_view(
                "Order Channel Updated",
                f"{ctx.channel.mention} is now the Nexbytes order trigger channel.",
                success=True,
            )
        )

    @ticket.group(
        name="channel",
        invoke_without_command=True,
    )
    @commands.guild_only()
    async def ticket_channel_group(
        self,
        ctx: commands.Context,
    ) -> None:
        await ctx.send(
            view=simple_view(
                "Ticket Channel",
                "Use `!ticket channelset` to set the current channel, or `!ticket channel reset` to return to the default order channel.",
            )
        )

    @ticket_channel_group.command(
        name="reset",
    )
    @commands.guild_only()
    async def ticket_channel_reset(
        self,
        ctx: commands.Context,
    ) -> None:
        if not is_staff(ctx.author):
            await ctx.send(
                view=simple_view(
                    "Permission Denied",
                    "Only the bot owner, administrators, or Order Staff can reset the ticket channel.",
                    error=True,
                )
            )
            return

        await self.db.set_ticket_channel(
            ctx.guild.id,
            DEFAULT_ORDER_CHANNEL_ID,
            ORDER_CATEGORY_ID or None,
        )

        channel = ctx.guild.get_channel(
            DEFAULT_ORDER_CHANNEL_ID
        )

        destination = (
            channel.mention
            if channel is not None
            else f"`{DEFAULT_ORDER_CHANNEL_ID}`"
        )

        await ctx.send(
            view=simple_view(
                "Ticket Channel Reset",
                f"The order trigger channel has been reset to {destination}.",
                success=True,
            )
        )

    @ticket.command(
        name="setup",
    )
    @commands.guild_only()
    async def ticket_setup(
        self,
        ctx: commands.Context,
    ) -> None:
        if not is_staff(ctx.author):
            await ctx.send(
                view=simple_view(
                    "Permission Denied",
                    "Only the bot owner, administrators, or Order Staff can run ticket setup.",
                    error=True,
                )
            )
            return

        staff_role = await self.ensure_staff_role(
            ctx.guild
        )

        category_id = (
            ctx.channel.category.id
            if isinstance(
                ctx.channel,
                discord.TextChannel,
            ) and ctx.channel.category
            else ORDER_CATEGORY_ID or None
        )

        await self.db.set_ticket_channel(
            ctx.guild.id,
            ctx.channel.id,
            category_id,
        )

        role_text = (
            staff_role.mention
            if staff_role
            else "Order Staff"
        )

        await ctx.send(
            view=simple_view(
                "Ticket System Ready",
                f"Order trigger: {ctx.channel.mention}\n"
                f"Staff access: {role_text} + Administrators + Bot Owner\n"
                "Tickets are private and persistent across bot restarts.",
                success=True,
            )
        )


async def setup(
    bot: commands.Bot,
) -> None:
    await bot.add_cog(
        Order(bot)
    )
