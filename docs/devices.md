# Supported Devices

Support is organized by EEP.
When a device is not supported yet:

- only the RSSI sensor is exposed in Home Assistant;
- support can still be added through `mapping.yaml`.

## Core EEP families

- [x] `A5` 4BS sensors
- [x] `D2` VLD devices
- [x] `D5` 1BS contact sensors
- [x] `F6` RPS rocker switches

## Supported EEP profiles

- [x] `A5-02`
- [x] `A5-03`
- [x] `A5-05`
- [x] `A5-06`
- [x] `A5-07-01`
- [x] `A5-08`
- [x] `A5-09`
- [x] `A5-10`
- [x] `A5-12`
- [x] `A5-13-01` to `A5-13-06`
- [x] `A5-14-01`, `A5-14-09`, `A5-14-0A`
- [x] `A5-20-01`, `A5-20-04`, `A5-20-06`
- [x] `A5-30-02`, `A5-30-03`, `A5-30-04`
- [x] `A5-38-08`
- [x] `D2-01-01`, `D2-01-08`, `D2-01-09`, `D2-01-0A`, `D2-01-0B`, `D2-01-0C`, `D2-01-0D`, `D2-01-0E`, `D2-01-11`
- [x] `D2-03-0A`
- [x] `D2-05-00`, `D2-05-02`
- [x] `D2-06-01`
- [x] `D2-14-30`, `D2-14-41`
- [x] `D2-50-00`, `D2-50-01`, `D2-50-10`, `D2-50-11`
- [x] `F6-02-01`, `F6-02-02`
- [x] `F6-04-01`
- [x] `F6-05-01`

## Eltako profiles and aliases

- [x] `fhd60sb`
- [x] `fsb14`
- [x] `fsb61`
- [x] `fj62`
- [x] `tf61j`
- [x] `fsr14`
- [x] `fsr61`
- [x] `tf61l`
- [x] `fr62`
- [x] `fud14`
- [x] `fud61`
- [x] `fdg14`
- [x] `fld61`
- [x] `tf61d`
- [x] `fttb`
- [x] `tf100l`
- [x] `fbh55esb`
- [x] `futh65d`
- [x] `futh55d`
- [x] `futh55ed`
- [x] `ft`
- [x] `repeater`
- [x] `shutter`

## Special cases

- [x] virtual devices
- [x] Becker shutters
- [x] Eltako FAM14 workflows
- [x] NodOn soft button `D2-03-0A`

## Adding support

To add support:

1. identify the EEP;
2. add or adapt the mapping in `mapping.yaml`;
3. adjust `EEP.xml` if needed;
4. test the rendered entities in Home Assistant;
5. validate the MQTT topics and command behavior.

## Practical rule

The original wiki recommended treating support as an incremental task:

- start with state entities;
- then command entities;
- then virtual devices;
- then commissioning-specific edge cases.
