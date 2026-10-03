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

## Pairing

Pairing is not needed for one-way sensors:

- they emit their telegrams;
- `enoceanmqtt` reads them directly;
- Home Assistant receives state updates over MQTT.

Pairing is required for some commands and actuators.
The recommended flow is:

1. put the device into pairing mode;
2. enable `LEARN` on the `ENOCEANMQTT` device in Home Assistant;
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
