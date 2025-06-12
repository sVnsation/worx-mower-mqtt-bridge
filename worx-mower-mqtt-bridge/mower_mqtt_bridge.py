import sys
import logging
import requests
import json
import ssl
import threading
import time
import urllib.parse
import os
import signal
import paho.mqtt.client as mqtt

from uuid import uuid4
from datetime import datetime


"""Setup Log"""
PATH_SELF = os.path.dirname(os.path.abspath(__file__))
PATH_LOG_FILE = os.path.join(PATH_SELF, 'mower_mqtt_bridge.log')
LOG_LEVEL = 'debug'
logging.addLevelName(100, "NONE")
def get_logger(name):
    """Configure the logger component."""
    logger = logging.getLogger(name)
    # configure log formatter
    logFormatter = logging.Formatter("%(asctime)s [%(levelname)s] [%(funcName)s] %(message)s")
    # configure stream handler
    consoleHandler = logging.StreamHandler()
    consoleHandler.setFormatter(logFormatter)
    file_handler = logging.FileHandler(PATH_LOG_FILE)
    file_handler.setFormatter(logFormatter)
    if not len(logger.root.handlers):
        logger.setLevel(getattr(logging, LOG_LEVEL.upper()))
        logger.addHandler(consoleHandler)
        logger.addHandler(file_handler)
    return logger



"""Supported cloud config types"""
BRAND_CONFIGS = {
    "WX": {
        "cloud_name": "Worx",
        "cloud_endpoint": "api.worxlandroid.com",
        "cloud_auth_endpoint": "id.worx.com",
        "cloud_auth_client_id": "150da4d2-bb44-433b-9429-3773adc70a2a"
    },
    "KR": {
        "cloud_name": "Kress",
        "cloud_endpoint": "api.kress-robotik.com",
        "cloud_auth_endpoint": "id.kress.com",
        "cloud_auth_client_id": "931d4bc4-3192-405a-be78-98e43486dc59"
    },
    "LX": {
        "cloud_name": "Landxcape",
        "cloud_endpoint": "api.landxcape-services.com",
        "cloud_auth_endpoint": "id.landxcape-services.com",
        "cloud_auth_client_id": "dec998a9-066f-433b-987a-f5fc54d3af7c"
    },
    "SM": {
        "cloud_name": "Ferrex",
        "cloud_endpoint": "api.watermelon.smartmower.cloud",
        "cloud_auth_endpoint": "id.watermelon.smartmower.cloud",
        "cloud_auth_client_id": "10078D10-3840-474A-848A-5EED949AB0FC"
    }
}
CLOUD_NAME = ""
CLOUD_BRAND_PREFIX = ""
CLOUD_ENDPOINT = ""
CLOUD_AUTH_ENDPOINT = ""
CLOUD_AUTH_CLIENT_ID = ""

QOS_FLAG = 1

NUM_RETRIES = 5
MAX_BACKOFF = 120
BACKOFF_FACTOR = 3



