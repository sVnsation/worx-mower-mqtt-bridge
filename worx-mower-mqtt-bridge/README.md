# Worx Mower MQTT Bridge Addon

This addon bridges the Worx Landroid, Kress Mission, Landxcape or Ferrex Smartmower Cloud MQTT Broker to a Private MQTT Broker, allowing you to control and monitor your lawnmower through Home Assistant. 

**Make sure to enter all required values in the configuration tab before the first launch.**

When using the MQTT Mosquitto broker addon from Home Assistant, leave the `private_broker_address` field empty to use auto-configuration. The addon will then automatically obtain the necessary MQTT connection details from the Home Assistant Supervisor API. 

**Note:** This feature is available only on Home Assistant OS or supervised installations with Supervisor API access. For other MQTT brokers or custom settings, manually configure the related fields.

The **complete documentation** for this addon is available [here](https://github.com/sVnsation/worx-mower-mqtt-bridge/).