import importlib
import json
import queue
import sys
import types
import unittest


def install_fake_dependencies():
    if 'paho.mqtt.client' in sys.modules:
        return

    class FakePublishInfo:
        def __init__(self, topic, payload, retain):
            self.topic = topic
            self.payload = payload
            self.retain = retain
            self._waited = False

        def wait_for_publish(self):
            self._waited = True
            return True

    class FakeMQTTClient:
        instances = []

        def __init__(self, client_id=''):
            self.client_id = client_id
            self.will = None
            self.on_connect = None
            self.on_disconnect = None
            self.on_message = None
            self.on_publish = None
            self.published = []
            self.subscriptions = []
            self.events = []
            self.connected = False
            FakeMQTTClient.instances.append(self)

        def will_set(self, topic, payload, retain=False, qos=0):
            self.will = {
                'topic': topic,
                'payload': payload,
                'retain': retain,
                'qos': qos,
            }

        def username_pw_set(self, *_args, **_kwargs):
            self.events.append(('username_pw_set',))

        def tls_set(self, *_args, **_kwargs):
            self.events.append(('tls_set',))

        def tls_insecure_set(self, *_args, **_kwargs):
            self.events.append(('tls_insecure_set',))

        def enable_logger(self):
            self.events.append(('enable_logger',))

        def connect_async(self, host, port=1883, keepalive=60):
            self.events.append(('connect_async', host, port, keepalive))

        def loop_start(self):
            self.events.append(('loop_start',))

        def loop_stop(self):
            self.events.append(('loop_stop',))

        def disconnect(self):
            self.events.append(('disconnect',))
            self.connected = False

        def subscribe(self, topic):
            self.subscriptions.append(topic)
            self.events.append(('subscribe', topic))

        def publish(self, topic, payload, retain=False):
            record = {
                'topic': topic,
                'payload': payload,
                'retain': retain,
            }
            self.published.append(record)
            self.events.append(('publish', topic, payload, retain))
            return FakePublishInfo(topic, payload, retain)

    fake_paho = types.ModuleType('paho')
    fake_paho_mqtt = types.ModuleType('paho.mqtt')
    fake_paho_mqtt_client = types.ModuleType('paho.mqtt.client')
    fake_paho_mqtt_client.Client = FakeMQTTClient
    fake_paho_mqtt.client = fake_paho_mqtt_client
    fake_paho.mqtt = fake_paho_mqtt
    sys.modules['paho'] = fake_paho
    sys.modules['paho.mqtt'] = fake_paho_mqtt
    sys.modules['paho.mqtt.client'] = fake_paho_mqtt_client

    class FakeTinyDB:
        def __init__(self, *_args, **_kwargs):
            self.records = []

        def all(self):
            return list(self.records)

        def contains(self, *_args, **_kwargs):
            return False

        def get(self, *_args, **_kwargs):
            return None

        def update(self, *_args, **_kwargs):
            return []

        def insert(self, record):
            self.records.append(record)
            return len(self.records)

        def upsert(self, record, *_args, **_kwargs):
            self.records.append(record)
            return [len(self.records)]

        def remove(self, *_args, **_kwargs):
            return []

    class FakeQuery:
        def __getattr__(self, _name):
            return self

        def __getitem__(self, _name):
            return self

        def all(self, *_args, **_kwargs):
            return self

        def __eq__(self, _other):
            return self

    fake_tinydb = types.ModuleType('tinydb')
    fake_tinydb.TinyDB = FakeTinyDB
    fake_tinydb.Query = FakeQuery
    sys.modules['tinydb'] = fake_tinydb

    fake_enocean = types.ModuleType('enocean')
    fake_utils = types.ModuleType('enocean.utils')

    def combine_hex(value):
        if isinstance(value, int):
            return value
        result = 0
        for item in value:
            result = (result << 8) | int(item)
        return result

    def to_hex_string(value):
        if isinstance(value, (bytes, bytearray)):
            return ':'.join(f'{byte:02X}' for byte in value)
        if isinstance(value, (list, tuple)):
            return ':'.join(f'{int(byte):02X}' for byte in value)
        return str(value)

    def from_hex_string(value):
        if isinstance(value, str):
            return bytearray(int(part, 16) for part in value.split(':'))
        return bytearray(value)

    fake_utils.combine_hex = combine_hex
    fake_utils.to_hex_string = to_hex_string
    fake_utils.from_hex_string = from_hex_string

    fake_protocol = types.ModuleType('enocean.protocol')
    fake_packet = types.ModuleType('enocean.protocol.packet')
    fake_constants = types.ModuleType('enocean.protocol.constants')
    fake_communicators = types.ModuleType('enocean.communicators')
    fake_communicators_communicator = types.ModuleType('enocean.communicators.communicator')
    fake_serialcommunicator = types.ModuleType('enocean.communicators.serialcommunicator')

    class FakePacket:
        def __init__(self, *_args, **_kwargs):
            self.packet_type = None
            self.data = [0]
            self.sender = [0, 0, 0, 0]
            self.rorg = 0

    class FakeBaseCommunicator:
        def __init__(self, *_args, **_kwargs):
            self._stop_flag = types.SimpleNamespace(is_set=lambda: False)

    class FakeRadioPacket:
        pass

    class FakePacketInstance:
        def __init__(self, *_args, **_kwargs):
            self.packet_type = None
            self.data = [0]

    FakePacketInstance.COMMON_COMMAND = 0

    class FakePacketType:
        RADIO = 1
        RESPONSE = 2

    class FakeRorg:
        VLD = 0x07
        RPS = 0xF6
        UTE = 0xD4

    class FakeReturnCode:
        def __init__(self, value):
            self.name = f'RC_{value}'

    def return_code(value):
        return FakeReturnCode(value)

    class FakeEnoceanThread:
        def __init__(self, *_args, **_kwargs):
            self.started = False
            self.stopped = False
            self.teach_in = True
            self.base_id = [0x01, 0x02, 0x03, 0x04]
            self.receive = types.SimpleNamespace(get=self._raise_empty)

        def _raise_empty(self, *_args, **_kwargs):
            raise queue.Empty

        def start(self):
            self.started = True

        def is_alive(self):
            return not self.stopped

        def stop(self):
            self.stopped = True

    fake_packet.RadioPacket = FakeRadioPacket
    fake_packet.Packet = FakePacketInstance
    fake_constants.PACKET = FakePacketType
    fake_constants.RETURN_CODE = return_code
    fake_constants.RORG = FakeRorg
    fake_communicators_communicator.Communicator = FakeBaseCommunicator
    fake_serialcommunicator.SerialCommunicator = FakeEnoceanThread

    fake_enocean.utils = fake_utils
    fake_enocean.protocol = fake_protocol
    fake_enocean.communicators = fake_communicators

    sys.modules['enocean'] = fake_enocean
    sys.modules['enocean.utils'] = fake_utils
    sys.modules['enocean.protocol'] = fake_protocol
    sys.modules['enocean.protocol.packet'] = fake_packet
    sys.modules['enocean.protocol.constants'] = fake_constants
    sys.modules['enocean.communicators'] = fake_communicators
    sys.modules['enocean.communicators.communicator'] = fake_communicators_communicator
    sys.modules['enocean.communicators.serialcommunicator'] = fake_serialcommunicator


