# Author: Marc Alexandre K. <marcalexandrek-developer@yahoo.fr>
"""this class is a Home Assistant overlay for enoceanmqtt"""

import logging
import copy
import os
import time
import json
import queue
from threading import Event

import yaml

import enocean.utils
from enoceanmqtt.communicator import Communicator
from enoceanmqtt.overlays.homeassistant.device_manager import DeviceManager
from enoceanmqtt.overlays.homeassistant.device_web import DeviceWebServer

REPOSITORY_URL = 'https://github.com/ChristopheHD/HA_enoceanmqtt'

class HACommunicator(Communicator):
    '''Home Assistant-oriented Communicator subclass for enoceanmqtt'''
    _mqtt_discovery_prefix = None
    _devmgr = None
    _system_status_topic = {}

    def __init__(self, config, sensors):
        self.conf = config
        self._device_change_queue = queue.Queue()

        # Read mapping file
        mapping_file = config.get('mapping_file')
        if not mapping_file:
            mapping_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mapping.yaml')
        with open(mapping_file, 'r', encoding="utf-8") as file:
            self._ha_mapping = yaml.safe_load(file)
        logging.info("Mapping file correctly read: %s", mapping_file)
        self._normalize_discovery_mapping(self._ha_mapping)

        # TinyDB stores both the UI-managed configuration and discovery metadata.
        self._devmgr = DeviceManager(config)
        self._devmgr.migrate_ini_devices(
            sensors,
            config.get('mqtt_prefix', 'enocean/')
        )
        sensors = []
        for device in self._devmgr.get_config_devices():
            sensors.extend(self._expand_device(device))

        # Retrieve MQTT discovery prefix from configuration and make sure there is a trailing '/'
        self._mqtt_discovery_prefix = config.get('mqtt_discovery_prefix', 'homeassistant/')
        if self._mqtt_discovery_prefix[-1] != '/':
            self._mqtt_discovery_prefix += '/'

        # Init
        super().__init__(config, sensors)

        # Disable Teach-in on startup
        self.enocean.teach_in = False
        logging.info("Auto Teach-in is %s", "enabled" if self.enocean.teach_in else "disabled")

        self._web_server = None
        if str(config.get('webui_enabled', 'true')).lower() not in ('false', '0', 'no'):
            logging.warning(
                "Device management UI has no built-in authentication; restrict network "
                "access or place it behind an authenticated proxy"
            )
            self._web_server = DeviceWebServer(
                self._devmgr,
                self._ha_mapping,
                self._enqueue_device_change,
                config.get('webui_host', '0.0.0.0'),
                int(config.get('webui_port', 8080))
            )
            self._web_server.start()

    def _expand_device(self, device):
        """Turn a UI/INI device definition into the sensor records used by the bridge."""
        prefix = self.conf.get('mqtt_prefix', 'enocean/')
        base_name = prefix + device['name']
        sensors = []

        if device.get('model'):
            try:
                manufacturer, model = device['model'].lower().split('/', 1)
            except ValueError:
                logging.warning("Ignoring invalid model reference for %s", device['name'])
                return sensors
            model_map = self._ha_mapping.get(manufacturer, {}).get(model, {})
            for new_sensor in copy.deepcopy(model_map.get('device_config', [])):
                rorg = new_sensor.get('rorg')
                new_sensor['name'] = base_name + '/' + str(rorg)[2:4].lower()
                new_sensor['address'] = device['address']
                for field in ('default_data', 'sender', 'ignore', 'virtual'):
                    if field in device:
                        new_sensor[field] = device[field]
                new_sensor['manufacturer'] = manufacturer
                new_sensor['model'] = model
                for field in ('rorg', 'func', 'type'):
                    new_sensor[field] = self._mapping_number(new_sensor[field])
                new_sensor['publish_json'] = '1'
                new_sensor['publish_rssi'] = '1'
                new_sensor['publish_date'] = '1'
                new_sensor.setdefault('persistent', '1')
                new_sensor['_managed_id'] = device['id']
                sensors.append(new_sensor)
            return sensors

        new_sensor = copy.deepcopy(device)
        new_sensor['name'] = base_name
        new_sensor['_managed_id'] = device['id']
        for field in ('address', 'rorg', 'func', 'type', 'sender'):
            if field in new_sensor:
                new_sensor[field] = self._mapping_number(new_sensor[field])

        try:
            device_map = self._ha_mapping[new_sensor['rorg']][new_sensor['func']][
                new_sensor['type']
            ].get('device_config', {})
        except KeyError:
            device_map = {}
        for field in ('command', 'channel', 'log_learn', 'direction', 'answer'):
            if device_map.get(field):
                new_sensor[field] = device_map[field]
        if str(new_sensor.get('ignore')) not in ('True', 'true', '1'):
            new_sensor['persistent'] = device_map.get('persistent', '1')
            new_sensor['publish_json'] = '1'
            new_sensor['publish_rssi'] = '1'
            new_sensor['publish_date'] = '1'
        sensors.append(new_sensor)
        return sensors

    @staticmethod
    def _mapping_number(value):
        return int(value, 0) if isinstance(value, str) else int(value)

    def _enqueue_device_change(self, action, device):
        """Apply a web UI change on the bridge loop thread."""
        completed = Event()
        result = {}
        self._device_change_queue.put((action, device, completed, result))
        if not completed.wait(30):
            raise TimeoutError("The bridge did not apply the device change in time")
        if 'error' in result:
            raise RuntimeError(str(result['error']))

    def _process_pending_actions(self):
        while True:
            try:
                action, device, completed, result = self._device_change_queue.get_nowait()
            except queue.Empty:
                return
            try:
                if action == 'add':
                    self._add_runtime_device(device)
                elif action == 'delete':
                    self._remove_runtime_device(device)
                else:
                    raise ValueError("Unknown device action")
            except Exception as error:
                logging.exception("Could not apply device %s", action)
                result['error'] = error
            finally:
                completed.set()

    def _add_runtime_device(self, device):
        with self._sensor_lock:
            new_sensors = self._expand_device(device)
            self.sensors.extend(new_sensors)
            self._index_sensors()
            if self._mqtt_connected:
                for sensor in new_sensors:
                    self.mqtt.subscribe(sensor['name'] + '/req/#')
                    self._discover_sensor(sensor)

    def _remove_runtime_device(self, device):
        prefix = self.conf.get('mqtt_prefix', 'enocean/')
        base_name = prefix + device['name']
        with self._sensor_lock:
            removed_sensors = [
                sensor for sensor in self.sensors
                if sensor.get('_managed_id') == device['id']
            ]
            if device.get('model'):
                manufacturer, model = device['model'].lower().split('/', 1)
                reference = manufacturer + '_' + model
                sender = self._format_sender(device.get('sender'))
                uid = reference + '_' + format(device['address'], '08X') + '_' + sender
            else:
                eep = format(
                    (device['rorg'] << 16) + (device['func'] << 8) + device['type'],
                    '06X'
                )
                sender = self._format_sender(device.get('sender'))
                uid = eep + '_' + format(device['address'], '08X') + '_' + sender

            if self._mqtt_connected:
                discovery = self._devmgr.db_get_device_by_field('uid', uid)
                if discovery:
                    for config_topic in discovery.get('cfgtopics', []):
                        self.mqtt.publish(
                            self._mqtt_discovery_prefix + config_topic,
                            '',
                            retain=True
                        )
                for sensor in removed_sensors:
                    self.mqtt.unsubscribe(sensor['name'] + '/req/#')
                    self.mqtt.unsubscribe(sensor['name'] + '/__system/#')
                if discovery:
                    self._devmgr.db_remove_device_by_field('uid', uid)
                else:
                    self._devmgr.db_remove_device_by_field('name', base_name)

            self.sensors = [
                sensor for sensor in self.sensors
                if sensor.get('_managed_id') != device['id']
            ]
            self._index_sensors()

    @staticmethod
    def _format_sender(sender):
        try:
            return format(int(sender), '08X')
        except (TypeError, ValueError):
            return 'NONE'

    def _discover_sensor(self, sensor):
        if sensor.get('model'):
            sender = self._format_sender(sensor.get('sender'))
            uid = (
                sensor['manufacturer'] + '_' + sensor['model'] + '_'
                + format(sensor['address'], '08X') + '_' + sender
            )
            device = self._devmgr.db_get_device_by_field('uid', uid)
            previous_topics = device.get('cfgtopics', []) if device else []
            self._mqtt_discovery_model(sensor, previous_topics)
        else:
            sender = self._format_sender(sensor.get('sender'))
            eep = format(
                (sensor['rorg'] << 16) + (sensor['func'] << 8) + sensor['type'],
                '06X'
            )
            uid = eep + '_' + format(sensor['address'], '08X') + '_' + sender
            device = self._devmgr.db_get_device_by_field('uid', uid)
            previous_topics = device.get('cfgtopics', []) if device else []
            self._mqtt_discovery_eep(sensor, previous_topics)

    def shutdown(self):
        if self._web_server is not None:
            self._web_server.stop()
        super().shutdown()

    #=============================================================================================
    # MQTT CLIENT
    #=============================================================================================
    def _on_connect(self, mqtt_client, _userdata, _flags, return_code):
        with self._sensor_lock:
            self._handle_connection(mqtt_client, _userdata, _flags, return_code)

    def _handle_connection(self, mqtt_client, _userdata, _flags, return_code):
        '''callback for when the client receives a CONNACK response from the MQTT server.'''
        if return_code == 0:
            self._mqtt_connected = True
            logging.info("Succesfully connected to MQTT broker.")
            # listen to enocean send requests
            for cur_sensor in self.sensors:
                mqtt_client.subscribe(cur_sensor['name']+'/req/#')

            # Create the retained bridge state topic immediately; it will be
            # replaced by "online" once the bridge is fully ready.
            self._publish_bridge_state(self.BRIDGE_STATE_OFFLINE)

            # Refresh discovery on every successful MQTT connection so retained
            # configs stay aligned with the current bridge state and mapping.
            self._mqtt_discovery_bridge()

            # Get all device UIDs in DB
            known_uids = self._devmgr.db_list_from_fields('uid')

            # This will discover new added sensors in HA while updating existing sensors
            # configuration when sensor mapping has changed
            for cur_sensor in self.sensors:
                if str(cur_sensor.get('ignore')) not in ("True", "true", "1"):
                    if not cur_sensor.get('model'):
                        # Create sensor UID
                        eep = format((cur_sensor['rorg']<<16)+(cur_sensor['func']<<8)+cur_sensor['type'], '06X')
                        try:
                            sender = format(cur_sensor.get('sender'),'08X')
                        except:
                            sender = 'NONE'
                        dev_uid = eep+"_"+format(cur_sensor['address'],'08X')+"_"+sender
                        # Get sensor from DB if it exists
                        sensor_db = self._devmgr.db_get_device_by_field('name', cur_sensor['name'])
                        # Sensor discovery/update
                        cfgtopics = sensor_db.get('cfgtopics', None) if sensor_db else None
                        self._mqtt_discovery_eep(cur_sensor, cfgtopics)
                        # Remove device from the UID list
                        try:
                            known_uids.remove(dev_uid)
                        except ValueError:
                            pass
                    else:
                        # Create sensor UID
                        try:
                            sender = format(cur_sensor.get('sender'),'08X')
                        except:
                            sender = 'NONE'
                        dev_uid = cur_sensor['manufacturer']+"_"+cur_sensor['model']+"_"+format(cur_sensor['address'],'08X')+"_"+sender
                        # Retrieve device name from sensor name by removing "/RORG" at the end
                        name = cur_sensor['name'][:-3]
                        # Get sensor from DB if it exists
                        sensor_db = self._devmgr.db_get_device_by_field('name', name)
                        # Sensor discovery/update
                        cfgtopics = sensor_db.get('cfgtopics', None) if sensor_db else None
                        self._mqtt_discovery_model(cur_sensor, cfgtopics)
                        # Remove device from the UID list
                        try:
                            known_uids.remove(dev_uid)
                        except ValueError:
                            pass

            # Delete devices that are no more listed in config file
            logging.debug("List of remaining UIDS: %s", str(known_uids))
            for dev_uid in known_uids:
                sensor_db = self._devmgr.db_get_device_by_field('uid', dev_uid)
                # Remove all device's entities
                if sensor_db:
                    for cfgtopic in sensor_db.get('cfgtopics', []):
                        self.mqtt.publish(f"{self._mqtt_discovery_prefix}{cfgtopic}",
                                           "", retain=True)
                # Remove the device from the database
                self._devmgr.db_remove_device_by_field('uid', dev_uid)

            # Add LEARN button in HA
            self._mqtt_discovery_system('learn')

            # LEARN status
            self.mqtt.publish(self._system_status_topic['learn'],
                              'ON' if self.enocean.teach_in else 'OFF',
                              retain=True)

            # Announce the bridge as online once discovery and the EnOcean sender are ready.
            self._maybe_publish_bridge_online()
        else:
            logging.error("Error connecting to MQTT broker: %s",
                          self.CONNECTION_RETURN_CODE[return_code]
                          if return_code < len(self.CONNECTION_RETURN_CODE) else return_code)

    def _on_mqtt_message(self, _mqtt_client, _userdata, msg):
        '''the callback for when a PUBLISH message is received from the MQTT server.'''
        # Intercept system messages
        if '/__system' in msg.topic:
            self._handle_system_msg(msg)
        # Intercept MQTT delete requests
        elif msg.topic.startswith(self._mqtt_discovery_prefix) and msg.topic.endswith('/config'):
            if len(msg.payload) == 0:
                self._handle_system_msg(msg, delete=True)
        # Device messages
        else:
            super()._on_mqtt_message(_mqtt_client, _userdata, msg)


    #=============================================================================================
    # SYSTEM
    #=============================================================================================
    def _bridge_availability(self):
        """return the Home Assistant availability block for the bridge topic"""
        return [{
            'topic': self._bridge_state_topic(),
            'value_template': '{{ value_json.state }}',
        }]

    def _normalize_discovery_mapping(self, node):
        """convert legacy availability fields in the static mapping to the modern format"""
        if isinstance(node, dict):
            legacy_topic = node.pop('availability_topic', None)
            legacy_template = node.pop('availability_template', None)
            legacy_payload_available = node.pop('payload_available', None)
            legacy_payload_not_available = node.pop('payload_not_available', None)
            if legacy_topic not in (None, ""):
                availability = list(node.get('availability', []))
                legacy_entry = {'topic': legacy_topic}
                if legacy_template not in (None, ""):
                    legacy_entry['value_template'] = legacy_template
                if legacy_payload_available not in (None, ""):
                    legacy_entry['payload_available'] = legacy_payload_available
                if legacy_payload_not_available not in (None, ""):
                    legacy_entry['payload_not_available'] = legacy_payload_not_available
                availability.append(legacy_entry)
                node['availability'] = availability
            for value in node.values():
                self._normalize_discovery_mapping(value)
        elif isinstance(node, list):
            for item in node:
                self._normalize_discovery_mapping(item)

    def _apply_bridge_availability(self, cfg, topic_prefix=None):
        """append bridge availability to the current discovery config"""
        availability = list(cfg.pop('availability', []))
        if topic_prefix:
            for entry in availability:
                topic = entry.get('topic')
                if topic and not topic.startswith(f"{topic_prefix}/"):
                    entry['topic'] = f"{topic_prefix}/{topic}"
        availability.extend(self._bridge_availability())
        cfg['availability'] = availability
        cfg['availability_mode'] = 'all'

    def _bridge_device(self):
        """build the Home Assistant device block for the bridge"""
        client_id = self.conf.get('mqtt_client_id', self._mqtt_base_topic())
        gateway_info = getattr(self, "_gateway_info", {}) or self._collect_gateway_info()
        base_id = gateway_info.get('base_id')
        esp3_info = gateway_info.get('esp3', {})
        serial_number = base_id or self.enocean_sender or client_id
        return {
            'name': 'Enocean Bridge',
            'identifiers': f'enoceanmqtt_bridge_{client_id}',
            'manufacturer': 'EnOcean',
            'model': esp3_info.get('appDescription', 'Enocean Bridge'),
            'model_id': esp3_info.get('chipId', 'unknown'),
            'serial_number': serial_number,
            'sw_version': esp3_info.get('apiVersion'),
            'hw_version': esp3_info.get('appVersion'),
        }

    def _bridge_device_identifier(self):
        """return the Home Assistant identifier used for the bridge device"""
        return self._bridge_device()['identifiers']

    def _mqtt_discovery_bridge(self):
        """Publish MQTT discovery for bridge diagnostic entities"""
        device = self._bridge_device()
        bridge_uid = device['identifiers']
        bridge_availability = self._bridge_availability()

        connection_cfg = {
            'device': copy.deepcopy(device),
            'device_class': 'connectivity',
            'entity_category': 'diagnostic',
            'name': 'Connection state',
            'object_id': 'enoceanmqtt_bridge_connection_state',
            'origin': {
                'name': 'enocean2mqtt',
                'sw': self.build_version,
                'url': REPOSITORY_URL,
            },
            'payload_off': 'offline',
            'payload_on': 'online',
            'state_topic': self._bridge_state_topic(),
            'unique_id': f'{bridge_uid}_connection_state',
            'value_template': '{{ value_json.state }}',
        }

        version_cfg = {
            'availability': copy.deepcopy(bridge_availability),
            'availability_mode': 'all',
            'device': copy.deepcopy(device),
            'entity_category': 'diagnostic',
            'icon': 'mdi:information-outline',
            'name': 'Version Bridge',
            'object_id': 'enoceanmqtt_bridge_version',
            'origin': {
                'name': 'enocean2mqtt',
                'sw': self.build_version,
                'url': REPOSITORY_URL,
            },
            'state_topic': self._bridge_info_topic(),
            'unique_id': f'{bridge_uid}_version',
            'value_template': '{{ value_json.version }}',
        }

        self.mqtt.publish(f"{self._mqtt_discovery_prefix}binary_sensor/enoceanmqtt_bridge/connection_state/config",
                          json.dumps(connection_cfg),
                          retain=True)
        self.mqtt.publish(f"{self._mqtt_discovery_prefix}sensor/enoceanmqtt_bridge/version/config",
                          json.dumps(version_cfg),
                          retain=True)
        self.mqtt.publish(self._bridge_info_topic(), self._bridge_info_payload(), retain=True)

    def _mqtt_discovery_system(self, attr):
        '''Publish MQTT discovery system entities configuration to Home Assistant'''
        device_map = copy.deepcopy(self._ha_mapping['system'][attr])
        bridge_device = self._bridge_device()
        for entity in device_map:
            cfg = entity['config']
            # Wait for the transmitter ID
            attempt = 0
            while attempt < 10:
                attempt += 1
                try:
                    if self.enocean_sender is not None:
                        break
                except AttributeError:
                    pass
                time.sleep(1)
                logging.info("Waiting for device base ID")
            if self.enocean_sender is None:
                logging.fatal("Device base ID not received !")
                os._exit(1)

            # Create a unique ID for the entity based on the transmitter ID
            sender = enocean.utils.combine_hex(self.enocean_sender)
            sender_hex = format(sender, '08X')
            uid = 'enoceanmqtt_'+attr+'_'+sender_hex
            cfg['unique_id'] = uid

            # The entity name to be displayed in HA
            cfg['name'] = entity['name']

            # Associate system entities to the bridge device in HA
            cfg['device'] = copy.deepcopy(bridge_device)

            # The configuration topic defined for MQTT Discovery
            cfgtopic = f"{self._mqtt_discovery_prefix}{entity['component']}/{uid}/config"

            # TODO: remove this legacy purge in the next version once the
            # retained discovery migration for learn has been absorbed by HA.
            # Force a clean re-discovery for learn so Home Assistant migrates
            # the entity to the bridge device even if it previously existed
            # under an older retained payload.
            if attr == 'learn':
                self.mqtt.publish(cfgtopic, "", retain=True)

            # Append defined entity's topics to the device topic
            for key in cfg:
                if "topic" in key:
                    if cfg[key] not in ("", None):
                        cfg[key] = self.conf['mqtt_prefix']+'__system/'+cfg[key]
                    else:
                        cfg[key] = self.conf['mqtt_prefix']+'__system'

            self._apply_bridge_availability(cfg)

            # Publish the device configuration to MQTT for discovery
            self.mqtt.publish(cfgtopic, json.dumps(cfg), retain=True)
        # listen to HA learn requests
        self.mqtt.subscribe(self.conf['mqtt_prefix']+'__system/'+attr+'/req/#')
        self._system_status_topic[attr] = self.conf['mqtt_prefix']+'__system/'+attr

    def _mqtt_discovery_eep(self, sensor, prev_sensor_cfgtopics=None):
        '''Publish MQTT discovery EEP entities configuration to Home Assistant'''
        if prev_sensor_cfgtopics is None:
            prev_sensor_cfgtopics = []
        update = prev_sensor_cfgtopics != []
        rorg = sensor['rorg']
        func = sensor['func']
        type_ = sensor['type']
        eep_dash = f'{rorg:02X}'+'-'+f'{func:02X}'+'-'+f'{type_:02X}'
        is_virtual = str(sensor.get('virtual')) == '1'

        # If the device is supported, retrieve the device mapping
        device_map = None
        try:
            if is_virtual:
                device_map = copy.deepcopy(self._ha_mapping[rorg][func][type_]['virtual'])
            else:
                device_map = copy.deepcopy(self._ha_mapping[rorg][func][type_]['entities'])
        except KeyError:
            pass

        if device_map is None:
            logging.warning('Device not yet supported: %s%s',
                            eep_dash, ' (Virtual).' if is_virtual else \
                                      '. Only RSSI sensor will be available')
            device_map = []

        if not is_virtual:
            # Add RSSI sensor in HA
            device_map += copy.deepcopy(self._ha_mapping['common']['rssi'])
            # Add DATE sensor in HA
            device_map += copy.deepcopy(self._ha_mapping['common']['date'])

        ## Add Per device delete button in HA
        #device_map += copy.deepcopy(self._ha_mapping['system']['delete'])

        eep = format((rorg<<16)+(func<<8)+type_, '06X')
        address = format(sensor['address'],'08X')
        try:
            sender = format(sensor.get('sender'),'08X')
        except:
            sender = 'NONE'
        dev_uid = eep+"_"+address+"_"+sender
        dev_name = "e2m_"+sensor['name'].replace(self.conf['mqtt_prefix'], "").replace("/", "_")
        sensor_cfgtopics = []

        # Delete previous entities that are no more used in loaded mapping
        if update:
            for entity in device_map:
                # Create a unique ID for the entity
                uid = "enocean_"+dev_uid+"_"+entity['name']

                # The configuration topic defined for MQTT Discovery
                cfgtopic = f"{entity['component']}/{uid}/config"

                # Remove the entity from the list of entities to be deleted during update
                if cfgtopic in prev_sensor_cfgtopics:
                    prev_sensor_cfgtopics.remove(cfgtopic)

            # Delete to-be-deleted entities, if any
            for cfgtopic in prev_sensor_cfgtopics:
                self.mqtt.publish(f"{self._mqtt_discovery_prefix}{cfgtopic}", "", retain=True)

        # Loop over all the entities defined in the device
        for entity in device_map:
            # A name should be defined in mapping. If not, generate one.
            if str(entity.get('name')).lower() in ("none", ""):
                entity['name'] = str(int(time.time()))
            # Select the entity configuration
            cfg = entity['config']

            # Create a unique ID for the entity
            uid = "enocean_"+dev_uid+"_"+entity['name']
            cfg['unique_id'] = uid

            # The entity name to be displayed in HA
            cfg['name'] = entity['name']

            # Associate all entities to the device in HA
            cfg['device'] = {}
            cfg['device']['name'] = dev_name
            cfg['device']['identifiers'] = address if address != 'FFFFFFFF' else dev_uid
            cfg['device']['via_device'] = self._bridge_device_identifier()
            cfg['device']['model'] = eep_dash+" @"+address if address != 'FFFFFFFF' else \
                                     eep_dash+' (VIRTUAL) / '+sender+'->'+address
            cfg['device']['manufacturer'] = "EnOcean"
            cfg['device']['configuration_url'] = 'http://tools.enocean-alliance.org/EEPViewer/profiles/'+\
                                                 eep_dash.replace("-","/")+'/'+\
                                                 eep_dash+'.pdf'

            # The configuration topic defined for MQTT Discovery
            cfgtopic = f"{entity['component']}/{uid}/config"

            # List of entities configuration topics for later component deletion/update
            sensor_cfgtopics.append(cfgtopic)

            # Append defined entity's topics to the device topic
            for key in cfg:
                if "topic" in key:
                    if cfg[key] not in ("", None):
                        cfg[key] = sensor['name']+"/"+cfg[key]
                    else:
                        cfg[key] = sensor['name']

            self._apply_bridge_availability(cfg, sensor['name'])

            # Publish the device configuration to MQTT for discovery
            self.mqtt.publish(f"{self._mqtt_discovery_prefix}{cfgtopic}",
                              json.dumps(cfg), retain=True)

        if sensor_cfgtopics:
            # Subscribe to one config topic so that we can detect when MQTT delete is pressed
            self.mqtt.subscribe(f"{self._mqtt_discovery_prefix}{sensor_cfgtopics[0]}/#")
            # Subscribe to system message topic (per-device)
            self.mqtt.subscribe(sensor['name']+'/__system/#')

        # Add/update device to the database
        self._devmgr.db_upsert_device(sensor, dev_uid, 'cfgtopics', sensor_cfgtopics)
        logging.info("Device %s (UID: %s / EEP: %s) %s device database",
                     sensor['name'], dev_uid, eep_dash,
                     'updated on' if update else 'added to')

    def _mqtt_discovery_model(self, sensor, prev_sensor_cfgtopics=None):
        '''Publish MQTT discovery model entities configuration to Home Assistant'''
        if prev_sensor_cfgtopics is None:
            prev_sensor_cfgtopics = []
        update = prev_sensor_cfgtopics != []
        model = sensor['model']
        manufacturer = sensor['manufacturer']
        reference = manufacturer+"_"+model
        name = sensor['name'][:-3]
        is_virtual = str(sensor.get('virtual')) == '1'

        # If the device is supported, retrieve the device mapping
        device_map = None
        try:
            if is_virtual:
                device_map = copy.deepcopy(self._ha_mapping[manufacturer][model]['virtual'])
            else:
                device_map = copy.deepcopy(self._ha_mapping[manufacturer][model]['entities'])
        except KeyError:
            pass

        if device_map is None:
            logging.warning('Device not yet supported: %s%s',
                            reference,' (Virtual).' if is_virtual else \
                                      '. Only RSSI sensor will be available')
            device_map = []

        if not is_virtual:
            # Add RSSI sensor in HA
            device_map += copy.deepcopy(self._ha_mapping['common']['rssi'])
            # Add DATE sensor in HA
            device_map += copy.deepcopy(self._ha_mapping['common']['date'])

        address = format(sensor['address'],'08X')
        try:
            sender = format(sensor.get('sender'),'08X')
        except:
            sender = 'NONE'
        dev_uid = reference+"_"+address+"_"+sender
        dev_name = "e2m_"+name.replace(self.conf['mqtt_prefix'], "").replace("/", "_")
        sensor_cfgtopics = []

        # Delete previous entities that are no more used in loaded mapping
        if update:
            for entity in device_map:
                # Create a unique ID for the entity
                uid = "enocean_"+dev_uid+"_"+entity['name']

                # The configuration topic defined for MQTT Discovery
                cfgtopic = f"{entity['component']}/{uid}/config"

                # Remove the entity from the list of entities to be deleted during update
                if cfgtopic in prev_sensor_cfgtopics:
                    prev_sensor_cfgtopics.remove(cfgtopic)

            # Delete to-be-deleted entities, if any
            for cfgtopic in prev_sensor_cfgtopics:
                self.mqtt.publish(f"{self._mqtt_discovery_prefix}{cfgtopic}", "", retain=True)

        # Loop over all the entities defined in the device
        for entity in device_map:
            # A name should be defined in mapping. If not, generate one.
            if str(entity.get('name')).lower() in ("none", ""):
                entity['name'] = str(int(time.time()))
            # Select the entity configuration
            cfg = entity['config']

            # For models, get RSSI and DATE from the next MQTT level
            if str(entity.get('name')).lower() in ("rssi", "last_seen"):
                cfg['state_topic'] = "+"

            # Create a unique ID for the entity
            uid = "enocean_"+dev_uid+"_"+entity['name']
            cfg['unique_id'] = uid

            # The entity name to be displayed in HA
            cfg['name'] = entity['name']

            # Associate all entities to the device in HA
            cfg['device'] = {}
            cfg['device']['name'] = dev_name
            cfg['device']['identifiers'] = address if address != 'FFFFFFFF' else dev_uid
            cfg['device']['via_device'] = self._bridge_device_identifier()
            cfg['device']['model'] = model.upper()+" @"+address if address != 'FFFFFFFF' else \
                                     model.upper()+' (VIRTUAL) / '+sender+'->'+address
            cfg['device']['manufacturer'] = manufacturer
            cfg['device']['configuration_url'] = 'https://www.google.com/search?q='+\
                                                 manufacturer+'+'+model+'+pdf'

            # The configuration topic defined for MQTT Discovery
            cfgtopic = f"{entity['component']}/{uid}/config"

            # List of entities configuration topics for later component deletion/update
            sensor_cfgtopics.append(cfgtopic)

            # Append defined entity's topics to the device topic
            for key in cfg:
                if "topic" in key:
                    if cfg[key] not in ("", None):
                        cfg[key] = name+"/"+cfg[key]
                    else:
                        cfg[key] = name

            self._apply_bridge_availability(cfg, sensor['name'])

            # Publish the device configuration to MQTT for discovery
            self.mqtt.publish(f"{self._mqtt_discovery_prefix}{cfgtopic}",
                              json.dumps(cfg), retain=True)

        if sensor_cfgtopics:
            # Subscribe to one config topic so that we can detect when MQTT delete is pressed
            self.mqtt.subscribe(f"{self._mqtt_discovery_prefix}{sensor_cfgtopics[0]}/#")
            # Subscribe to system message topic (per-device)
            self.mqtt.subscribe(name+'/__system/#')

        # Add/update device to the database
        self._devmgr.db_upsert_device(sensor, dev_uid, 'cfgtopics', sensor_cfgtopics)
        logging.info("Device %s (UID: %s / REF: %s) %s device database",
                     name, dev_uid, reference,
                     'updated on' if update else 'added to')

    def _handle_system_msg(self, msg, delete=False):
        '''Handle system-related MQTT messages'''
        if delete:
            # This indicates a delete request and it should be only done
            # on MQTT discovery configuration topics
            # Retrieve targeted configuration topic
            cfgtopic = msg.topic.split(self._mqtt_discovery_prefix)[1]
            # Remove the sensor from the database
            self._devmgr.db_remove_device_by_field('cfgtopics', cfgtopic)
        else:
            # Retrieve system request target
            [target_name, prop] = [msg.topic.split('/__system')[i] for i in (0,-1)]
            # Global system request
            if target_name == self.conf['mqtt_prefix'][:-1]:
                # Handle learn request
                if prop == "/learn/req":
                    self.enocean.teach_in = msg.payload.decode('UTF-8') == 'ON'
                    self.mqtt.publish(self._system_status_topic['learn'],
                                      'ON' if self.enocean.teach_in else 'OFF',
                                      retain=True)

    #=============================================================================================
    # ENOCEAN TO MQTT
    #=============================================================================================
    def _publish_mqtt(self, sensor, mqtt_json):
        '''Publish decoded packet content to MQTT'''
        ## Present the device to HA if it is the first time it is seen
        #if not self._devmgr.db_search_device_by_address(sensor['address']):
            #self._mqtt_discovery_sensor(sensor)

        # Publish the packet
        super()._publish_mqtt(sensor, mqtt_json)