class CloudEndpointAPI:
    """Cloud Endpoint API definition."""

    def __init__(self, username, password):
        self._log = get_logger("cloud_endpoint_api")
        self.access_token = None
        self.refresh_token = None
        self.token_expire = 0

        self.username = username
        self.password = password

    def backoff(self, retry):
        """Calculate backoff time."""
        val: float = BACKOFF_FACTOR * (2 ** (retry - 1))
        s = val if val <= MAX_BACKOFF else MAX_BACKOFF
        self._log.debug(f"retry after sleeping {s} seconds")
        time.sleep(s)

    def get_headers(self, access_token=None):
        """Generate headers dictionary."""
        headers = {"Accept": "application/json"}
        headers.update(
            {"Content-Type": "application/json"} if access_token is None
            else {"Authorization": f"Bearer {access_token}"}
        )
        return headers

    def request(self, url, request_body=None, headers=None, timeout=60):
        """Send a GET or POST request and return the response."""

        headers = headers or self.get_headers()
        method = 'POST' if request_body else 'GET'

        for retry in range(NUM_RETRIES):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    json=request_body,
                    headers=headers,
                    timeout=timeout,
                    cookies=None
                )
                response.raise_for_status()
                return response.json()

            except requests.exceptions.HTTPError as e:
                code = e.response.status_code
                if code == 504:
                    self._log.warning(f"HTTP Error {e} - Backing off and retrying...")
                    self.backoff(retry)
                    return
                else:
                    self._log.critical(f"HTTP Error: {e}")
                    self._log.critical(f"Serverresponse: {e.response.text}")
                sys.exit(1)

        self._log.critical(f"stopping after {NUM_RETRIES} retries")
        raise Exception("No Connection to Cloud Endpoint API")

    def get_token(self, update=False):
        """Get the access and refresh tokens."""
        url = f"https://{CLOUD_AUTH_ENDPOINT}/oauth/token"
        self._log.debug(f"request auth token from {url}")

        request_body = {
            "grant_type": "refresh_token" if update else "password",
            "client_id": CLOUD_AUTH_CLIENT_ID,
            "scope": "*",
            **({"refresh_token": self.refresh_token} if update else {"username": self.username, "password": self.password})
        }

        headers = self.get_headers()
        response = self.request(url, request_body, headers)
        self.access_token = response.get("access_token")
        self.refresh_token = response.get("refresh_token")

        if not self.access_token or not self.refresh_token:
            self._log.critical(f"Authentication for {self.username} failed!")
            raise Exception("AuthorizationError: Unauthorized")

        self.token_expire = int(time.time()) + int(response.get("expires_in"))
        expire_time_str = datetime.fromtimestamp(self.token_expire).strftime('%Y-%m-%d %H:%M:%S')
        self._log.info(f"Auth token successfully requested, valid until {expire_time_str}")

    def is_token_expired(self):
        token_expire_state = int(time.time()) >= self.token_expire
        self._log.debug("Auth Token has expired.") if token_expire_state else None
        return token_expire_state

    def update_token(self):
        """Refresh the tokens."""
        self.get_token(update = True)

    def get_mowers(self):
        """Get mowers associated with the account.
        Returns:
            str: JSON object containing available mowers associated with the account.
        """
        url = f"https://{CLOUD_ENDPOINT}/api/v2/product-items?status=1"
        headers = self.get_headers(self.access_token)
        mowers = self.request(url, headers=headers)
        for mower in mowers:
            # enrich model information
            model = self.get_model(mower["product_id"])
            self._log.debug(f"Model details: {model}")
            if model is not None:
                mower["model"] = {
                    "code": model["code"],
                    "friendly_name": f"{model['default_name']}{model['meters']} {model['product_year']}",
                }
            else:
                self._log.warning(f"No model found for product_id: {mower['product_id']}")
                mower["model"] = None
            self._log.debug(f"Mower details: {mower}")

        return mowers

    def get_model(self, product_id):
        """
        Retrieve model information for a given product ID.
        Returns:
            str: detailed product information if found, None otherwise.
        """
        url = f"https://{CLOUD_ENDPOINT}/api/v2/products"
        headers = self.get_headers(self.access_token)
        products = self.request(url, headers=headers)
        product_info = next((product for product in products if product["id"] == product_id), None)

        return product_info