install_fake_dependencies()

Communicator = importlib.import_module('enoceanmqtt.communicator').Communicator
HACommunicator = importlib.import_module('enoceanmqtt.overlays.homeassistant.ha_communicator').HACommunicator


class LoopOnceQueue:
    def get(self, *_args, **_kwargs):
        raise queue.Empty


class LoopOnceEnocean:
    def __init__(self):
        self.base_id = [0x11, 0x22, 0x33, 0x44]
        self.receive = LoopOnceQueue()
        self.started = True
        self.stopped = False
        self._alive_calls = 0

    def is_alive(self):
        self._alive_calls += 1
        return self._alive_calls <= 2 and not self.stopped

    def stop(self):
        self.stopped = True


class BridgeStateTests(unittest.TestCase):
    def make_communicator(self, prefix='enoceanmqtt/', sensors=None):
        if sensors is None:
            sensors = []
        config = {
            'mqtt_host': 'localhost',
            'enocean_port': '/dev/ttyUSB0',
            'mqtt_prefix': prefix,
            'mqtt_client_id': 'client-1',
            'mqtt_keepalive': '60',
        }
        return Communicator(config, sensors)

    def test_last_will_uses_configured_prefix_and_is_retained(self):
        comm = self.make_communicator(prefix='custom/root/')

        self.assertEqual(comm.mqtt.will['topic'], 'custom/root/__system/state')
        self.assertEqual(comm.mqtt.will['payload'], json.dumps({'state': 'offline'}))
        self.assertTrue(comm.mqtt.will['retain'])
        self.assertEqual(comm.build_version, 'null')

    def test_online_is_published_once_bridge_is_ready_and_is_retained(self):
        comm = self.make_communicator(prefix='custom/root/')
        comm._on_connect(comm.mqtt, None, None, 0)
        comm.enocean = LoopOnceEnocean()
        comm.run()

        bridge_publishes = [
            item for item in comm.mqtt.published
            if item['topic'] == 'custom/root/__system/state'
        ]
        self.assertGreaterEqual(len(bridge_publishes), 2)
        self.assertEqual(bridge_publishes[0]['payload'], json.dumps({'state': 'online'}))
        self.assertTrue(bridge_publishes[0]['retain'])
        self.assertEqual(bridge_publishes[-1]['payload'], json.dumps({'state': 'offline'}))
        self.assertTrue(bridge_publishes[-1]['retain'])

    def test_online_is_republished_after_mqtt_reconnect(self):
        comm = self.make_communicator(prefix='custom/root/')
        comm.enocean_sender = [0x11, 0x22, 0x33, 0x44]
        comm._on_connect(comm.mqtt, None, None, 0)
        comm._on_disconnect(comm.mqtt, None, 1)
        comm._on_connect(comm.mqtt, None, None, 0)

        online_publishes = [
            item for item in comm.mqtt.published
            if item['topic'] == 'custom/root/__system/state'
        ]
        self.assertGreaterEqual(len(online_publishes), 2)
        self.assertEqual(online_publishes[-1]['payload'], json.dumps({'state': 'online'}))
        self.assertTrue(all(item['retain'] for item in online_publishes))

    def test_offline_is_published_before_clean_disconnect(self):
        comm = self.make_communicator(prefix='custom/root/')
        comm.enocean_sender = [0x11, 0x22, 0x33, 0x44]
        comm._on_connect(comm.mqtt, None, None, 0)
        comm.shutdown()

        publish_index = next(
            index for index, event in enumerate(comm.mqtt.events)
            if event[0] == 'publish' and event[1] == 'custom/root/__system/state'
        )
        disconnect_index = next(
            index for index, event in enumerate(comm.mqtt.events)
            if event[0] == 'disconnect'
        )
        self.assertLess(publish_index, disconnect_index)
        self.assertEqual(comm.mqtt.published[-1]['payload'], json.dumps({'state': 'offline'}))
        self.assertTrue(comm.mqtt.published[-1]['retain'])

    def test_enocean_topic_retain_behavior_remains_unchanged(self):
        comm = self.make_communicator(prefix='custom/root/')

        comm._publish_mqtt(
            {
                'name': 'custom/root/device',
                'publish_json': '1',
                'persistent': '0',
            },
            {'value': 1, '_RSSI_': -42, '_DATE_': '2026-09-22T12:00:00'},
        )
        comm._publish_mqtt(
            {
                'name': 'custom/root/device2',
                'publish_json': '1',
                'persistent': '1',
            },
            {'value': 2, '_RSSI_': -41, '_DATE_': '2026-09-22T12:00:01'},
        )

        self.assertEqual(comm.mqtt.published[0]['topic'], 'custom/root/device')
        self.assertFalse(comm.mqtt.published[0]['retain'])
        self.assertEqual(comm.mqtt.published[1]['topic'], 'custom/root/device2')
        self.assertTrue(comm.mqtt.published[1]['retain'])


