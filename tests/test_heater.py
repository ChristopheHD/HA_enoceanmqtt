import datetime
import os
import tempfile
import unittest

from test_bridge_state import MemorySecureStore, install_fake_dependencies

install_fake_dependencies()

# pylint: disable=wrong-import-position
from enoceanmqtt import communicator as communicator_module
from enoceanmqtt import heater
from enocean.protocol.constants import SECURE_STATUS

HEATER = 0x058EDA56
HEATER_ID = [0x05, 0x8E, 0xDA, 0x56]


class SimpleRadioPacket:
    '''Minimal stand-in for the EnOcean library RadioPacket'''
    def __init__(self, packet_type, data=None, optional=None):
        self.packet_type = packet_type
        self.data = list(data)
        self.optional = list(optional or [])
        self.rorg = self.data[0]
        self.sender = self.data[-5:-1]
        self.received = None


class FixedDatetime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 26, 14, 30, 12)


class HeaterTests(unittest.TestCase):
    '''EEP D2-33-00 acknowledge mechanism ("Rules for the communications" of the EEP)'''

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self._radio_packet = communicator_module.RadioPacket
        communicator_module.RadioPacket = SimpleRadioPacket
        self.store = MemorySecureStore()
        self._secure_store = communicator_module.SecureStore
        communicator_module.SecureStore = lambda database: self.store

    def tearDown(self):
        communicator_module.RadioPacket = self._radio_packet
        communicator_module.SecureStore = self._secure_store
        self.tmpdir.cleanup()

    def make_communicator(self, **sensor_config):
        sensor = {
            'name': 'enoceanmqtt/heater',
            'address': HEATER,
            'rorg': communicator_module.RORG.VLD,
            'func': 0x33,
            'type': 0x00,
            'command': 'MID',
        }
        sensor.update(sensor_config)
        config = {
            'mqtt_host': 'localhost',
            'enocean_port': '/dev/ttyUSB0',
            'mqtt_prefix': 'enoceanmqtt/',
            'db_file': os.path.join(self.tmpdir.name, 'db.json'),
        }
        comm = communicator_module.Communicator(config, [sensor])
        comm.answers = []
        comm.answer_sensors = []

        def send_packet(answer_sensor, destination, command=None):
            comm.answers.append((answer_sensor['data'], destination, command))
            comm.answer_sensors.append(answer_sensor)
        comm._send_packet = send_packet
        comm._read_packet = lambda packet, sensor: None
        return comm, sensor

    def receive(self, comm, payload):
        comm._process_radio_packet(
            SimpleRadioPacket(1, [communicator_module.RORG.VLD] + payload + HEATER_ID + [0]))

    def test_status_information_is_acknowledged(self):
        comm, _ = self.make_communicator()
        self.receive(comm, [0x84, 0x00, 0x00, 0x88, 0x1A, 0xA0])
        self.assertEqual(comm.answers, [({'MID': 0, 'REQ': 15}, HEATER_ID, 0)])

    def test_heater_parameters_are_acknowledged(self):
        comm, _ = self.make_communicator()
        self.receive(comm, [0x90, 0x03, 0x03, 0x95, 0xF0, 0xC8])
        self.assertEqual(comm.answers, [({'MID': 0, 'REQ': 15}, HEATER_ID, 0)])

    def test_external_temperature_request_is_acknowledged(self):
        comm, _ = self.make_communicator()
        self.receive(comm, [0x80, 0x00, 0x00, 0x00, 0x00, 0x00])
        self.assertEqual(comm.answers, [({'MID': 0, 'REQ': 15}, HEATER_ID, 0)])

    def test_time_and_date_request_is_answered(self):
        comm, _ = self.make_communicator()
        original = heater.datetime.datetime
        heater.datetime.datetime = FixedDatetime
        try:
            self.receive(comm, [0x83, 0x00, 0x00, 0x00, 0x00, 0x00])
        finally:
            heater.datetime.datetime = original
        self.assertEqual(comm.answers, [({'MID': 3, 'DAY': 26, 'MON': 10, 'YR': 2026, 'MIN': 30,
                                          'HR': 14, 'DAYW': 0}, HEATER_ID, 3)])

    def test_program_request_is_answered_with_last_program(self):
        comm, sensor = self.make_communicator()
        self.receive(comm, [0x82, 0x00, 0x00, 0x00, 0x00, 0x00])
        self.assertEqual(comm.answers, [])

        comm._mqtt_message_json('enoceanmqtt/heater/req', {'MID': '2', 'TPT': '0', 'TSP': '19.5',
                                                           'send': 'clear'})
        self.assertNotIn('data', sensor)
        comm.answers.clear()
        self.receive(comm, [0x82, 0x00, 0x00, 0x00, 0x00, 0x00])
        self.assertEqual(comm.answers, [({'MID': 2, 'TPT': 0, 'TSP': 19.5}, HEATER_ID, 2)])

    def test_acknowledge_and_sensor_parameters_request_are_not_answered(self):
        comm, _ = self.make_communicator()
        self.receive(comm, [0x8F, 0x00, 0x00, 0x00, 0x00, 0x00])
        self.receive(comm, [0x81, 0x00, 0x00, 0x00, 0x00, 0x00])
        self.assertEqual(comm.answers, [])

    def test_other_devices_are_not_answered(self):
        comm, _ = self.make_communicator(func=0x50)
        self.receive(comm, [0x84, 0x00, 0x00, 0x88, 0x1A, 0xA0])
        self.assertEqual(comm.answers, [])

    def test_answer_to_secure_heater_keeps_its_sender(self):
        # the telegram is decrypted by the EnOcean library, which also encrypts the answer
        comm, sensor = self.make_communicator(sender=0xFF8C1C81)
        packet = SimpleRadioPacket(1, [communicator_module.RORG.VLD, 0x84, 0x00, 0x00, 0x88, 0x1A, 0xA0] + HEATER_ID + [0])
        packet.secure_status = SECURE_STATUS.DECRYPTED
        comm._process_radio_packet(packet)

        self.assertEqual(comm.answers, [({'MID': 0, 'REQ': 15}, HEATER_ID, 0)])
        self.assertEqual(comm.answer_sensors[0]['sender'], 0xFF8C1C81)
        self.assertEqual(comm.answer_sensors[0]['address'], HEATER)
        self.assertNotIn('data', sensor)


if __name__ == '__main__':
    unittest.main()