class CloudMQTTClient:
    """Cloud MQTT Client definition."""

    def __init__(self):
        """Handle Cloud API for Connection to MQTT"""
        self._log = get_logger("cloud_mqtt")
        self._log.debug("Cloud MQTT Client Initializing")

        self.private_mqtt_client = None
        self.api = None

        self.uuid = uuid4()
        self.mowers = None
        self.endpoint = None
        self.user_id = None

        self.token_refresh_thread = None
        self.token_refresh_stop = threading.Event()

        self.client = None

    def set_private_mqtt_client(self, private_mqtt_client):
        self.private_mqtt_client = private_mqtt_client

    def get_mowers(self):
        return self.mowers

    def on_connect(self, client, userdata, flags, rc):
        """MQTT callback method."""
        if rc == 0:
            self._log.info("Cloud MQTT Client connection successful")
            for mower in self.mowers:
                self._log.debug(f"Subscribing to topic {mower['mqtt_topics']['command_out']}")
                client.subscribe(mower["mqtt_topics"]["command_out"], qos=QOS_FLAG)
        else:
            self._log.critical(f"Cloud MQTT Client connection failed. ResultCode={rc}")
            raise Exception("Cloud MQTT Client connection error")

    def on_message(self, client, userdata, msg):
        """MQTT callback method."""
        self._log.debug(f"Received message from Cloud MQTT Broker. Sending to Private MQTT Broker: {msg.payload.decode('utf-8')} on topic {msg.topic}")
        try:
            self.private_mqtt_client.publish(msg.topic, payload=msg.payload, qos=QOS_FLAG, retain=True)
        except Exception as e:
            self._log.error(e)

    def set_username_pw(self):
        """Set short lived JSON Web Token for AWS custom authentication on the MQTT client"""
        token_parts = self.api.access_token.translate(str.maketrans("_-", "/+")).split(".")
        username = "bot?jwt={0}.{1}&x-amz-customauthorizer-name=''&x-amz-customauthorizer-signature={2}".format(*map(urllib.parse.quote, token_parts))
        self.client.username_pw_set(username=username, password=None)

    def on_disconnect(self, client, userdata, rc):
        """MQTT callback method."""
        self._log.debug(f"Cloud MQTT Client disconnect with result code: {rc}")
        if rc == 7 and self.api.is_token_expired():
            self.token_refresh()
        else:
            self._log.debug("Cloud MQTT Client waiting for automatic reconnect to broker.")

    def publish(self, msg):
        """Publish message to the cloud."""
        self.client.publish(msg.topic, payload=msg.payload, qos=QOS_FLAG)

    def authenticate(self, username, password):
        """Authenticate against the API."""
        self.api = CloudEndpointAPI(username, password)
        self._log.info(f"Authenticating {username}")
        self.api.get_token()
        self.start_token_auto_refresh()
        return True

    def connect(self):
        """Connect to MQTT AWS IoT server"""
        self.mowers = self.api.get_mowers()
        if not self.mowers:
            raise ValueError("No mowers found")

        self.endpoint = self.mowers[0]["mqtt_endpoint"]
        self.user_id = self.mowers[0]["user_id"]

        self.client = mqtt.Client(
            client_id=f"{CLOUD_BRAND_PREFIX}/USER/{self.user_id}/bot/{self.uuid}",
            clean_session=False,
            userdata=None,
            reconnect_on_failure=True,
        )
        self.set_username_pw()

        ssl_context = ssl.create_default_context()
        ssl_context.set_alpn_protocols(["mqtt"])
        self.client.tls_set_context(context=ssl_context)
        self.client.reconnect_delay_set(min_delay=10, max_delay=300)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

        self._log.info(f"Connecting to Cloud MQTT Broker {self.endpoint}")
        self.client.connect_async(self.endpoint, 443, keepalive=45)

    def loop_start(self):
        self._log.debug("Cloud MQTT Client start loop")
        self.client.loop_start()

    def disconnect(self):
        self._log.info("Cloud MQTT Client disconnect")
        self.stop_token_auto_refresh()
        self.client.disconnect()

    def start_token_auto_refresh(self):
        if self.token_refresh_thread is None or not self.token_refresh_thread.is_alive():
            self.token_refresh_stop.clear()
            self.token_refresh_thread = threading.Thread(target=self.token_refresh_loop, daemon=True)
            self.token_refresh_thread.start()

    def stop_token_auto_refresh(self):
        self.token_refresh_stop.set()
        if self.token_refresh_thread:
            self.token_refresh_thread.join()

    def token_refresh_loop(self):
        while not self.token_refresh_stop.is_set():
            if self.api and self.api.token_expire:
                if self.api.is_token_expired():
                    self.token_refresh()
            time.sleep(10)

    def token_refresh(self):
        try:
            self._log.debug("Refresh access token and reconnect.")
            self.api.update_token()
            self.set_username_pw()
            self.client.reconnect()
        except Exception:
            self._log.critical("Failed to refresh access token and reconnect.", exc_info=True)


