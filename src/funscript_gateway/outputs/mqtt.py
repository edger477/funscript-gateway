"""MqttDriver — publishes on/off commands to an MQTT broker."""

from __future__ import annotations

import asyncio
import logging

from funscript_gateway.models import MqttOutputConfig

logger = logging.getLogger(__name__)

try:
    import aiomqtt
    _AIOMQTT_AVAILABLE = True
except ImportError:
    _AIOMQTT_AVAILABLE = False
    logger.warning(
        "aiomqtt not available; MQTT outputs will not function. "
        "Install with: pip install aiomqtt"
    )


class MqttDriver:
    """Publishes on/off payloads to a configured MQTT topic.

    The ``aiomqtt.Client`` lifecycle is managed by ``OutputManager``.
    ``MqttDriver`` receives a reference to an already-entered client and
    does not call connect/disconnect itself.

    If a ``status_topic`` is configured, ``OutputManager`` starts a
    subscription task that updates ``_confirmed_state``.
    """

    def __init__(self, config: MqttOutputConfig, client: object) -> None:
        self.config = config
        self._client = client
        self._last_sent: bool | None = None
        self._confirmed_state: bool | None = None

    async def set_state(self, on: bool) -> None:
        if not _AIOMQTT_AVAILABLE:
            raise RuntimeError("aiomqtt is not installed")
        if on == self._last_sent:
            return
        payload = self.config.payload_on if on else self.config.payload_off
        await self._client.publish(
            self.config.command_topic,
            payload,
            qos=self.config.qos,
            retain=self.config.retain,
        )
        self._last_sent = on
        logger.debug(
            "MQTT %s -> %s (topic: %s)",
            "ON" if on else "OFF",
            payload,
            self.config.command_topic,
        )

    async def run_status_subscription(self) -> None:
        """Subscribe to status_topic and update _confirmed_state.

        Intended to be run as a background asyncio task by OutputManager.
        """
        if not _AIOMQTT_AVAILABLE or not self.config.status_topic:
            return
        await self._client.subscribe(self.config.status_topic)
        async for message in self._client.messages:
            topic = str(message.topic)
            if topic != self.config.status_topic:
                continue
            try:
                payload_str = message.payload.decode("utf-8")
            except Exception:  # noqa: BLE001
                continue
            if payload_str == self.config.payload_on:
                self._confirmed_state = True
            elif payload_str == self.config.payload_off:
                self._confirmed_state = False
