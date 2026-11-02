import types
import unittest

from test_bridge_state import MemorySecureStore, install_fake_dependencies

install_fake_dependencies()

# pylint: disable=wrong-import-position
from enoceanmqtt import communicator as communicator_module
from enocean.protocol import security
from enocean.protocol.constants import RORG, SECURE_STATUS

KEY = bytes(range(16))
RADIATOR = 0x058EDA56
RADIATOR_ID = [0x05, 0x8E, 0xDA, 0x56]
SENDER = 0xFF8C1C81
SENDER_ID = [0xFF, 0x8C, 0x1C, 0x81]
CHIP_ID = [0x01, 0x9A, 0x8B, 0x7C]


class SimpleRadioPacket:
    '''Minimal stand-in for the EnOcean library RadioPacket'''
    def __init__(self, packet_type, data=None, optional=None):
        self.packet_type = packet_type
        self.data = list(data)
        self.optional = list(optional)
        self.rorg = self.data[0]
        self.sender = self.data[-5:-1]
        self.received = None


class SecureCommunicatorTests(unittest.TestCase):
    def setUp(self):
        self._radio_packet = communicator_module.RadioPacket
        communicator_module.RadioPacket = SimpleRadioPacket
        # The device database survives the communicators, as it does restarts
        self.store = MemorySecureStore()
        self._secure_store = communicator_module.SecureStore
        communicator_module.SecureStore = lambda database: self.store

    def tearDown(self):
        communicator_module.RadioPacket = self._radio_packet
        communicator_module.SecureStore = self._secure_store

    def pair(self, **state):
        '''store the state of a device paired with KEY'''
        record = {'key': KEY.hex().upper(), 'slf': 0x8B, 'rlc': 0, 'rlc_snd': 0}
        record.update(state)
        self.store.save_state(RADIATOR, record)

    def make_communicator(self, paired=False, **sensor_config):
        if paired:
            self.pair()
        sensor = {
            'name': 'enoceanmqtt/radiator',
            'address': RADIATOR,
            'rorg': 0xD2,
            'func': 0x33,
            'type': 0x00,
        }
        sensor.update(sensor_config)
        config = {
            'mqtt_host': 'localhost',
            'enocean_port': '/dev/ttyUSB0',
            'mqtt_prefix': 'enoceanmqtt/',
        }
        comm = communicator_module.Communicator(config, [sensor])
        comm.enocean_sender = SENDER_ID
        comm._gateway_info = {'esp3': {'chipId': bytes(CHIP_ID).hex()}}
        comm.sent = []
        comm.enocean.send = comm.sent.append
        comm.read = []
        comm._read_packet = lambda packet, sensor: comm.read.append((packet, sensor))
        return comm, sensor

    @staticmethod
    def radio_packet(rorg, data, sender=None):
        return SimpleRadioPacket(1, [rorg] + list(data) + (sender or RADIATOR_ID) + [0],
                                 [0x01, 0xFF, 0xFF, 0xFF, 0xFF, 0x46, 0x00])

    @staticmethod
    def taught(comm):
        '''the teach-in sent by the communicator'''
        return security.parse_teach_in(
            {security.teach_in_index(p.data[1:-5]): bytes(p.data[1:-5]) for p in comm.sent})

    def test_secure_teach_in_pairs_device_with_a_new_key(self):
        comm, sensor = self.make_communicator()
        comm._send_secure_teach_in(sensor)

        self.assertEqual(len(comm.sent), 2)
        for packet in comm.sent:
            self.assertEqual(packet.data[0], RORG.SEC_TI)
            self.assertEqual(packet.optional[1:5], RADIATOR_ID)
        state = self.store.states()[RADIATOR]
        self.assertEqual(self.taught(comm).key.hex().upper(), state['key'])
        self.assertEqual((self.taught(comm).rlc, state['rlc'], state['rlc_snd']), (0, 0, 0))

    def test_secure_teach_in_is_sent_from_chip_id(self):
        comm, sensor = self.make_communicator()
        comm._send_secure_teach_in(sensor)
        self.assertEqual([p.data[-5:-1] for p in comm.sent], [CHIP_ID] * 2)

        # the device is then sent its telegrams from the address it was paired from
        comm, sensor = self.make_communicator()
        self.assertEqual(comm._get_sender(sensor), CHIP_ID)

    def test_secure_teach_in_without_chip_id_is_sent_from_base_id(self):
        comm, sensor = self.make_communicator()
        comm._gateway_info = {}
        with self.assertLogs(level='WARNING'):
            comm._send_secure_teach_in(sensor)
        self.assertEqual([p.data[-5:-1] for p in comm.sent], [SENDER_ID] * 2)

    def test_secure_teach_in_is_sent_from_configured_sender(self):
        comm, sensor = self.make_communicator(sender=0x01020304)
        comm._send_secure_teach_in(sensor)
        self.assertEqual([p.data[-5:-1] for p in comm.sent], [[0x01, 0x02, 0x03, 0x04]] * 2)

    def test_secure_teach_in_replaces_existing_key(self):
        self.pair(rlc=5, rlc_snd=7)
        comm, sensor = self.make_communicator(secure_teachin_telegrams=3)
        comm._send_secure_teach_in(sensor)

        self.assertEqual(len(comm.sent), 3)
        state = self.store.states()[RADIATOR]
        self.assertNotEqual(self.taught(comm).key, KEY)
        self.assertEqual(self.taught(comm).key.hex().upper(), state['key'])
        self.assertEqual((self.taught(comm).rlc, state['rlc'], state['rlc_snd']), (0, 0, 0))

    def test_invalid_secure_teach_in_is_not_sent(self):
        comm, sensor = self.make_communicator(secure_teachin_telegrams=4)
        with self.assertLogs(level='ERROR'):
            comm._send_secure_teach_in(sensor)
        self.assertEqual(comm.sent, [])

    def test_mqtt_send_action_triggers_secure_teach_in(self):
        comm, _ = self.make_communicator()
        comm._mqtt_message_normal(types.SimpleNamespace(topic='enoceanmqtt/radiator/req/send',
                                                        payload=b'secure_teachin'))
        self.assertEqual([p.data[0] for p in comm.sent], [RORG.SEC_TI] * 2)

    def test_mqtt_json_send_action_triggers_secure_teach_in(self):
        comm, _ = self.make_communicator()
        comm._mqtt_message_json('enoceanmqtt/radiator/req', {'send': 'secure_teachin'})
        self.assertEqual([p.data[0] for p in comm.sent], [RORG.SEC_TI] * 2)

    def test_teach_in_key_is_not_logged(self):
        comm, sensor = self.make_communicator(paired=True)
        with self.assertLogs(level='DEBUG') as logs:
            comm._send_secure_teach_in(sensor)
        self.assertEqual(len(comm.sent), 2)
        self.assertNotIn(KEY.hex().upper(), '\n'.join(logs.output).upper())

    def test_secure_devices_are_given_to_the_enocean_library(self):
        self.pair(rlc=5)
        comm, sensor = self.make_communicator()
        secure_devices = comm.enocean.secure_devices
        self.assertEqual(secure_devices.state(RADIATOR)['rlc'], 5)
        # their changes are kept in the device database
        secure_devices.decrypt(RADIATOR, *security.encrypt(KEY, 0x8B, 5, 0xD2, b'\x80\x00'))
        self.assertEqual(self.store.states()[RADIATOR]['rlc'], 6)

    def secure_status_packet(self, status, rorg=0xD2, data=b'\x80\x00', sender=None):
        packet = self.radio_packet(rorg, data, sender)
        packet.secure_status = status
        return packet

    def test_decrypted_telegram_is_processed(self):
        comm, sensor = self.make_communicator(paired=True)
        packet = self.secure_status_packet(SECURE_STATUS.DECRYPTED)
        comm._process_radio_packet(packet)
        self.assertEqual(comm.read, [(packet, sensor)])

    def test_rejected_telegram_is_logged(self):
        for status in (SECURE_STATUS.REJECTED, SECURE_STATUS.UNSUPPORTED):
            comm, _ = self.make_communicator(paired=True)
            with self.assertLogs(level='WARNING') as logs:
                comm._process_radio_packet(self.secure_status_packet(status, rorg=RORG.SEC_ENCAPS))
            self.assertIn('enoceanmqtt/radiator: secure telegram', '\n'.join(logs.output))
            self.assertEqual(comm.read, [])

    def test_telegram_of_device_without_key_is_logged(self):
        comm, _ = self.make_communicator()
        with self.assertLogs(level='WARNING') as logs:
            comm._process_radio_packet(self.secure_status_packet(SECURE_STATUS.UNKNOWN_KEY, rorg=RORG.SEC_ENCAPS))
        self.assertIn('no key is known, pair the device', '\n'.join(logs.output))
        self.assertEqual(comm.read, [])

    def test_device_declared_with_secure_rorg_receives_its_telegrams_as_they_are(self):
        # e.g. a device declared with rorg = 0x31 to get its RSSI
        comm, sensor = self.make_communicator(rorg=RORG.SEC_ENCAPS)
        packet = self.secure_status_packet(SECURE_STATUS.UNKNOWN_KEY, rorg=RORG.SEC_ENCAPS)
        with self.assertNoLogs(level='WARNING'):
            comm._process_radio_packet(packet)
        self.assertEqual(comm.read, [(packet, sensor)])

    def test_learned_key_is_logged(self):
        comm, _ = self.make_communicator()
        with self.assertLogs(level='INFO') as logs:
            comm._process_radio_packet(self.secure_status_packet(SECURE_STATUS.KEY_LEARNED, rorg=RORG.SEC_TI))
        self.assertIn('enoceanmqtt/radiator: paired from its secure teach-in', '\n'.join(logs.output))
        self.assertEqual(comm.read, [])

    def test_teach_in_is_ignored_when_teach_in_is_disabled(self):
        comm, _ = self.make_communicator()
        comm.enocean.teach_in = False
        with self.assertLogs(level='INFO') as logs:
            comm._process_radio_packet(self.secure_status_packet(SECURE_STATUS.TEACH_IN, rorg=RORG.SEC_TI))
        self.assertIn('ignoring secure teach-in', '\n'.join(logs.output))
        self.assertEqual(comm.read, [])

    def test_part_of_teach_in_is_not_processed(self):
        comm, _ = self.make_communicator()
        comm.enocean.teach_in = True
        with self.assertNoLogs(level='INFO'):
            comm._process_radio_packet(self.secure_status_packet(SECURE_STATUS.TEACH_IN, rorg=RORG.SEC_TI))
        self.assertEqual(comm.read, [])


if __name__ == '__main__':
    unittest.main()