class PrivateMQTTClient(mqtt.Client):
    """Private MQTT Client definition."""

    def __init__(self, *args, **kwargs):
        super(PrivateMQTTClient, self).__init__(*args, **kwargs)
        self._log = get_logger("private_mqtt_client")
        self._log.debug("Private MQTT Client Initializing")
        self.cloud_client = None
        self.auto_discover_sent = False
        self.availability_topic = "mower_mqtt_bridge/status"
        self.will_set(self.availability_topic, payload="offline", qos=QOS_FLAG, retain=True)

    def set_cloud_client(self, cloud_client):
        self.cloud_client = cloud_client

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._log.info("Private MQTT Client connection successful")
            client.publish(self.availability_topic, payload="online", qos=QOS_FLAG, retain=True)
            try:
                mowers = self.cloud_client.get_mowers()
                for mower in mowers:
                    t = mower['mqtt_topics']['command_in']
                    self._log.debug(f"Subscribing to mower topic {t}")
                    client.subscribe(t, qos=QOS_FLAG)
                if not self.auto_discover_sent: 
                    MQTTDiscovery(mowers, self).send_discovery()
                    self.auto_discover_sent = True
            except Exception as e:
                self._log.error(f"Error subscribing to mower topic: {e}")

        else:
            self._log.critical(f"Private MQTT Client connection failed. ResultCode={rc}")
            raise Exception("Private MQTT Client Connection Error")

    def on_message(self, client, userdata, msg):
        self._log.debug(f"Received message from Private MQTT Broker. Sending to Cloud MQTT Broker: {msg.payload.decode('utf-8')} on topic {msg.topic}")
        try:
            self.cloud_client.publish(msg)
        except Exception as e:
            self._log.error(e)

    def on_disconnect(self, client, userdata, rc):
        self._log.debug(f"Private MQTT Client disconnect with result code:{rc}")

    def disconnect(self):
        self._log.info("Private MQTT Client disconnect")
        self.publish(self.availability_topic, payload="offline", qos=QOS_FLAG, retain=True)
        super().disconnect()

