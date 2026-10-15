# Installation

`HA_enoceanmqtt` is a Home Assistant overlay for `enoceanmqtt`.
It exposes EnOcean telegrams to Home Assistant through MQTT Discovery.

## Overview

The project supports three installation modes:

- standalone installation on Linux;
- Docker deployment;
- Home Assistant addon installation.

## Standalone

Requirements:

- a working MQTT broker;
- an EnOcean transceiver available on the host;
- a configuration file based on `standalone/enoceanmqtt.conf.sample`.

Steps:

1. make `standalone/install.sh` executable;
2. run the script with the desired branch or version;
3. adapt `/etc/enoceanmqtt.conf`;
4. set `overlay = HA`;
5. set `mqtt_discovery_prefix`;
6. set `mqtt_prefix`;
7. declare your EnOcean devices.

You can then enable the `systemd` service from `standalone/enoceanmqtt.service`.

## Docker

The container expects:

- a mounted `/config` volume;
- access to the EnOcean device;
- a suitable `enoceanmqtt.conf` file under `/config`.

The example configuration is `docker/enoceanmqtt.conf.sample`.

Example run:

```sh
docker run --device=/dev/enocean -v my_docker_volume:/config makgitdev/ha_enoceanmqtt_dev-aarch64
```

## Home Assistant Addon

The addon mode requires:

- adding the addon repository;
- installing the Mosquitto addon if needed;
- a device configuration file under `/config`;
- enabling `mapping_file` and `eep_file` only if you want custom files.

The same core settings apply in every mode:

- `mqtt_discovery_prefix` drives Home Assistant discovery;
- `mqtt_prefix` drives the MQTT topics used by devices;
- `overlay = HA` enables the Home Assistant behavior.
