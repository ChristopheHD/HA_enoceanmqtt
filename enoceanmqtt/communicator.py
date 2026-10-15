# Copyright (c) 2020 embyt GmbH. See LICENSE for further details.
# Author: Roman Morawek <roman.morawek@embyt.com>
"""this class handles the enocean and mqtt interfaces"""
import logging
import queue
import numbers
import json
import os
import time

from enocean.communicators.serialcommunicator import SerialCommunicator
from enoceanmqtt.tcpclientcommunicator import TCPClientCommunicator
from enocean.protocol.packet import RadioPacket, Packet
from enocean.protocol.constants import PACKET, RETURN_CODE, RORG
import enocean.utils
import paho.mqtt.client as mqtt


class Communicator:
    """the main working class providing the MQTT interface to the enocean packet classes"""
    mqtt = None
    enocean = None
    BRIDGE_STATE_ONLINE = "online"
    BRIDGE_STATE_OFFLINE = "offline"

    CONNECTION_RETURN_CODE = [
        "connection successful",
        "incorrect protocol version",
        "invalid client identifier",
        "server unavailable",
        "bad username or password",
        "not authorised",
    ]

    def __init__(self, config, sensors):
        self.conf = config
        self.sensors = sensors
        self._index_sensors()
        self._mqtt_connected = False
        self._bridge_state = self.BRIDGE_STATE_OFFLINE
        self._shutdown_requested = False
        self._gateway_info_logged = False
        self._gateway_info = {}
        self.build_version = self._load_build_version()

        # check for mandatory configuration
        if 'mqtt_host' not in self.conf or 'enocean_port' not in self.conf:
            raise Exception("Mandatory configuration not found: mqtt_host/enocean_port")
        mqtt_port = int(self.conf['mqtt_port']) if 'mqtt_port' in self.conf else 1883
        mqtt_keepalive = int(self.conf['mqtt_keepalive']) if 'mqtt_keepalive' in self.conf else 60

        # setup mqtt connection
        client_id = self.conf['mqtt_client_id'] if 'mqtt_client_id' in self.conf else ''
        self.mqtt = mqtt.Client(client_id=client_id)
        self.mqtt.will_set(self._bridge_state_topic(),
                           self._bridge_state_payload(self.BRIDGE_STATE_OFFLINE),
                           retain=True)
        self.mqtt.on_connect = self._on_connect
        self.mqtt.on_disconnect = self._on_disconnect
        self.mqtt.on_message = self._on_mqtt_message
        self.mqtt.on_publish = self._on_mqtt_publish
        if 'mqtt_user' in self.conf:
            logging.info("Authenticating: %s", self.conf['mqtt_user'])
            self.mqtt.username_pw_set(self.conf['mqtt_user'], self.conf['mqtt_pwd'])
        if str(self.conf.get('mqtt_ssl')) in ("True", "true", "1"):
            logging.info("Enabling SSL")
            ca_certs = self.conf['mqtt_ssl_ca_certs'] if 'mqtt_ssl_ca_certs' in self.conf else None
            certfile = self.conf['mqtt_ssl_certfile'] if 'mqtt_ssl_certfile' in self.conf else None
            keyfile = self.conf['mqtt_ssl_keyfile'] if 'mqtt_ssl_keyfile' in self.conf else None
            self.mqtt.tls_set(ca_certs=ca_certs, certfile=certfile, keyfile=keyfile)
            if str(self.conf.get('mqtt_ssl_insecure')) in ("True", "true", "1"):
                logging.warning("Disabling SSL certificate verification")
                self.mqtt.tls_insecure_set(True)
        if str(self.conf.get('mqtt_debug')) in ("True", "true", "1"):
            self.mqtt.enable_logger()
        logging.debug("Connecting to host %s, port %s, keepalive %s",
                      self.conf['mqtt_host'], mqtt_port, mqtt_keepalive)
        self.mqtt.connect_async(self.conf['mqtt_host'], port=mqtt_port, keepalive=mqtt_keepalive)
        self.mqtt.loop_start()

        # setup enocean communication
        eport  = self.conf['enocean_port']
        seport = eport.split(':')
        if seport[0] == "tcp":
            logging.info("connecting TCPClient to %s port %d", seport[1],int(seport[2]))
            self.enocean = TCPClientCommunicator(seport[1],int(seport[2]))
        else:
            logging.info("connecting Serial to %s", eport)
            self.enocean = SerialCommunicator(eport)

        self.enocean.start()
        # sender will be automatically determined
        self.enocean_sender = None

    def __del__(self):
        if self.enocean is not None and self.enocean.is_alive():
            self.enocean.stop()

    def _index_sensors(self):
        """index sensors by address and name for faster lookup"""
        self._sensors_by_address = {}
        self._sensors_by_name = {}
        self._sensor_to_index = {id(s): i for i, s in enumerate(self.sensors)}
        for sensor in self.sensors:
            addr = sensor.get('address')
            if addr is not None:
                if addr not in self._sensors_by_address:
                    self._sensors_by_address[addr] = []
                self._sensors_by_address[addr].append(sensor)

            name = sensor.get('name')
            if name:
                if name not in self._sensors_by_name:
                    self._sensors_by_name[name] = []
                self._sensors_by_name[name].append(sensor)

    def _get_sensors_for_topic(self, topic):
        """return list of sensors that match the given topic"""
        matched = []
        parts = topic.split('/')
        current = ""
        for i, part in enumerate(parts):
            if i > 0:
                current += "/"
            current += part
            if current in self._sensors_by_name:
                # Check if it matches name + "/" as in original code
                if topic.startswith(current + "/"):
                    matched.extend(self._sensors_by_name[current])
        # Sort matched sensors by their original order to maintain behavior
        if len(matched) > 1:
            matched.sort(key=lambda s: self._sensor_to_index.get(id(s), 0))
        return matched

    def _mqtt_base_topic(self):
        """return the configured MQTT base topic with a trailing slash stripped"""
        return self.conf.get('mqtt_prefix', 'enocean/').rstrip('/')

    def _build_version_path(self):
        """return the VERSION file path shipped with the package"""
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'VERSION')

    def _load_build_version(self):
        """load the build version from VERSION, defaulting to null"""
        try:
            with open(self._build_version_path(), 'r', encoding='utf-8') as version_file:
                version = version_file.read().strip()
        except OSError:
            version = ''
        return version or 'null'

    def _bridge_state_topic(self):
        """return the retained topic used to expose bridge availability"""
        return f"{self._mqtt_base_topic()}/__system/state"

    def _bridge_info_topic(self):
        """return the retained topic used to expose bridge metadata"""
        return f"{self._mqtt_base_topic()}/__system/info"

    def _bridge_state_payload(self, state):
        """build the JSON payload used for bridge availability"""
        return json.dumps({"state": state})

    def _bridge_info_payload(self):
        """build the JSON payload used for bridge metadata"""
        return json.dumps({
            "version": self.build_version,
        })

    def _format_gateway_value(self, value):
        """normalize gateway values for readable logging"""
        if value is None or value == "":
            return None
        if isinstance(value, (bytes, bytearray)):
            return value.hex()
        if isinstance(value, (list, tuple)) and value and all(isinstance(item, int) for item in value):
            return enocean.utils.to_hex_string(value)
        return value

    def _parse_esp3_version_payload(self, payload):
        """parse the 32-byte version payload returned by the gateway"""
        if len(payload) < 32:
            return None

        app_ver = ".".join(str(payload[i]) for i in range(0, 4))
        api_ver = ".".join(str(payload[i]) for i in range(4, 8))
        chip_id = bytes(payload[8:12]).hex()
        chip_ver = ".".join(str(payload[i]) for i in range(12, 16))
        app_desc = ""
        for i in range(16, 32):
            if payload[i] == 0x00:
                break
            app_desc += chr(payload[i])
        return {
            "appVersion": app_ver,
            "apiVersion": api_ver,
            "chipId": chip_id,
            "chipVersion": chip_ver,
            "appDescription": app_desc,
        }

    def _parse_esp3_version_response(self, buf):
        """parse an ESP3 version response similar to the Node.js implementation"""
        if not buf:
            return {}
        if len(buf) == 40 and buf[0] == 0x55:
            if int.from_bytes(buf[1:3], "big") != 0x21:
                return {}
            if buf[4] != 0x02:
                return {}
            if buf[6] != 0x00:
                return {}
            return self._parse_esp3_version_payload(buf[7:39]) or {}
        if len(buf) == 33 and buf[0] == 0x00:
            return self._parse_esp3_version_payload(buf[1:33]) or {}
        if len(buf) >= 33 and buf[0] == 0x00:
            parsed = self._parse_esp3_version_payload(buf[1:33])
            if parsed:
                return parsed
        if len(buf) >= 32:
            parsed = self._parse_esp3_version_payload(buf[:32])
            if parsed:
                return parsed
        return {}

    def _collect_esp3_info(self, timeout=1.0):
        """try to fetch gateway version details through the communicator queue"""
        if self.enocean is None or not hasattr(self.enocean, "send") or not hasattr(self.enocean, "receive"):
            logging.debug("Skipping ESP3 gateway info: communicator does not expose send/receive")
            return {}
        try:
            command_type = getattr(Packet, "COMMON_COMMAND", getattr(PACKET, "COMMON_COMMAND", None))
            if command_type is None:
                logging.debug("Skipping ESP3 gateway info: COMMON_COMMAND is unavailable")
                return {}
            logging.debug("Fetching ESP3 gateway info through communicator")
            self.enocean.send(Packet(command_type, data=[0x03]))
        except Exception as error:
            logging.debug("Unable to send ESP3 version request: %s", error)
            return {}
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(0.0, deadline - time.time())
            try:
                packet = self.enocean.receive.get(block=True, timeout=remaining)
            except queue.Empty:
                continue
            if getattr(packet, "packet_type", None) != PACKET.RESPONSE:
                logging.debug("Ignoring non-response packet while fetching ESP3 gateway info: %s", packet)
                continue
            payload = getattr(packet, "data", None)
            if payload is None:
                logging.debug("Ignoring ESP3 gateway info response without payload: %s", packet)
                continue
            try:
                payload_length = len(payload)
            except TypeError:
                logging.debug("Ignoring ESP3 gateway info response with non-sized payload: %s", packet)
                continue
            if payload_length not in (33, 40):
                logging.debug("Ignoring non-version ESP3 response while fetching gateway info: %s", packet)
                continue
            parsed = self._parse_esp3_version_response(bytes(payload)) or {}
            if parsed:
                parsed = {
                    key: parsed[key]
                    for key in ("appVersion", "apiVersion", "chipId", "appDescription")
                    if parsed.get(key) not in (None, "")
                }
                logging.debug("Received ESP3 gateway info: %s", parsed)
                return parsed
            logging.debug("ESP3 gateway info response could not be parsed: %s", payload)
        logging.debug("No ESP3 gateway info response received within %.2fs", timeout)
        return {}

    def _collect_gateway_info(self):
        """collect best-effort gateway information from the driver object"""
        if self.enocean is None:
            return {}
        info = {
            "driver": type(self.enocean).__name__,
        }
        # base_id is the only stable attribute exposed by the driver itself.
        if hasattr(self.enocean, "base_id"):
            formatted_value = self._format_gateway_value(getattr(self.enocean, "base_id"))
            if formatted_value is not None:
                info["base_id"] = formatted_value

        # If the driver wraps a lower-level serial object, include a few of its
        # public fields as well. This stays best-effort and avoids hardcoding a
        # specific implementation detail.
        for nested_name in ("serial", "_serial", "serial_port", "_serial_port", "port_handle", "_port"):
            nested = getattr(self.enocean, nested_name, None)
            if nested is None:
                continue
            nested_info = {}
            for attr_name in ("port", "baudrate", "name", "is_open", "serial_number", "manufacturer", "locationId", "vendorId", "productId"):
                if hasattr(nested, attr_name):
                    formatted_value = self._format_gateway_value(getattr(nested, attr_name))
                    if formatted_value is not None:
                        nested_info[attr_name] = formatted_value
            if nested_info:
                info[nested_name] = nested_info
            else:
                info[nested_name] = repr(nested)

        esp3_info = self._collect_esp3_info()
        if esp3_info:
            info["esp3"] = esp3_info
        return info

    def _log_gateway_info(self):
        """log gateway information once the driver has enough data"""
        if self._gateway_info_logged:
            return
        info = self._collect_gateway_info()
        if not info:
            return
        self._gateway_info = info
        logging.info("EnOcean gateway info: %s", info)
        self._gateway_info_logged = True

    def _bridge_is_ready(self):
        """return True when the bridge is ready to announce itself online"""
        return self._mqtt_connected and self.enocean is not None and \
            self.enocean.is_alive() and self.enocean_sender is not None

    def _publish_bridge_state(self, state):
        """publish the retained bridge availability state"""
        if state == self.BRIDGE_STATE_ONLINE:
            if self._bridge_state == self.BRIDGE_STATE_ONLINE or not self._bridge_is_ready():
                return False
        elif state == self.BRIDGE_STATE_OFFLINE:
            if self.mqtt is None or not self._mqtt_connected:
                return False

        logging.debug("Publishing bridge state %s to %s", state, self._bridge_state_topic())
        publish_info = self.mqtt.publish(self._bridge_state_topic(),
                                         self._bridge_state_payload(state),
                                         retain=True)
        self._bridge_state = state
        return publish_info

    def _maybe_publish_bridge_online(self):
        """publish bridge online once both MQTT and EnOcean are ready"""
        return self._publish_bridge_state(self.BRIDGE_STATE_ONLINE)

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
                # logging.debug("MQTT subscribing: %s", cur_sensor['name']+'/req/#')
                mqtt_client.subscribe(cur_sensor['name']+'/req/#')
            self._maybe_publish_bridge_online()
        else:
            logging.error("Error connecting to MQTT broker: %s",
                          self.CONNECTION_RETURN_CODE[return_code]
                          if return_code < len(self.CONNECTION_RETURN_CODE) else return_code)

    def _on_disconnect(self, _mqtt_client, _userdata, return_code):
        '''callback for when the client disconnects from the MQTT server.'''
        self._mqtt_connected = False
        self._bridge_state = self.BRIDGE_STATE_OFFLINE
        if return_code == 0:
            logging.warning("Successfully disconnected from MQTT broker")
        else:
            logging.warning("Unexpectedly disconnected from MQTT broker: %s",
                            self.CONNECTION_RETURN_CODE[return_code]
                            if return_code < len(self.CONNECTION_RETURN_CODE) else return_code)

    def _on_mqtt_message(self, _mqtt_client, _userdata, msg):
        '''the callback for when a PUBLISH message is received from the MQTT server.'''
        # search for sensor
        found_topic = False
        logging.debug("Got MQTT message: %s", msg.topic)

        # Get how to handle MQTT message
        try:
            mqtt_payload = json.loads(msg.payload)
        except:
            mqtt_payload = msg.payload

        if isinstance(mqtt_payload, dict):
            found_topic = self._mqtt_message_json(msg.topic, mqtt_payload)
        else:
            found_topic = self._mqtt_message_normal(msg)

        if not found_topic:
            logging.warning("Unexpected or erroneous MQTT message: %s: %s", msg.topic, msg.payload)

    def _on_mqtt_publish(self, _mqtt_client, _userdata, _mid):
        '''the callback for when a PUBLISH message is successfully sent to the MQTT server.'''
        #logging.debug("Published MQTT message "+str(mid))


    def shutdown(self):
        """publish bridge offline and stop both interfaces cleanly"""
        if self._shutdown_requested:
            return
        self._shutdown_requested = True

        publish_info = self._publish_bridge_state(self.BRIDGE_STATE_OFFLINE)
        if publish_info and hasattr(publish_info, 'wait_for_publish'):
            publish_info.wait_for_publish()

        if self.mqtt is not None:
            try:
                self.mqtt.disconnect()
            finally:
                self.mqtt.loop_stop()

        if self.enocean is not None and self.enocean.is_alive():
            self.enocean.stop()


    #=============================================================================================
    # MQTT TO ENOCEAN
    #=============================================================================================
    def _mqtt_message_normal(self, msg):
        '''Handle received PUBLISH message from the MQTT server as a normal payload.'''
        found_topic = False
        for cur_sensor in self._get_sensors_for_topic(msg.topic):
            # get message topic
            prop = msg.topic[len(cur_sensor['name']+"/req/"):]
            # do we face a send request?
            if prop == "send":
                found_topic = True

                # Clear sent data, if requested by the send message
                # MQTT payload is binary data, thus we need to decode it
                clear = False
                raw_data = False
                for action in msg.payload.decode('UTF-8').lower().split('+'):
                    if action == "clear":
                        clear = True
                    elif action == "learn":
                        cur_sensor['learn'] = True
                    elif action == "raw_data":
                        raw_data = True

                # raw_data has not been validated by the send payload
                if 'raw_data' in cur_sensor and not raw_data:
                    del cur_sensor['raw_data']

                self._send_message(cur_sensor, clear)

            elif prop == "raw_data":
                found_topic = True
                cur_sensor['raw_data'] = msg.payload.decode('UTF-8')
            else:
                found_topic = True
                # parse message content
                value = None
                try:
                    value = int(msg.payload)
                except ValueError:
                    logging.warning("Cannot parse int value for %s: %s", msg.topic, msg.payload)
                    # Prevent storing undefined value, as it will trigger exception in EnOcean library
                    return False
                # store received data
                logging.debug("%s: %s=%s", cur_sensor['name'], prop, value)
                if 'data' not in cur_sensor:
                    cur_sensor['data'] = {}
                cur_sensor['data'][prop] = value

        return found_topic

    def _mqtt_message_json(self, mqtt_topic, mqtt_json_payload):
        '''Handle received PUBLISH message from the MQTT server as a JSON payload.'''
        found_topic = False
        for cur_sensor in self._get_sensors_for_topic(mqtt_topic):
            # get message topic
            prop = mqtt_topic[len(cur_sensor['name']+"/"):]
            # JSON payload shall be sent to '/req' topic
            if prop == "req":
                found_topic = True
                send = False
                clear = False

                # do we face a send request?
                if "send" in mqtt_json_payload.keys():
                    send = True
                    logging.debug("Send Payload: %s", mqtt_json_payload['send'])
                    # Decode packet handling actions
                    for action in mqtt_json_payload['send'].lower().split('+'):
                        # Check whether the data buffer shall be cleared
                        if action == "clear":
                            clear = True
                        elif action == "learn":
                            cur_sensor['learn'] = True
                        elif action == "raw_data":
                            if 'raw_data' in mqtt_json_payload:
                                cur_sensor['raw_data'] = mqtt_json_payload['raw_data']
                                del mqtt_json_payload['raw_data']

                    # Remove 'send' field as it is not part of EnOcean data
                    del mqtt_json_payload['send']

                # Parse message content
                for topic in list(mqtt_json_payload):
                    try:
                        mqtt_json_payload[topic] = int(mqtt_json_payload[topic])
                    except ValueError:
                        logging.warning("Cannot parse int value for %s: %s", topic, mqtt_json_payload[topic])
                        # Prevent storing undefined value, as it will trigger exception in EnOcean library
                        del mqtt_json_payload[topic]

                # Append received data to cur_sensor['data'].
                # This will keep the possibility to pass single topic/payload as done with
                # normal payload, even if JSON provides the ability to pass all topic/payload
                # in a single MQTT message.
                logging.debug("%s: %s=%s", cur_sensor['name'], prop, mqtt_json_payload)
                if 'data' not in cur_sensor:
                    cur_sensor['data'] = {}
                cur_sensor['data'].update(mqtt_json_payload)

                # Finally, send the message
                if send == True:
                    self._send_message(cur_sensor, clear)

            # The targeted sensor has been found and the MQTT message has been handled
            break

        return found_topic

    def _send_message(self, sensor, clear):
        '''Send received MQTT message (Property-based) to EnOcean.'''
        logging.debug("Trigger message to: %s", sensor['name'])
        destination = [(sensor['address'] >> i*8) &
                       0xff for i in reversed(range(4))]

        # Retrieve command from MQTT message and pass it to _send_packet()
        command = None
        command_shortcut = sensor.get('command')

        if command_shortcut:
            # Check MQTT message sets the command field
            if 'data' not in sensor or sensor['data'].get(command_shortcut) is None:
                logging.warning(
                    'Command field %s must be set in MQTT message!', command_shortcut)
                return
            # Retrieve command id from MQTT message
            command = sensor['data'][command_shortcut]
            logging.debug('Retrieved command id from MQTT message: %s', hex(command))

        # Send the MQTT message
        self._send_packet(sensor, destination, command)

        # Clear sent data, if requested by the sent message
        if clear == True:
            logging.debug('Clearing data buffer.')
            del sensor['data']

        # Delete learn
        if 'learn' in sensor:
            del sensor['learn']

        # Delete raw_data if any
        if 'raw_data' in sensor:
            del sensor['raw_data']

    #=============================================================================================
    # ENOCEAN TO MQTT
    #=============================================================================================
    def _get_command_id(self, packet, sensor):
        '''interpret packet to retrieve command id from VLD packets'''
        # Retrieve the first defined EEP profile matching sensor RORG-FUNC-TYPE
        # As we take the first defined profile, this suppose that command is
        # ALWAYS at the same offset and ALWAYS has the same size.
        profile = packet.eep.find_profile(
            packet._bit_data, sensor['rorg'], sensor['func'], sensor['type'])

        if profile:
            # Loop over profile contents
            for source in list(profile):
               if not source.tag:
                   continue
               # Check the current shortcut matches the command shortcut
               if source.get('shortcut') == sensor.get('command'):
                   return packet.eep._get_raw(source, packet._bit_data)

        # If profile or command shortcut not found,
        # return None for default handling of the packet
        return None

    def _publish_mqtt(self, sensor, mqtt_json):
        '''Publish decoded packet content to MQTT'''
        # Publish using JSON format ?
        mqtt_publish_json = str(sensor.get('publish_json')) in ("True", "true", "1")

        # Publish RSSI ?
        mqtt_publish_rssi = str(sensor.get('publish_rssi')) in ("True", "true", "1")

        # Retain the to-be-published message ?
        retain = str(sensor.get('persistent')) in ("True", "true", "1")

        # Is grouping enabled on this sensor
        channel_id = sensor.get('channel')
        channel_id = channel_id.split('/') if channel_id not in (None, '') else []

        # Handling Auxiliary data RSSI
        aux_data = {}
        if mqtt_publish_rssi:
            if mqtt_publish_json:
                # Keep _RSSI_ out of groups
                if channel_id:
                    aux_data.update({"_RSSI_": mqtt_json['_RSSI_']})
            else:
                self.mqtt.publish(sensor['name']+"/_RSSI_", mqtt_json['_RSSI_'], retain=retain)
        # Delete RSSI if already handled
        if channel_id or not mqtt_publish_json or not mqtt_publish_rssi:
            del mqtt_json['_RSSI_']

        # Handling Auxiliary data _DATE_
        if str(sensor.get('publish_date')) in ("True", "true", "1"):
            # Publish _DATE_ both at device and group levels
            if channel_id:
                if mqtt_publish_json:
                    aux_data.update({"_DATE_": mqtt_json['_DATE_']})
                else:
                    self.mqtt.publish(sensor['name']+"/_DATE_", mqtt_json['_DATE_'], retain=retain)
        else:
            del mqtt_json['_DATE_']

        # Publish auxiliary data
        if aux_data:
            self.mqtt.publish(sensor['name'], json.dumps(aux_data), retain=retain)

        # Determine MQTT topic
        topic = sensor['name']
        for cur_id in channel_id:
            if mqtt_json.get(cur_id) not in (None, ''):
                topic += f"/{cur_id}{mqtt_json[cur_id]}"
                del mqtt_json[cur_id]

        # Publish packet data to MQTT
        value = json.dumps(mqtt_json)
        if mqtt_json not in (None, ""):
            logging.debug("%s: Sent MQTT: %s retain=%s", topic, value, retain)
        else:
            retain = True
            value = None
            logging.debug("Clearing retained packets retain=%s", retain)

        if mqtt_publish_json:
            self.mqtt.publish(topic, value, retain=retain)
        else:
            for prop_name, value in mqtt_json.items():
                self.mqtt.publish(f"{topic}/{prop_name}", value, retain=retain)

    def _read_packet(self, packet, sensor):
        '''interpret packet, read properties and publish to MQTT'''
        mqtt_json = {}
        
        # Shall the packet be published to MQTT ?
        if not packet.learn or str(sensor.get('log_learn')) in ("True", "true", "1"):
            # Store RSSI
            # Use underscore so that it is unique and doesn't
            # match a potential future EnOcean EEP field.
            mqtt_json['_RSSI_'] = packet.dBm

            # Store receive date
            # Use underscore so that it is unique and doesn't
            # match a potential future EnOcean EEP field.
            mqtt_json['_DATE_'] = packet.received.isoformat()

            # Handling received data packet
            found_property = self._handle_data_packet( packet, sensor, mqtt_json)
            if not found_property:
                logging.warning("message not interpretable: %s", sensor['name'])
            else:
                self._publish_mqtt(sensor, mqtt_json)
        else:
            # learn request received
            logging.info("learn request not emitted to mqtt")

    def _handle_data_packet(self, packet, sensor, mqtt_json):
        # radio packet of proper rorg type received; parse EEP
        found_property = False
        direction = None
        if sensor.get('direction'):
            direction = sensor.get('direction')

        # Retrieve command from the received packet and pass it to parse_eep()
        command = None
        if sensor.get('command'):
            command = self._get_command_id(packet, sensor)
            if command:
                logging.debug('Retrieved command id from packet: %s', hex(command))

        # Retrieve properties from EEP
        properties = packet.parse_eep(sensor['func'], sensor['type'], direction, command)

        # Now send also raw data to MQTT
        raw_data = packet.data[1:len(packet.data)-1-4]
        raw_data.append(packet.data[-1])
        mqtt_json["_RAW_DATA_"] = enocean.utils.to_hex_string(raw_data)

        # loop through all EEP properties
        for prop_name in properties:
            found_property = True
            cur_prop = packet.parsed[prop_name]
            # we only extract numeric values, either the scaled ones
            # or the raw values for enums
            if isinstance(cur_prop['value'], numbers.Number):
                value = cur_prop['value']
            else:
                value = cur_prop['raw_value']
            # publish extracted information
            logging.debug("%s: %s (%s)=%s %s", sensor['name'], prop_name,
                            cur_prop['description'], cur_prop['value'], cur_prop['unit'])

            # Store property
            mqtt_json[prop_name] = value

        return found_property

    #=============================================================================================
    # LOW LEVEL FUNCTIONS
    #=============================================================================================
    def _reply_packet(self, in_packet, sensor):
        '''send enocean message as a reply to an incoming message'''
        # prepare addresses
        destination = in_packet.sender

        self._send_packet(sensor, destination, None, True,
                          in_packet.data if in_packet.learn else None)

    def _send_packet(self, sensor, destination, command=None,
                     negate_direction=False, learn_data=None):
        '''triggers sending of an enocean packet'''
        # determine direction indicator
        if 'direction' in sensor and sensor.get('direction'):
            direction = sensor['direction']
            if negate_direction:
                # we invert the direction in this reply
                direction = 1 if direction == 2 else 2
        else:
            direction = None
        # is this a response to a learn packet?
        is_learn_response = learn_data is not None

        # Add possibility for the user to indicate a specific sender address
        # in sensor configuration using added 'sender' field.
        # So use specified sender address if any
        if 'sender' in sensor:
            sender = [(sensor['sender'] >> i*8) & 0xff for i in reversed(range(4))]
        else:
            sender = self.enocean_sender

        # Check whether the learn bit should be set in the packet (only valid for RORG.BS1 and RORG.BS4)
        force_learn = False
        if sensor.get('learn'):
            force_learn = True

        try:
            # Now pass command to RadioPacket.create()
            packet = RadioPacket.create(sensor['rorg'], sensor['func'], sensor['type'],
                                        direction=direction, command=command, sender=sender,
                                        destination=destination, learn=is_learn_response|force_learn)
        except ValueError as err:
            logging.error("Cannot create RF packet: %s", err)
            return

        # assemble data based on packet type (learn / data)
        if not is_learn_response:
            # data packet received
            # Check whether payload is raw data
            if 'raw_data' in sensor:
                logging.debug("sensor raw data: %s", sensor['raw_data'])
                try:
                    # Use the EnOcean library hex_string format for raw_data
                    # as there can be more than 8 bytes depending on EEP (VLD)
                    raw_data = enocean.utils.from_hex_string(sensor['raw_data'])
                    # Maximum raw data length including status byte
                    # -1 for RORG, -4 for sender ID
                    max_raw_data_len = len(packet.data)-1-4
                    # Status byte should not be set
                    if len(raw_data) == max_raw_data_len-1:
                        packet.data[1:max_raw_data_len] = raw_data
                    # Status byte should be set
                    elif len(raw_data) == max_raw_data_len:
                        packet.data[1:max_raw_data_len] = raw_data[:-1]
                        packet.data[-1] = raw_data[-1]
                    # Invalid raw data as all data bytes should be set
                    else:
                        raise Exception('Invalid raw data length. Should be in range [{}:{}]'.
                                        format(max_raw_data_len-1,max_raw_data_len))
                except Exception as ex:
                    logging.debug("Invalid raw data: %s (%s)", sensor['raw_data'], ex)
                    return
            else:
                # Initialize packet with default_data if specified
                if 'default_data' in sensor:
                    # Check default_data type
                    try:
                        # Default data is raw data
                        default_data = int(sensor['default_data'], 0)
                        packet.data[1:5] = [(default_data >> i*8) &
                                        0xff for i in reversed(range(4))]
                    except:
                        # Default data is property-based
                        logging.debug("sensor default data: %s", sensor['default_data'])
                        # Set packet data payload
                        packet.set_eep(json.loads(sensor['default_data']))
                        # Set packet status bits
                        packet.data[-1] = packet.status
                        # Ensure that the logging output of packet is updated
                        packet.parse_eep()

                # do we have specific data to send?
                if 'data' in sensor:
                    # override with specific data settings
                    logging.debug("sensor data: %s", sensor['data'])
                    # Set packet data payload with property-based data
                    packet.set_eep(sensor['data'])
                    # Set packet status bits
                    packet.data[-1] = packet.status
                    packet.parse_eep()  # ensure that the logging output of packet is updated
                else:
                    # what to do if we have no data to send yet?
                    logging.warning('sending only default data as answer to %s', sensor['name'])

        else:
            # learn request received
            # copy EEP and manufacturer ID
            packet.data[1:5] = learn_data[1:5]
            # update flags to acknowledge learn request
            packet.data[4] = 0xf0

        # send it
        logging.info("sending: %s", packet)
        self.enocean.send(packet)

    def _confirm_vld_teach_in(self, packet, sensors):
        '''Answer a UTE teach-in request of a VLD device with command 0.

        Some devices (e.g. LUNOS UNI-EO) send UTE teach-in requests without
        expecting a UTE response. They expect a VLD telegram with command 0 as
        teach-in confirmation instead. This is enabled per device with the
        'teach_in_via_vld' option.'''
        if (packet.rorg != RORG.UTE
                or getattr(packet, 'response_expected', True)
                or not getattr(self.enocean, 'teach_in', False)):
            return
        for sensor in sensors:
            command_shortcut = sensor.get('command')
            if str(sensor.get('teach_in_via_vld')) in ("True", "true", "1") and command_shortcut:
                logging.info("Sending VLD teach-in confirmation to %s.",
                             enocean.utils.to_hex_string(packet.sender))
                ack_sensor = dict(sensor)
                ack_sensor['data'] = {command_shortcut: 0}
                ack_sensor.pop('raw_data', None)
                self._send_packet(ack_sensor, packet.sender, 0)
                return

    def _process_radio_packet(self, packet):
        # first, look whether we have this sensor configured
        found_sensor = False
        address = enocean.utils.combine_hex(packet.sender)
        potential_sensors = self._sensors_by_address.get(address, [])

        for cur_sensor in potential_sensors:
            # Does this sensor match?
            if (packet.rorg == cur_sensor.get('rorg')) or \
               (not cur_sensor.get('rorg') and cur_sensor.get('ignore')):
                found_sensor = cur_sensor
                break

        # skip ignored sensors
        if found_sensor and 'ignore' in found_sensor and found_sensor['ignore']:
            return

        # log packet, if not disabled
        if str(self.conf.get('log_packets')) in ("True", "true", "1"):
            logging.info("received: %s", packet)

        # UTE teach-in request of a VLD device that expects a VLD confirmation
        self._confirm_vld_teach_in(packet, potential_sensors)

        # abort loop if sensor not found
        if not found_sensor:
            logging.info("unknown sensor: %s (RORG = %s)", enocean.utils.to_hex_string(packet.sender), hex(packet.rorg))
            return

        # Handling EnOcean library decision to set learn to True by default.
        # Only 1BS and 4BS are correctly handled by the EnOcean library.
        # -> VLD EnOcean devices use UTE as learn mechanism
        if found_sensor['rorg'] == RORG.VLD and packet.rorg != RORG.UTE:
            packet.learn = False
        # -> RPS EnOcean devices only send normal data telegrams.
        # Hence learn can always be set to false
        elif found_sensor['rorg'] == RORG.RPS:
            packet.learn = False

        # interpret packet, read properties and publish to MQTT
        self._read_packet(packet, found_sensor)

        # check for neccessary reply
        if str(found_sensor.get('answer')) in ("True", "true", "1"):
            self._reply_packet(packet, found_sensor)


    #=============================================================================================
    # RUN LOOP
    #=============================================================================================
    def run(self):
        """the main loop with blocking enocean packet receive handler"""
        try:
            # start endless loop for listening
            while self.enocean.is_alive() and not self._shutdown_requested:
                # Request transmitter ID, if needed
                if self.enocean_sender is None:
                    self.enocean_sender = self.enocean.base_id
                    self._log_gateway_info()

                # Loop to empty the queue...
                try:
                    # get next packet
                    packet = self.enocean.receive.get(block=True, timeout=1)

                    # check packet type
                    if packet.packet_type == PACKET.RADIO:
                        self._process_radio_packet(packet)
                    elif packet.packet_type == PACKET.RESPONSE:
                        response_code = RETURN_CODE(packet.data[0])
                        logging.info("got response packet: %s", response_code.name)
                    else:
                        logging.info("got non-RF packet: %s", packet)
                except queue.Empty:
                    pass
                except KeyboardInterrupt:
                    logging.debug("Exception: KeyboardInterrupt")
                    break

                self._maybe_publish_bridge_online()
        finally:
            self.shutdown()