class MQTTDiscovery:
    def __init__(self, mowers, private_mqtt_client):
        self._log = get_logger("mqtt_discovery")
        self._log.debug("MQTT Discovery Initializing")
        self.mowers = mowers
        self.private_mqtt_client = private_mqtt_client

    def send_discovery(self):
        try:
            for mower in self.mowers:
                self.publish_lawn_mower_config(mower)
                self.publish_switches(mower)
                self.publish_sensors(mower)
                self.publish_binary_sensors(mower)
        except Exception as e:
            self._log.error(f"Error sending auto discover: {e}")

    def publish_config(self, device_type, config):
        discovery_topic = f"homeassistant/{device_type}/{config['uniq_id']}/config"
        self.private_mqtt_client.publish(discovery_topic, payload=json.dumps(config), qos=QOS_FLAG, retain=True)
        self._log.debug(f"Sent discovery message to {discovery_topic}")

    def publish_lawn_mower_config(self, mower):
        config = {
            "name": "Lawn Mower",
            "uniq_id": f"mower_{mower['mac_address']}",
            "activity_state_topic": mower['mqtt_topics']['command_out'],
            "activity_value_template": """
                {%- set status_map = {
                  1: "docked",
                  2: "mowing", 3: "mowing", 7: "mowing", 32: "mowing", 33: "mowing",
                  4: "returning", 5: "returning", 6: "returning", 30: "returning",
                  8: "error", 9: "error", 10: "error", 12: "error",
                  0: "paused", 11: "paused", 31: "paused", 34: "paused"
                } -%}
                {{- status_map[value_json.dat.ls] | default("unknown") -}}
            """,
            "avty_t": self.private_mqtt_client.availability_topic,
            "dock_command_topic": mower['mqtt_topics']['command_in'],
            "dock_command_template": '{"cmd":3}',
            "pause_command_topic": mower['mqtt_topics']['command_in'],
            "pause_command_template": '{"cmd":2}',
            "start_mowing_command_topic": mower['mqtt_topics']['command_in'],
            "start_mowing_command_template": '{"cmd":1}',
            "dev": {
                "mf": CLOUD_NAME,
                "name": mower['name'],
                "ids": [mower['mac_address']],
                "mdl": mower['model']['friendly_name'],
                "mdl_id": mower['model']['code'],
                "sw": mower['firmware_version'],
                "sn": mower['serial_number']
            },
        }
        self.publish_config("lawn_mower", config)

    def get_common_config(self, mower):
        return {
            "stat_t": mower['mqtt_topics']['command_out'],
            "dev": {
                "name": mower['name'],
                "ids": [mower['mac_address']],
            }
        }

    def publish_switches(self, mower):
        switches = [
            {
                "name": "Wi-Fi Lock",
                "uniq_id": f"wifi_lock_{mower['mac_address']}",
                "ic": "mdi:lock-open",
                "val_tpl": "{{ 'ON' if value_json.dat.lk == 1 else 'OFF' }}",
                "cmd_t": mower['mqtt_topics']['command_in'],
                "cmd_tpl": '{% if value == "ON" %}{"cmd":5}{% else %}{"cmd":6}{% endif %}',
            },
        ]
        for switch in switches:
            config = {**switch, **self.get_common_config(mower)}
            self.publish_config("switch", config)

    def publish_sensors(self, mower):
        sensors = [
            {
                "name": f"Status",
                "uniq_id": f"mower_status_{mower['mac_address']}",
                "ic": "mdi:robot-mower-outline",
                "val_tpl": """
                    {%- set status_map = {
                            0: "Idle",
                            1: "Home",
                            2: "Start sequence",
                            3: "Leaving home",
                            4: "Follow wire",
                            5: "Searching home",
                            6: "Searching wire",
                            7: "Mowing",
                            8: "Lifted",
                            9: "Trapped",
                            10: "Blade blocked",
                            11: "Debug",
                            12: "Remote control",
                            30: "Going home",
                            31: "Zone training",
                            32: "Border Cut",
                            33: "Searching zone",
                            34: "Pause" } -%}
                    {{- status_map[value_json.dat.ls] | default("unknown") -}}
                """,
                "json_attr_t": mower['mqtt_topics']['command_out'],
                "json_attr_tpl": """
                    {%- set j = value_json -%}
                    {%- set ns = namespace(attrs={}) -%}
                    {%- set attr_map = {
                        'last_update_time': j.cfg.tm,
                        'last_update_date': j.cfg.dt,
                        'schedule_active': j.cfg.sc.m,
                        'schedule_variation': j.cfg.sc.p,
                        'schedule_days': j.cfg.sc.d,
                        'rain_delay': j.cfg.rd,
                        'serial_number': j.cfg.sn,
                        'mac_address': j.dat.mac,
                        'firmware': j.dat.fw,
                        'battery_temperature': j.dat.bt.t,
                        'battery_voltage': j.dat.bt.v,
                        'battery_charge_percent': j.dat.bt.p,
                        'battery_charge_cycles': j.dat.bt.nr,
                        'battery_charging': j.dat.bt.c,
                        'roll': j.dat.dmp[0],
                        'yaw': j.dat.dmp[1],
                        'pitch': j.dat.dmp[2],
                        'status_code': j.dat.ls,
                        'error_code': j.dat.le,
                        'zone_current': j.dat.lz,
                        'zone_mz': j.cfg.mz,
                        'zone_mzv': j.cfg.mzv,
                        'wifi_link_quality': j.dat.rsi,
                    } -%}
                    {%- for key, value in attr_map.items() -%}
                        {%- if value is defined -%}
                            {%- set ns.attrs = dict(ns.attrs, **{key: value}) -%}
                        {%- endif -%}
                    {%- endfor -%}
                    {%- if j.dat.st.b is defined -%}
                        {%- set t = j.dat.st.b -%}
                        {%- set ns.attrs = dict(ns.attrs, **{'blade_time': '%0dd %0.02dh %0.02dmin' | format(t // 1440, ((t % 1440) // 60), t % 60)}) -%}
                    {%- endif -%}
                    {%- if j.dat.st.wt is defined -%}
                        {%- set t = j.dat.st.wt -%}
                        {%- set ns.attrs = dict(ns.attrs, **{'mowing_time': '%0dd %0.02dh %0.02dmin' | format(t // 1440, ((t % 1440) // 60), t % 60)}) -%}
                    {%- endif -%}
                    {%- if j.dat.st.d is defined -%}
                        {%- set dist = (j.dat.st.d | float(0) / 1000) | int(0) | string + ' km' -%}
                        {%- set ns.attrs = dict(ns.attrs, **{'driven_distance': dist}) -%}
                    {%- endif -%}
                    {{- ns.attrs | tojson -}}
                """
                ,
            },
            {
                "name": f"Error",
                "uniq_id": f"mower_error_{mower['mac_address']}",
                "ic": "mdi:alert-circle",
                "val_tpl": """
                    {%- set mapper = {
                            0: "No errors",
                            1: "Trapped",
                            2: "Lifted",
                            3: "Wire missing",
                            4: "Outside wire",
                            5: "Rain Delay",
                            6: "Close door to mow",
                            7: "Close door to go home",
                            8: "Blade motor blocked",
                            9: "Wheel motor blocked",
                            10: "Trapped timeout",
                            11: "Upside down",
                            12: "Battery low",
                            13: "Reverse wire",
                            14: "Charge error",
                            15: "Timeout finding home",
                            16: "Mower locked",
                            17: "Battery temperature too high/low" } %}
                    {%- set state = value_json.dat.le | int(-1) -%}
                    {{- mapper[state] if state in mapper else 'Unknown: ' ~ state -}}
                """,
            },
            {
                "name": f"Battery Level",
                "uniq_id": f"mower_battery_level_{mower['mac_address']}",
                "unit_of_meas": '%',
                "dev_cla": 'battery',
                "val_tpl": "{{ value_json.dat.bt.p | int(0) }}",
            },
            {
                "name": f"Battery Voltage",
                "uniq_id": f"mower_battery_voltage_{mower['mac_address']}",
                "unit_of_meas": 'V',
                "dev_cla": 'voltage',
                "val_tpl": "{{ value_json.dat.bt.v | float(0) }}",
                "ent_cat": "diagnostic",
            },
            {
                "name": f"Battery Temperature",
                "uniq_id": f"mower_battery_temperature_{mower['mac_address']}",
                "unit_of_meas": '°C',
                "dev_cla": 'temperature',
                "val_tpl": "{{ value_json.dat.bt.t | float(0) }}",
                "ent_cat": "diagnostic",
            },
            {
                "name": f"Battery Cycles",
                "uniq_id": f"mower_battery_cycles_{mower['mac_address']}",
                "val_tpl": "{{ value_json.dat.bt.nr | int(0) }}",
                "ic": 'mdi:battery-sync',
                "ent_cat": "diagnostic",
            },
            {
                "name": f"WiFi Quality",
                "uniq_id": f"mower_wifi_{mower['mac_address']}",
                "val_tpl": "{{ value_json.dat.rsi | int(-100) }}",
                "dev_cla": "signal_strength",
                "unit_of_meas": "dBm",
                "ent_cat": "diagnostic",
            },
            {
                "name": f"Last Update",
                "uniq_id": f"mower_lastupdate_{mower['mac_address']}",
                "ic": 'mdi:clock',
                "val_tpl": "{{ strptime(value_json.cfg.dt + ' ' + value_json.cfg.tm, '%d/%m/%Y %H:%M:%S').strftime('%d.%m.%y %H:%M') }}"
            }
        ]
        for sensor in sensors:
            config = {**sensor, **self.get_common_config(mower)}
            self.publish_config("sensor", config)

    def publish_binary_sensors(self, mower):
        binary_sensors = [
            {
                "name": f"Mowing",
                "uniq_id": f"mower_mowing_{mower['mac_address']}",
                "val_tpl": "{{ 'ON' if value_json.dat.ls == 7 else 'OFF' }}",
                "dev_cla": "running",
                "ent_cat": "diagnostic",
            },
            {
                "name": f"Battery Charging",
                "uniq_id": f"mower_battery_charging_{mower['mac_address']}",
                "val_tpl": "{{ 'ON' if value_json.dat.bt.c | int(0) == 1 else 'OFF' }}",
                "dev_cla": "battery_charging",
                "ent_cat": "diagnostic",
            }
        ]
        for sensor in binary_sensors:
            config = {**sensor, **self.get_common_config(mower)}
            self.publish_config("binary_sensor", config)



