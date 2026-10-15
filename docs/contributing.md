# Contributing

To contribute useful device support:

- add or fix the mapping in `mapping.yaml`;
- adapt `EEP.xml` if needed;
- verify the behavior on real hardware;
- open a pull request with the test details.

Notes:

- avoid adding unnecessary entities;
- keep MQTT topics and structure simple;
- do not simulate a state that does not exist on the EnOcean side.

## Local debugging

If you modify mapping or configuration files in an addon:

1. stop the addon;
2. edit the file you need;
3. restart the addon;
4. verify the generated entities in Home Assistant.