class DiscoveryAvailabilityTests(unittest.TestCase):
    def make_ha_communicator(self):
        config = {
            'mqtt_host': 'localhost',
            'enocean_port': '/dev/ttyUSB0',
            'mqtt_prefix': 'enoceanmqtt/',
            'mqtt_discovery_prefix': 'homeassistant/',
            'mqtt_client_id': 'client-1',
            'mqtt_keepalive': '60',
        }
        return HACommunicator(config, [])

    def test_ha_discovery_includes_bridge_availability(self):
        comm = self.make_ha_communicator()
        sensor = {
            'name': 'enoceanmqtt/window',
            'address': 0x12345678,
            'rorg': 0xD2,
            'func': 0x06,
            'type': 0x01,
        }

        comm._mqtt_discovery_eep(sensor)
        payloads = [
            json.loads(item['payload'])
            for item in comm.mqtt.published
            if item['topic'].endswith('/config') and item['payload']
        ]
        burglary_alarm = next(item for item in payloads if item.get('name') == 'burglary_alarm')

        self.assertIn('availability', burglary_alarm)
        self.assertNotIn('availability_topic', burglary_alarm)
        self.assertEqual(
            burglary_alarm['availability'][-1],
            {
                'topic': 'enoceanmqtt/__system/state',
                'value_template': '{{ value_json.state }}',
            },
        )
        self.assertEqual(
            burglary_alarm['availability'][0]['topic'],
            'enoceanmqtt/window/MT0',
        )
        self.assertIn('offline', burglary_alarm['availability'][0]['value_template'])
        self.assertIn('online', burglary_alarm['availability'][0]['value_template'])

    def test_device_discovery_is_republished_on_reconnect_with_availability(self):
        comm = self.make_ha_communicator()
        comm.enocean_sender = [0x11, 0x22, 0x33, 0x44]
        comm.sensors = [{
            'name': 'enoceanmqtt/window',
            'address': 0x12345678,
            'rorg': 0xD2,
            'func': 0x06,
            'type': 0x01,
        }]

        comm._on_connect(comm.mqtt, None, None, 0)
        comm._on_disconnect(comm.mqtt, None, 1)
        comm._on_connect(comm.mqtt, None, None, 0)

        payloads = [
            json.loads(item['payload'])
            for item in comm.mqtt.published
            if item['topic'].endswith('/config') and item['payload']
        ]
        burglary_alarm = [item for item in payloads if item.get('name') == 'burglary_alarm']

        self.assertGreaterEqual(len(burglary_alarm), 2)
        for item in burglary_alarm:
            self.assertIn('availability', item)
            self.assertEqual(
                item['availability'][-1],
                {
                    'topic': 'enoceanmqtt/__system/state',
                    'value_template': '{{ value_json.state }}',
                },
            )

    def test_system_discovery_includes_bridge_availability(self):
        comm = self.make_ha_communicator()
        comm.enocean_sender = [0x11, 0x22, 0x33, 0x44]

        comm._mqtt_discovery_system('learn')
        payloads = [
            json.loads(item['payload'])
            for item in comm.mqtt.published
            if item['topic'].endswith('/config') and item['payload']
        ]
        learn = next(item for item in payloads if item.get('name') == 'ENOCEAN_LEARN')
        bridge_device = comm._bridge_device()

        self.assertEqual(
            learn['availability'],
            [{
                'topic': 'enoceanmqtt/__system/state',
                'value_template': '{{ value_json.state }}',
            }],
        )
        self.assertEqual(learn['device'], bridge_device)
        self.assertTrue(
            any(
                item['topic'] == 'homeassistant/switch/enoceanmqtt_learn_11223344/config'
                and item['payload'] == ''
                and item['retain']
                for item in comm.mqtt.published
            )
        )

    def test_eep_device_discovery_sets_via_device_to_bridge(self):
        comm = self.make_ha_communicator()
        sensor = {
            'name': 'enoceanmqtt/window',
            'address': 0x12345678,
            'rorg': 0xD2,
            'func': 0x06,
            'type': 0x01,
        }

        comm._mqtt_discovery_eep(sensor)

        payloads = [
            json.loads(item['payload'])
            for item in comm.mqtt.published
            if item['topic'].endswith('/config') and item['payload']
        ]
        burglary_alarm = next(item for item in payloads if item.get('name') == 'burglary_alarm')

        self.assertEqual(
            burglary_alarm['device']['via_device'],
            comm._bridge_device_identifier(),
        )

    def test_model_device_discovery_sets_via_device_to_bridge(self):
        comm = self.make_ha_communicator()
        sensor = {
            'name': 'enoceanmqtt/model/ABC',
            'address': 0x12345678,
            'manufacturer': 'foo',
            'model': 'bar',
        }

        comm._mqtt_discovery_model(sensor)

        payloads = [
            json.loads(item['payload'])
            for item in comm.mqtt.published
            if item['topic'].endswith('/config') and item['payload']
        ]
        discovered = next(item for item in payloads if item.get('device', {}).get('via_device'))

        self.assertEqual(
            discovered['device']['via_device'],
            comm._bridge_device_identifier(),
        )

    def test_bridge_discovery_publishes_binary_sensor_and_version_sensor(self):
        comm = self.make_ha_communicator()
        comm.enocean_sender = [0x11, 0x22, 0x33, 0x44]
        comm._on_connect(comm.mqtt, None, None, 0)

        payloads = [
            json.loads(item['payload'])
            for item in comm.mqtt.published
            if item['topic'].endswith('/config') and item['payload']
        ]
        connection = next(item for item in payloads if item.get('name') == 'Connection state')
        version = next(item for item in payloads if item.get('name') == 'Version')
        bridge_info = next(item for item in comm.mqtt.published if item['topic'] == 'enoceanmqtt/__system/info')
        connection_config_topic = next(
            item['topic'] for item in comm.mqtt.published
            if item['topic'].endswith('/config') and json.loads(item['payload']).get('name') == 'Connection state'
        )

        self.assertEqual(connection['device_class'], 'connectivity')
        self.assertEqual(connection['device']['manufacturer'], 'https://github.com/ChristopheHD/HA_enoceanmqtt')
        self.assertNotIn('via_device', connection['device'])
        self.assertEqual(connection['state_topic'], 'enoceanmqtt/__system/state')
        self.assertEqual(connection['value_template'], '{{ value_json.state }}')
        self.assertEqual(connection['payload_on'], 'online')
        self.assertEqual(connection['payload_off'], 'offline')
        self.assertEqual(connection_config_topic, 'homeassistant/binary_sensor/enoceanmqtt_bridge/connection_state/config')
        self.assertEqual(version['object_id'], 'enoceanmqtt_bridge_version')
        self.assertNotIn('via_device', version['device'])
        self.assertEqual(version['state_topic'], 'enoceanmqtt/__system/info')
        self.assertEqual(version['value_template'], '{{ value_json.version }}')
        self.assertEqual(version['availability_mode'], 'all')
        self.assertEqual(version['availability'][0]['topic'], 'enoceanmqtt/__system/state')
        self.assertEqual(version['availability'][0]['value_template'], '{{ value_json.state }}')
        self.assertEqual(json.loads(bridge_info['payload']), {'version': 'null'})
        self.assertTrue(bridge_info['retain'])
        self.assertTrue(bridge_info['retain'])
        self.assertTrue(
            any(
                item['topic'] == 'homeassistant/sensor/enoceanmqtt_bridge/version/config'
                for item in comm.mqtt.published
            )
        )

    def test_bridge_info_is_republished_when_learn_changes(self):
        comm = self.make_ha_communicator()
        comm.enocean_sender = [0x11, 0x22, 0x33, 0x44]
        comm._on_connect(comm.mqtt, None, None, 0)

        comm._handle_system_msg(types.SimpleNamespace(
            topic='enoceanmqtt/__system/learn/req',
            payload=b'ON',
        ))

        bridge_info_publishes = [
            json.loads(item['payload'])
            for item in comm.mqtt.published
            if item['topic'] == 'enoceanmqtt/__system/info'
        ]

        self.assertGreaterEqual(len(bridge_info_publishes), 2)
        self.assertEqual(bridge_info_publishes[-1], {'version': 'null'})

    def test_ha_on_connect_publishes_bridge_state_topic(self):
        comm = self.make_ha_communicator()
        comm.enocean_sender = [0x11, 0x22, 0x33, 0x44]

        comm._on_connect(comm.mqtt, None, None, 0)

        state_publishes = [
            json.loads(item['payload'])
            for item in comm.mqtt.published
            if item['topic'] == 'enoceanmqtt/__system/state'
        ]

        self.assertGreaterEqual(len(state_publishes), 2)
        self.assertEqual(state_publishes[0], {'state': 'offline'})
        self.assertEqual(state_publishes[-1], {'state': 'online'})


if __name__ == '__main__':
    unittest.main()
