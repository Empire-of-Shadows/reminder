import asyncio
from typing import List, Tuple, Optional
import discord
from discord.ext import commands

from storage.log import get_logger

logger = get_logger("TimerEmbedManager")


class TimerEmbedManager(commands.Cog):
    """Manages the persistent timer embed that shows bump cooldown status."""

    def __init__(self, bot):
        self.bot = bot
        self._pending_updates = {}  # guild_id -> task mapping
        self._update_lock = asyncio.Lock()

    def create_timer_embed(
        self,
        active_timers: List[Tuple[str, int]],
        expired_timers: List[str],
        role_id: int
    ) -> discord.Embed:
        purple = 0x7603FF
        embed = discord.Embed(
            title="Bump Timer Status",
            color=purple
        )

        # Add active timers
        if active_timers:
            active_text = []
            for bot_name, end_timestamp in sorted(active_timers, key=lambda x: x[1]):
                active_text.append(
                    f"**{bot_name.capitalize()}**: <t:{end_timestamp}:R>"
                )
            embed.add_field(
                name="⏰ Active Timers",
                value="\n".join(active_text),
                inline=False
            )

        # Add expired timers
        if expired_timers:
            expired_text = []
            for bot_name in expired_timers:
                expired_text.append(f"**{bot_name.capitalize()}**: Ready to bump!")
            embed.add_field(
                name="✅ Ready to Bump",
                value="\n".join(expired_text),
                inline=False
            )

        # Add footer
        if expired_timers:
            embed.set_footer(text=f"💡 Bump now and I'll remind you when it's time again!")
        else:
            embed.set_footer(text=f"🕐 Timers update automatically after each bump")

        return embed

    async def schedule_embed_update(
        self,
        guild_id: int,
        channel_id: int,
        role_id: int,
        active_timers: List[Tuple[str, int]],
        expired_timers: List[str]
    ):
        try:
            async with self._update_lock:
                if guild_id in self._pending_updates:
                    self._pending_updates[guild_id].cancel()

                task = asyncio.create_task(
                    self._delayed_update(
                        guild_id, channel_id, role_id, active_timers, expired_timers
                    )
                )
                self._pending_updates[guild_id] = task

        except Exception as e:
            logger.error(f"[{guild_id}] Error scheduling embed update: {e}", exc_info=True)

    @staticmethod
    def _resolve_timer_channel(config, fallback_channel_id: int) -> int:
        """Where the countdown embed belongs.

        The panel offers a Timers Channel described as "Channel where the live
        countdown timer embed is shown. Defaults to the Bump Channel." Both the
        panel and the dashboard wrote it and nothing ever read it, so the embed
        always landed in the bump channel and the setting did nothing. Unset
        (0/None) keeps the documented default, which is the channel the caller
        passed - the bump channel.
        """
        raw = getattr(config, "timers_channel", 0)
        try:
            configured = int(raw or 0)
        except (TypeError, ValueError):
            logger.warning(f"Unparseable timers_channel {raw!r}; using the bump channel")
            return fallback_channel_id
        return configured or fallback_channel_id

    async def _clear_stale_embeds(self, guild_id: int, config, keep_channel_id: int) -> None:
        """Remove a countdown embed left behind in a channel we no longer use.

        The stored message id is keyed per channel, so moving the Timers Channel
        would otherwise strand a frozen countdown in the old one forever.
        """
        stale_keys = [
            key for key in (config.extra_data or {})
            if key.startswith("timer_message_") and key != f"timer_message_{keep_channel_id}"
        ]
        for key in stale_keys:
            message_id = config.extra_data.get(key)
            if not message_id:
                continue
            try:
                old_channel_id = int(key.rsplit("_", 1)[1])
            except (IndexError, ValueError):
                continue
            try:
                old_channel = self.bot.get_channel(old_channel_id)
                if old_channel is not None:
                    old_message = await old_channel.fetch_message(int(message_id))
                    await old_message.delete()
                    logger.info(
                        f"[{guild_id}] Removed stale timer embed from channel {old_channel_id}"
                    )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException,
                    ValueError, TypeError) as e:
                logger.debug(f"[{guild_id}] Could not remove stale timer embed: {e}")
            # Forget it either way - a message we cannot reach is not ours to track.
            await self.bot.guild_config_manager.set_value(guild_id, key, None)

    async def _delayed_update(
        self,
        guild_id: int,
        channel_id: int,
        role_id: int,
        active_timers: List[Tuple[str, int]],
        expired_timers: List[str]
    ):
        try:
            await asyncio.sleep(10)

            # Check if timers should be displayed
            config = await self.bot.guild_config_manager.get_config(guild_id)
            if not config.timers_message:
                logger.debug(f"[{guild_id}] Timer messages disabled, skipping update")
                return

            # Resolved here rather than at schedule time so an admin changing the
            # setting during the debounce window still gets the new channel.
            channel_id = self._resolve_timer_channel(config, channel_id)
            await self._clear_stale_embeds(guild_id, config, channel_id)

            channel = self.bot.get_channel(channel_id)
            if not channel:
                try:
                    guild = self.bot.get_guild(guild_id)
                    if guild:
                        channel = await guild.fetch_channel(channel_id)
                except Exception as e:
                    logger.warning(f"[{guild_id}] Could not fetch channel {channel_id}: {e}")
                    return

            if not channel:
                logger.warning(f"[{guild_id}] Channel {channel_id} not found for embed update")
                return

            embed = self.create_timer_embed(active_timers, expired_timers, role_id)

            # Delete old timer message if it exists
            existing_msg_id = config.extra_data.get(f"timer_message_{channel_id}")

            if existing_msg_id:
                try:
                    message = await channel.fetch_message(int(existing_msg_id))
                    await message.delete()
                    logger.debug(f"[{guild_id}] Deleted old timer embed message {existing_msg_id}")
                except (discord.NotFound, ValueError, TypeError):
                    logger.debug(f"[{guild_id}] Old timer message {existing_msg_id} not found or invalid")
                except discord.Forbidden:
                    logger.warning(f"[{guild_id}] Missing permissions to delete old timer message {existing_msg_id}")
                except discord.HTTPException as e:
                    logger.warning(f"[{guild_id}] Failed to delete old timer message: {e}")

            # Send new message
            try:
                message = await channel.send(embed=embed)
                # Save using config manager
                await self.bot.guild_config_manager.set_value(guild_id, f"timer_message_{channel_id}", message.id)
                logger.info(f"[{guild_id}] Sent new timer embed message {message.id}")
            except discord.Forbidden:
                logger.error(f"[{guild_id}] Missing permissions to send embed in channel {channel_id}")
            except discord.HTTPException as e:
                logger.error(f"[{guild_id}] Failed to send embed message: {e}")

        except asyncio.CancelledError:
            logger.debug(f"[{guild_id}] Embed update cancelled (likely debounced)")
            raise
        except Exception as e:
            logger.error(f"[{guild_id}] Error updating timer embed: {e}", exc_info=True)
        finally:
            async with self._update_lock:
                self._pending_updates.pop(guild_id, None)


async def setup(bot):
    logger.info("Setting up TimerEmbedManager Cog...")
    await bot.add_cog(TimerEmbedManager(bot))
