# Author: Marc Alexandre K. <marcalexandrek-developer@yahoo.fr>
"""this class is a Home Assistant overlay for enoceanmqtt"""

import logging
import copy
import os
import time
import json
import yaml

import enocean.utils
from enoceanmqtt.communicator import Communicator
from enoceanmqtt.overlays.homeassistant.device_manager import DeviceManager

REPOSITORY_URL = 'https://github.com/ChristopheHD/HA_enoceanmqtt'

class HACommunicator(Communicator):
    '''Home Assistant-oriented Communicator subclass for enoceanmqtt'''
    _mqtt_discovery_prefix = None
    _devmgr = None
    _system_status_topic = {}

    def __init__(self, config, sensors):
        # Read mapping file
        mapping_file = config.get('mapping_file')
        if not mapping_file:
            mapping_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mapping.yaml')
        with open(mapping_file, 'r', encoding="utf-8") as file:
            self._ha_mapping = yaml.safe_load(file)
        logging.info("Mapping file correctly read: %s", mapping_file)

        # Get Model-based sensors
        models = []
        models = [item for item in sensors if item.get('model')]

        # Get EEP-based sensors
        sensors = [cur_sensor for cur_sensor in sensors if cur_sensor not in models]

        # Overwrite some of the user-defined device configuration
        # to comply with the overlay requirements
        for cur_sensor in sensors:
            if str(cur_sensor.get('ignore')) not in ("True", "true", "1"):
                # Retrieve EEP-related device configuration
                rorg  = cur_sensor['rorg']
                func  = cur_sensor['func']
                type_ = cur_sensor['type']
                devcfg = {}
                try:
                    devcfg = copy.deepcopy(self._ha_mapping[rorg][func][type_]['device_config'])
                except KeyError:
                    pass

                # Set EEP-related device configuration
                # Only set fields if they have non-empty values to avoid passing empty strings
                # to the EnOcean library which expects None for unset parameters
                if devcfg.get('command'):
                    cur_sensor['command'] = devcfg.get('command')
                if devcfg.get('channel'):
                    cur_sensor['channel'] = devcfg.get('channel')
                if devcfg.get('log_learn'):
                    cur_sensor['log_learn'] = devcfg.get('log_learn')
                if devcfg.get('direction'):
                    cur_sensor['direction'] = devcfg.get('direction')
                if devcfg.get('answer'):
                    cur_sensor['answer'] = devcfg.get('answer')
                cur_sensor['persistent']   = devcfg.get('persistent', "1")

                # Better to work with JSON in HA so force JSON usage
                # Also force publish_rssi and publish_date
                cur_sensor['publish_json'] = "1"
                cur_sensor['publish_rssi'] = "1"
                cur_sensor['publish_date'] = "1"

        # Create sensors from models
        for cur_model in models:
            if str(cur_model.get('ignore')) not in ("True", "true", "1"):
                manufacturer,model = cur_model.get('model').lower().split('/')
                logging.debug("Found new model-based device: %s %s", manufacturer, model)
                devcfg = {}
                try:
                    devcfg = copy.deepcopy(self._ha_mapping[manufacturer][model]['device_config'])
                except KeyError:
                    pass
                for new_sens in devcfg:
                    new_sens['name'] = cur_model.get('name')+'/'+new_sens.get('rorg')[2:4].lower()
                    new_sens['address'] = cur_model.get('address')
                    if cur_model.get('default_data'):
                        new_sens['default_data'] = cur_model.get('default_data')
                    if cur_model.get('sender'):
                        new_sens['sender'] = cur_model.get('sender')
                    if cur_model.get('ignore'):
                        new_sens['ignore'] = cur_model.get('ignore')
                    new_sens['manufacturer'] = manufacturer
                    new_sens['model'] = model
                    new_sens['rorg'] = int(new_sens['rorg'],0)
                    new_sens['func'] = int(new_sens['func'],0)
                    new_sens['type'] = int(new_sens['type'],0)
                    # Better to work with JSON in HA so force JSON usage
                    # Also force publish_rssi and publish_date
                    new_sens['publish_json'] = "1"
                    new_sens['publish_rssi'] = "1"
                    new_sens['publish_date'] = "1"
                    new_sens.setdefault('persistent', "1")
                    sensors.append(new_sens)
                    logging.debug("Created sensor: %s", new_sens)

        # Create device manager
        self._devmgr = DeviceManager(config)

        # Retrieve MQTT discovery prefix from configuration and make sure there is a trailing '/'
        self._mqtt_discovery_prefix = config.get('mqtt_discovery_prefix', 'homeassistant/')
        if self._mqtt_discovery_prefix[-1] != '/':
            self._mqtt_discovery_prefix += '/'

        # Init
        super().__init__(config, sensors)

        # Disable Teach-in on startup
        self.enocean.teach_in = False
        logging.info("Auto Teach-in is %s", "enabled" if self.enocean.teach_in else "disabled")


    #=============================================================================================
    # MQTT CLIENT
    #=============================================================================================
    def _on_connect(self, mqtt_client, _userdata, _flags, return_code):
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

            self._mqtt_discovery_bridge()

            # Refresh discovery on every successful MQTT connection so retained
            # configs stay aligned with the current bridge state and mapping.
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

    def _apply_bridge_availability(self, cfg):
        """merge bridge availability with any existing legacy availability settings"""
        availability = []
        legacy_topic = cfg.pop('availability_topic', None)
        legacy_template = cfg.pop('availability_template', None)
        legacy_payload_available = cfg.pop('payload_available', None)
        legacy_payload_not_available = cfg.pop('payload_not_available', None)
        if legacy_topic not in (None, ""):
            legacy_entry = {'topic': legacy_topic}
            if legacy_template not in (None, ""):
                legacy_entry['value_template'] = legacy_template
            if legacy_payload_available not in (None, ""):
                legacy_entry['payload_available'] = legacy_payload_available
            if legacy_payload_not_available not in (None, ""):
                legacy_entry['payload_not_available'] = legacy_payload_not_available
            availability.append(legacy_entry)
        if cfg.get('availability'):
            availability.extend(cfg.pop('availability'))
        availability.extend(self._bridge_availability())
        cfg['availability'] = availability
        cfg['availability_mode'] = 'all'

    def _bridge_device(self):
        """build the Home Assistant device block for the bridge"""
        client_id = self.conf.get('mqtt_client_id', self._mqtt_base_topic())
        return {
            'name': 'Enocean Bridge',
            'identifiers': f'enoceanmqtt_bridge_{client_id}',
            'manufacturer': REPOSITORY_URL,
            'model': 'Enocean Bridge',
            'sw_version': self.build_version,
            'hw_version': self.conf.get('enocean_port', 'unknown'),
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
            'name': 'Version',
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

            self._apply_bridge_availability(cfg)

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

            self._apply_bridge_availability(cfg)

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
                    self.mqtt.publish(self._bridge_info_topic(),
                                      self._bridge_info_payload(),
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
