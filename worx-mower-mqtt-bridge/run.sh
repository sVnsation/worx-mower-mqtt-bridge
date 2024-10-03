#!/usr/bin/with-contenv bashio

# Log level configuration
log_level="$(bashio::config 'log_level')"

# Cloud configuration
cloud_username="$(bashio::config 'cloud_username')"
cloud_password="$(bashio::config 'cloud_password')"
cloud_brand_prefix="$(bashio::config 'cloud_brand_prefix')"

# Private broker configuration
private_broker_address="$(bashio::config 'private_broker_address')"
private_broker_port="$(bashio::config 'private_broker_port')"
private_broker_username="$(bashio::config 'private_broker_username')"
private_broker_password="$(bashio::config 'private_broker_password')"

# Check if private_broker_address is empty or null
if [ -z "$private_broker_address" ]; then
    bashio::log.info "Private broker address was not provided. Using Home Assistant MQTT service (Mosquitto broker addon)."
    private_broker_address=$(bashio::services mqtt "host")
    private_broker_username=$(bashio::services mqtt "username")
    private_broker_password=$(bashio::services mqtt "password")
fi

# Log configuration
bashio::log.info "Log Level: ${log_level}"
bashio::log.info "Cloud Username: ${cloud_username}"
bashio::log.info "Cloud Brand Prefix: ${cloud_brand_prefix}"
bashio::log.info "Private Broker Address: ${private_broker_address}"
bashio::log.info "Private Broker Port: ${private_broker_port}"
bashio::log.info "Private Broker Username: ${private_broker_username}"

# Execute the Python script with all parameters
exec python3 -u mower_mqtt_bridge.py \
    "${log_level}" \
    "${cloud_username}" \
    "${cloud_password}" \
    "${cloud_brand_prefix}" \
    "${private_broker_address}" \
    "${private_broker_port}" \
    "${private_broker_username}" \
    "${private_broker_password}"
