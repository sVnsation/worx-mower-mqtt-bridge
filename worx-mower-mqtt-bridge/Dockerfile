ARG BUILD_FROM
FROM $BUILD_FROM

ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Install requirements for add-on
RUN apk add --no-cache python3 py3-setuptools py3-pip
RUN pip3 install --no-cache-dir requests paho-mqtt~=1.6

# Copy data for add-on
COPY run.sh /
COPY mower_mqtt_bridge.py /

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]