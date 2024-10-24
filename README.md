# Worx Mower MQTT Bridge Addon

## Overview

This addon bridges the Worx Landroid, Kress Mission, Landxcape or Ferrex Smartmower Cloud MQTT Broker to a Private MQTT Broker, allowing you to control and monitor your lawnmower through Home Assistant. 

It's also enabling other MQTT-compatible software to access and interact with your mower's data and functions. By exposing the mower's information and controls to a private MQTT broker, this addon facilitates integration with various smart home platforms, custom scripts, and third-party applications that support MQTT communication.

**Make sure to enter all required values in the configuration tab before the first launch.**

**Note:** While the code is designed to support multiple mowers, it has currently only been tested with a single mower. Be aware that deploying the system with multiple mowers may require additional testing and potential adjustments to ensure proper functionality across all units.

## Installation

To install this addon you need to add this GitHub repository as a custom add-on to Home Assistant, follow these steps:

1. In the Home Assistant Settings panel click on Add-ons.

2. Click on the "Add-on Store" button on the bottom right.

3. Click on the three dots in the top right corner and select "Repositories".

4. In the "Add repository" field, paste the following URL:
   ```
   https://github.com/sVnsation/worx-mower-mqtt-bridge
   ```

5. Click "Add" to save the repository.

6. The add-on should now appear in your add-on store. Find it in the list and click on it.

7. Click "Install" to add the add-on to your Home Assistant instance.

8. After installation, go to the add-on's Configuration tab and fill in the required fields.

9. Start the add-on and check the logs to ensure it's running correctly.

## Home Assistant MQTT Broker auto-configuration

If you are using the MQTT Mosquitto broker addon from Home Assistant, you can take advantage of the auto-configuration feature. To use this:

1. Leave the `private_broker_address` field empty in your configuration.
2. The addon will automatically retrieve the necessary MQTT connection information from the Home Assistant Supervisor API.

**Note:** This auto-configuration only works when running the addon on Home Assistant OS or a supervised installation that provides access to the Supervisor API.
If you prefer to use a different MQTT broker or need to specify custom settings, you can still manually configure the `private_broker_address` and related fields.

## Home Assistant MQTT Device Discovery

This addon supports Home Assistant's MQTT Discovery feature which ensures that your lawnmower is immediately available in Home Assistant after the addon is set up, providing a seamless integration experience.
It automatically creates and configures entities in Home Assistant for your lawnmower.

If you need to customize any of the auto-discovered entities, you can do so through Home Assistant's entity customization options.

