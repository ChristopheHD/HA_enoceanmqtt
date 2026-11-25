import types
import unittest

from test_bridge_state import install_fake_dependencies

install_fake_dependencies()

# pylint: disable=wrong-import-position
from enoceanmqtt.communicator import Communicator


class MqttValueTests(unittest.TestCase):
    def make_communicator(self):
        sensor = {'name': 'enoceanmqtt/heater', 'address': 0x058EDA56, 'rorg': 0xD2, 'func': 0x33, 'type': 0x00}
        comm = Communicator({'mqtt_host': 'localhost', 'enocean_port': '/dev/ttyUSB0',
                             'mqtt_prefix': 'enoceanmqtt/'}, [sensor])
        return comm, sensor

    def test_parse_number(self):
        self.assertEqual(Communicator._parse_number('12'), 12)
        self.assertEqual(Communicator._parse_number(b'12'), 12)
        self.assertEqual(Communicator._parse_number('21.5'), 21.5)
        self.assertIsInstance(Communicator._parse_number('1.0'), int)
        self.assertEqual(Communicator._parse_number(3), 3)
        with self.assertRaises(ValueError):
            Communicator._parse_number('on')

    def test_json_values_accept_decimals(self):
        comm, sensor = self.make_communicator()
        with self.assertLogs(level='WARNING'):
            comm._mqtt_message_json('enoceanmqtt/heater/req', {'MID': '2', 'TSP': '21.5', 'MODE': 'eco'})
        self.assertEqual(sensor['data'], {'MID': 2, 'TSP': 21.5})

    def test_single_values_accept_decimals(self):
        comm, sensor = self.make_communicator()
        comm._mqtt_message_normal(types.SimpleNamespace(topic='enoceanmqtt/heater/req/TSP', payload=b'19.5'))
        self.assertEqual(sensor['data'], {'TSP': 19.5})


if __name__ == '__main__':
    unittest.main()