def main():
    """Setup Logging"""
    global LOG_LEVEL
    LOG_LEVEL = sys.argv[1]
    _log = get_logger("mower_mqtt_bridge")
    _log.info("Starting Mower MQTT Bridge...")

    """Handle arguments and set variables"""
    global CLOUD_BRAND_PREFIX, CLOUD_NAME, CLOUD_ENDPOINT, CLOUD_AUTH_ENDPOINT, CLOUD_AUTH_CLIENT_ID
    cloud_username = sys.argv[2]
    cloud_password = sys.argv[3]
    CLOUD_BRAND_PREFIX = sys.argv[4]
    if CLOUD_BRAND_PREFIX in BRAND_CONFIGS:
        c = BRAND_CONFIGS[CLOUD_BRAND_PREFIX]
        CLOUD_NAME = c["cloud_name"]
        CLOUD_ENDPOINT = c["cloud_endpoint"]
        CLOUD_AUTH_ENDPOINT = c["cloud_auth_endpoint"]
        CLOUD_AUTH_CLIENT_ID = c["cloud_auth_client_id"]
    else:
        self._log.critical(f"Invalid CLOUD_BRAND_PREFIX: {CLOUD_BRAND_PREFIX}")
        sys.exit(1)
    private_broker_adress = sys.argv[5]
    private_broker_port = int(sys.argv[6])
    private_broker_username = sys.argv[7] if len(sys.argv) > 7 else ""
    private_broker_password = sys.argv[8] if len(sys.argv) > 8 else ""

    """Setup Private and Cloud MQTT Client"""
    private_client = PrivateMQTTClient(client_id="mower_mqtt_bridge")
    if private_broker_username and private_broker_password and private_broker_username != "null" and private_broker_password != "null":
        private_client.username_pw_set(private_broker_username, private_broker_password)
    private_client.connect_async(private_broker_adress, port=private_broker_port, keepalive=45)

    cloud_client = CloudMQTTClient()
    cloud_client.authenticate(cloud_username, cloud_password)
    cloud_client.connect()
    cloud_client.set_private_mqtt_client(private_client)
    private_client.set_cloud_client(cloud_client)

    cloud_client.loop_start()
    private_client.loop_start()

    """Force refresh to get first data"""
    mowers = cloud_client.get_mowers()
    for mower in mowers:
        msg = mqtt.MQTTMessage()
        msg.payload = '{"cmd":0}'.encode('utf-8')
        msg.topic = mower['mqtt_topics']['command_in'].encode('utf-8')
        cloud_client.publish(msg)

    """Gracefull disconnect on programm exit"""
    def stop(signum, frame):
        _log.info("Stopping Mower MQTT Bridge...")
        cloud_client.disconnect()
        private_client.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    """Monitoring connections to MQTT brokers"""
    last_state_client_connected = {
        'cloud': None,
        'private': None
    }

    while True:
        time.sleep(1)
        connections = {
            'cloud': cloud_client.client.is_connected(),
            'private': private_client.is_connected()
        }
        for broker, is_connected in connections.items():
            if is_connected != last_state_client_connected[broker]:
                _log.debug(f"{broker.capitalize()} MQTT Broker connected = {is_connected}")
                last_state_client_connected[broker] = is_connected

if __name__ == "__main__":
    main()
