"""MqttDriver — publishes on/off commands to an MQTT broker.

Uses paho-mqtt's own threaded network loop (loop_start/loop_stop) so that
no asyncio add_reader/add_writer calls are made.  This avoids the
NotImplementedError that occurs with qasync on Windows (ProactorEventLoop).
"""

from __future__ import annotations

import asyncio
import logging
import threading

import paho.mqtt.client as paho

from funscript_gateway.models import MqttOutputConfig

logger = logging.getLogger(__name__)


def _make_client() -> paho.Client:
    """Create a paho Client, using VERSION1 callbacks if paho >= 2.0."""
    try:
        return paho.Client(callback_api_version=paho.CallbackAPIVersion.VERSION1)
    except AttributeError:
        return paho.Client()


class MqttDriver:
    """Publishes on/off payloads to a configured MQTT topic.

    Lifecycle:
      await driver.connect()   — connects and starts paho's background thread
      await driver.set_state() — thread-safe publish (non-blocking)
      await driver.disconnect() — stops background thread and disconnects
    """

    def __init__(self, config: MqttOutputConfig) -> None:
        self.config = config
        self._last_sent: bool | None = None
        self._confirmed_state: bool | None = None
        self._connected_event = threading.Event()
        self._client = _make_client()

        if config.username:
            self._client.username_pw_set(
                config.username, config.password or None
            )

        self._client.on_connect = self._on_connect
        if config.status_topic:
            self._client.on_message = self._on_message

    # ------------------------------------------------------------------
    # Paho callbacks (called from paho's background thread)
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc) -> None:  # VERSION1 signature
        if rc == 0:
            self._connected_event.set()
            if self.config.status_topic:
                client.subscribe(self.config.status_topic)
            logger.info(
                "MQTT connected to %s:%d", self.config.broker_host, self.config.broker_port
            )
        else:
            logger.warning("MQTT connect failed, rc=%d", rc)

    def _on_message(self, client, userdata, message) -> None:
        try:
            payload = message.payload.decode("utf-8")
        except Exception:  # noqa: BLE001
            return
        if payload == self.config.payload_on:
            self._confirmed_state = True
        elif payload == self.config.payload_off:
            self._confirmed_state = False

    # ------------------------------------------------------------------
    # Async public interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Connect to the broker and start the background network loop."""
        await asyncio.to_thread(self._do_connect)

    def _do_connect(self) -> None:
        self._client.connect(
            self.config.broker_host,
            port=self.config.broker_port,
            keepalive=60,
        )
        self._client.loop_start()
        if not self._connected_event.wait(timeout=10.0):
            self._client.loop_stop()
            raise ConnectionError(
                f"MQTT broker {self.config.broker_host}:{self.config.broker_port} "
                "did not respond within 10 s"
            )

    async def set_state(self, on: bool) -> None:
        if on == self._last_sent:
            return
        payload = self.config.payload_on if on else self.config.payload_off
        # paho.publish() is thread-safe and queues the message internally.
        result = self._client.publish(
            self.config.command_topic,
            payload,
            qos=self.config.qos,
            retain=self.config.retain,
        )
        if result.rc != paho.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish error rc={result.rc}")
        self._last_sent = on
        logger.debug(
            "MQTT %s -> %s (topic: %s)",
            "ON" if on else "OFF",
            payload,
            self.config.command_topic,
        )

    async def disconnect(self) -> None:
        await asyncio.to_thread(self._do_disconnect)

    def _do_disconnect(self) -> None:
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:  # noqa: BLE001
            pass
