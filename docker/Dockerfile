FROM python:3.14-alpine AS builder

ARG BUILD_VERSION="null"

WORKDIR /build

RUN apk add --no-cache git

COPY docker/requirements.txt /build/requirements.txt
RUN python3 -m pip install --upgrade pip setuptools wheel && \
    pip3 install --no-cache-dir git+https://github.com/ChristopheHD/enocean.git && \
    pip3 install --no-cache-dir -r /build/requirements.txt
COPY enoceanmqtt /usr/local/lib/python3.14/site-packages/enoceanmqtt
RUN printf '%s\n' "$BUILD_VERSION" > /usr/local/lib/python3.14/site-packages/enoceanmqtt/VERSION
# Remove build-only Python packaging helpers before exporting /usr/local to the final image.
RUN pip3 uninstall -y setuptools wheel

FROM python:3.14-alpine

WORKDIR /config
COPY docker/enoceanmqtt.conf.sample /config/enoceanmqtt.conf

VOLUME /config

WORKDIR /app

RUN apk add --no-cache tzdata
ENV TZ=Europe/London

COPY --from=builder /usr/local /usr/local

STOPSIGNAL SIGINT

ENTRYPOINT [ "python", "/usr/local/bin/enoceanmqtt", "/config/enoceanmqtt.conf" ]
