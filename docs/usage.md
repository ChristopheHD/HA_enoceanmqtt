# Normal Usage

## Configuration model

A device is declared in the configuration file like this:

```ini
[my_device]
address = 0x01234567
rorg = 0xF6
func = 0x02
type = 0x01
```

Key fields:

- `address`
- `rorg`
- `func`
- `type`
- `sender` for virtual devices
- `virtual = 1` for emulated devices
The section name becomes the MQTT and Home Assistant device name.

## Device management UI

With the Home Assistant overlay enabled, the bridge serves a device-management
page at `http://<bridge-host>:8080/` by default. It can add and remove EEP- or
model-based devices without restarting the bridge. EEP and model choices are
read from the configured `mapping.yaml`.

The UI stores device definitions in the existing TinyDB file. On the first
startup with the Home Assistant overlay, device sections from the INI
configuration are imported into TinyDB once. The INI file is left unchanged;
a migration marker in TinyDB prevents the import from running again on
subsequent startups. TinyDB is the source of device definitions managed by the
UI after migration.

The web server settings are:

```ini
webui_enabled = true
webui_host = 0.0.0.0
webui_port = 8080
```

The server is designed to work behind a path-prefix reverse proxy such as
future Home Assistant Ingress integration. It does not provide its own login;
do not expose the port to untrusted networks. Restrict access to a trusted
network or an authenticated proxy.

## Pairing

Pairing is not needed for one-way sensors:

- they emit their telegrams;
- `enoceanmqtt` reads them directly;
- Home Assistant receives state updates over MQTT.

Pairing is required for some commands and actuators.
The recommended flow is:

1. enable `LEARN` on the `ENOCEANMQTT` device in Home Assistant;
2. put the device into pairing mode;
3. disable `LEARN` after pairing.

## Identifying a device

If the device address is unknown:

1. open the logs;
2. trigger a radio action on the device;
3. read the address reported in the `unknown sensor` message.

If the transceiver ID is unknown:

1. open the `ENOCEANMQTT` device in the Home Assistant MQTT integration;
2. read the `Base ID`.

## Removing a device

To remove a device from Home Assistant:

1. delete its declaration from the configuration file;
2. restart the service, or;
3. in the MQTT integration, open the device and use the delete button if one is exposed.

## Mapping files

Device support is driven by:

- `mapping.yaml` for EEP-to-Home-Assistant mapping;
- `EEP.xml` for the EEP definitions used by the EnOcean library.

Typical uses:

- add an unsupported device;
- adjust an existing behavior;
- test a device variant without changing the main repository logic.

## Virtual devices

Virtual devices let Home Assistant issue commands as if they were physical devices.

They use:

- a fake `address`, usually `0xFFFFFFFF`;
- a `sender` within the `Base ID` range;
- `virtual = 1`.

Typical uses:

- virtual rocker switches;
- virtual buttons to control Eltako actuators;
- workflows where Home Assistant acts as a remote control.

## Eltako FAM14

For some Eltako devices, virtual buttons can be used to work around the limits of direct pairing.

The idea is:

- create a virtual actuator in `enoceanmqtt`;
- use the state feedback emitted by the Eltako system;
- build a Home Assistant template switch on top of it.

## NodOn soft button

The NodOn D2-03-0A button exposes:

- single press;
- double press;
- long press;
- long press release;
- battery.

The project maps it to multiple entities, but the historical wiki recommendation is to use Home Assistant device triggers for automations instead.

## Examples

The wiki examples illustrate:

- declaring a device;
- configuring a virtual device;
- using Home Assistant templates to drive relays.

The general flow is:

- `enoceanmqtt` publishes EnOcean state;
- Home Assistant consumes it through MQTT Discovery;
- commands are sent on `req` topics.