![screenshot mqtt integration](https://github.com/sVnsation/worx-mower-mqtt-bridge/blob/main/docs/images/ha_mqtt_integration.png?raw=true "HA MQTT Integration")

### Auto-discovered Entities

The following entities are automatically created for each mower:

1. **Lawn Mower**: A lawn mower entity with start, pause, and dock commands.
2. **Switch Wi-Fi Lock**: Anti-theft protection
3. **Sensors**:
   - Status: Current status of the mower
   - Error: Any error messages
   - Battery Level: Current battery percentage
   - Battery Voltage: Current battery voltage
   - Battery Temperature: Current battery temperature
   - Battery Cycles: Number of battery charge cycles
   - WiFi Quality: WiFi signal strength
   - Last Update: Timestamp of the last update from the mower

4. **Binary Sensors**:
   - Mowing: Indicates if the mower is currently mowing
   - Battery Charging: Indicates if the battery is currently charging

### Discovery Process

1. When the addon connects to the private MQTT broker, it automatically sends discovery messages for each mower.
2. These messages are published to the `homeassistant/` topic, which Home Assistant monitors for auto-discovery configurations.
3. Home Assistant then creates and configures the entities based on the discovery information.

## Addon Configuration Options

| Option | Type | Required | Description |
|:-------|:-----|:---------|:------------|
| `cloud_username` | string | Yes | Your cloud username |
| `cloud_password` | password | Yes | Your cloud password |
| `cloud_brand_prefix` | string | Yes | Cloud Brand Specific Values. See below.  |
| `private_broker_address` | string | No | The address of your private MQTT broker |
| `private_broker_port` | number | No | The port of your private MQTT broker (default: 1883) |
| `private_broker_username` | string | No | The username for your private MQTT broker (if required) |
| `private_broker_password` | password | No | The password for your private MQTT broker (if required) |
| `log_level` | string | Yes | How much information is logged. |

### Cloud Brand Specific Values

Possible values for cloud_brand_prefix option:

**Worx Landroid**

- `cloud_brand_prefix`: WX

**Kress Mission**

- `cloud_brand_prefix`: KR

**Landxcape**

- `cloud_brand_prefix`: LX

**Ferrex Smartmower**

- `cloud_brand_prefix`: SM


### Example Configuration

```yaml
cloud_username: your_username@example.com
cloud_password: your_password
cloud_brand_prefix: WX
private_broker_address: 192.168.1.100
private_broker_port: 1883
private_broker_username: mqtt_user
private_broker_password: mqtt_password
log_level: info
```


## Advanced Configuration with Template Sensors

While the addon provides auto-discovered entities for basic mower control and monitoring, users can create additional template sensors in Home Assistant to access more advanced functionalities such as **schedules** and **zones**. This can be done by utilizing the MQTT topics for each mower.

To create custom template sensors or automations, you can use the following MQTT topics for each mower:

   - Command Out Topic: information coming from the mower
   - Command In Topic: send commands or settings to the mower

**Note:** You can look up the both Topics in the Log-Tab of the Addon, with log_level set to debug.

### Creating Custom Template Sensors

Here's how you can set up custom template sensors in your Home Assistant configuration:

**1.** First, create an MQTT sensor that subscribes to the mower's command out topic:

```yaml
mqtt:
  sensor:
    - name: "Mower Raw Data"
      state_topic: "YOUR_PREFIX/YOUR_SERIAL_NUMBER/commandOut"
      value_template: "{{ value_json }}"
```

**2.** Then, create template sensors to extract specific information:

```yaml
template:
  - sensor:
      - name: "Mower Schedule"
        state: >
          {% set data = states('sensor.mower_raw_data') | from_json %}
          {{ data.cfg.sc | to_json }}

      - name: "Mower Schedule Active"
        state: >
          {% set data = states('sensor.mower_raw_data') | from_json %}
          {{ data.cfg.sc.m }}

      - name: "Mower Current Zone"
        state: >
          {% set data = states('sensor.mower_raw_data') | from_json %}
          {{ data.dat.lz }}

      - name: "Mower Rain Delay"
        state: >
          {% set data = states('sensor.mower_raw_data') | from_json %}
          {{ data.cfg.rd }}
```

### Sending Commands

You can also create scripts or automations to send commands to your mower using the command in topic. For example:

```yaml
script:
  set_rain_delay_timeextenstion:
    sequence:
      - service: mqtt.publish
        data:
          topic: "YOUR_PREFIX/YOUR_SERIAL_NUMBER/commandIn"
          payload: "{"rd":60,"sc":{"p":20}}"
```

This script would send a command to set the mower rain delay to 60 minutes and time extension to 20%.

By using these custom template sensors and commands, you can access and control more advanced features of your mower directly from Home Assistant, complementing the auto-discovered entities provided by the addon.


## Credits

This project was inspired and supported by findings and concepts from the following projects:

- [pyWorxCloud](https://github.com/MTrab/pyworxcloud): A PyPI module for communicating with Worx Cloud mowers.
- [ioBroker.worx](https://github.com/iobroker-community-adapters/ioBroker.worx): An ioBroker adapter for controlling Worx Landroid, Kress, Landxcape, and Ferrex mowers.
- [AvaDeskApp](https://github.com/EishaV/Avalonia-Desktop-App): A portable application for Positec mowers based on the .NETCore framework.

Many thanks to the developers of these projects for their contributions to the open source community.
