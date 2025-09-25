FROM python:3-alpine

ARG BUILD_VERSION="head"

# Copy enoceanmqtt.conf.sample to container
RUN mkdir /config
COPY docker/enoceanmqtt.conf.sample /config/enoceanmqtt.conf

# Create config volume
VOLUME /config

# Create Working Directory
WORKDIR /app

##add timezone-support
RUN apk add --no-cache tzdata
ENV TZ=Europe/London

# Install enoceanmqtt and requirements
COPY docker/requirements.txt .
RUN apk add --no-cache git && \
    python3 -m pip install --upgrade pip && \
    pip3 install -r requirements.txt && \
    pip3 install git+https://github.com/ChristopheHD/enocean.git && \
    git clone -b master --single-branch --depth 1 https://github.com/embyt/enocean-mqtt.git && \
    cd enocean-mqtt && python3 setup.py develop && cd .. && \
    echo "Installing from repository head" && \
    git clone -b develop --single-branch --depth 1 https://github.com/ChristopheHD/HA_enoceanmqtt.git ; \
    cp -rf ./HA_enoceanmqtt/enoceanmqtt enocean-mqtt && \
    rm -rf ./HA_enoceanmqtt

# Set entrypoint
ENTRYPOINT [ "python", "/usr/local/bin/enoceanmqtt", "/config/enoceanmqtt.conf" ]