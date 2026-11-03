import json
import os
import tempfile
import unittest

from test_bridge_state import install_fake_dependencies

install_fake_dependencies()

# pylint: disable=wrong-import-position
from enoceanmqtt.overlays.homeassistant.ha_communicator import HACommunicator


class HeaterMappingTests(unittest.TestCase):
    '''Home Assistant mapping of EEP D2-33-00 heaters'''

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        config = {
            'mqtt_host': 'localhost',
            'enocean_port': '/dev/ttyUSB0',
            'mqtt_prefix': 'enoceanmqtt/',
            'mqtt_discovery_prefix': 'homeassistant/',
            'db_file': os.path.join(self.tmpdir.name, 'db.json'),
        }
        self.sensor = {'name': 'enoceanmqtt/heater', 'address': 0x058EDA56,
                       'rorg': 0xD2, 'func': 0x33, 'type': 0x00}
        self.comm = HACommunicator(config, [self.sensor])
        self.comm._mqtt_discovery_eep(self.sensor)
        self.entities = {
            payload['name']: payload
            for payload in (json.loads(item['payload']) for item in self.comm.mqtt.published
                            if item['topic'].startswith('homeassistant/') and item['payload'])
        }

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_device_config(self):
        self.assertEqual(self.sensor['command'], 'MID')
        self.assertEqual(self.sensor['channel'], 'MID')
        self.assertEqual(self.sensor['secure_teachin_telegrams'], 3)

    def test_climate_topics(self):
        climate = self.entities['heater']
        self.assertEqual(climate['current_temperature_topic'], 'enoceanmqtt/heater/MID8')
        self.assertEqual(climate['action_topic'], 'enoceanmqtt/heater/MID8')
        self.assertEqual(climate['temperature_command_topic'], 'enoceanmqtt/heater/req')
        # The heater does not report its setpoint: it is read back from the retained command,
        # and Home Assistant keeps it until a first command is sent
        self.assertEqual(climate['temperature_state_topic'], 'enoceanmqtt/heater/req')
        self.assertEqual(climate['temperature_state_template'], "{{ value_json.TSP | default('') }}")
        self.assertTrue(climate['optimistic'])
        self.assertTrue(climate['retain'])
        self.assertEqual(climate['modes'], ['heat'])

    def test_setpoint_command_is_a_permanent_program(self):
        template = self.entities['heater']['temperature_command_template']
        payload = json.loads(template.replace('{{ value }}', '21.5'))
        self.assertEqual(payload.pop('send'), 'clear')
        self.comm._mqtt_message_json('enoceanmqtt/heater/req', payload)
        self.assertEqual(self.sensor['data'], {'MID': 2, 'TPT': 0, 'ETD': 0, 'ETM': 0, 'ETH': 0,
                                               'STD': 0, 'STM': 0, 'STH': 0, 'TSP': 21.5, 'CSC': 0})

    def test_setpoint_is_only_read_from_programs(self):
        try:
            import jinja2  # pylint: disable=import-outside-toplevel
        except ImportError:
            self.skipTest('jinja2 is not installed')
        template = jinja2.Environment().from_string(self.entities['heater']['temperature_state_template'])
        self.assertEqual(template.render(value_json={'MID': '2', 'TSP': '19.5'}), '19.5')
        # Other requests are sent to the same topic: Home Assistant ignores an empty value
        self.assertEqual(template.render(value_json={'MID': '0', 'REQ': '9'}), '')

    def test_heater_entities(self):
        self.assertEqual(self.entities['temperature']['state_topic'], 'enoceanmqtt/heater/MID8')
        self.assertIn('value_json.INT', self.entities['temperature']['value_template'])
        self.assertIn('value_json.HTF', self.entities['heating']['value_template'])
        self.assertIn('value_json.WOF == 2', self.entities['window']['value_template'])
        self.assertIn('value_json.PIF == 2', self.entities['presence']['value_template'])
        self.assertEqual(self.entities['energy']['state_topic'], 'enoceanmqtt/heater/MID9')
        self.assertEqual(self.entities['energy']['state_class'], 'total_increasing')

    def test_error_sensor_decodes_flags(self):
        try:
            import jinja2  # pylint: disable=import-outside-toplevel
        except ImportError:
            self.skipTest('jinja2 is not installed')
        template = jinja2.Environment().from_string(self.entities['error']['value_template'])

        def render(erf):
            return template.render(value_json={'ERF': erf}).strip()

        self.assertEqual(render(0), 'OK')
        self.assertEqual(render(1), 'Temperature sensor open')
        self.assertEqual(render(0b1100), 'Temperature above 50°C, '
                         'Internal and external temperatures differ by more than 4°C')
        self.assertEqual(render(0x100), 'Error 256')

    def test_buttons(self):
        self.assertEqual(json.loads(self.entities['request_status']['payload_press']),
                         {'MID': '0', 'REQ': '8', 'send': 'clear'})
        self.assertEqual(self.entities['secure_teachin']['command_topic'], 'enoceanmqtt/heater/req/send')
        self.assertEqual(self.entities['secure_teachin']['payload_press'], 'secure_teachin')


if __name__ == '__main__':
    unittest.main()
