import json
import os
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import yaml

from enoceanmqtt.overlays.homeassistant.device_manager import DeviceManager
from enoceanmqtt.overlays.homeassistant.device_web import DeviceWebServer


class DeviceManagerMigrationTests(unittest.TestCase):
    def test_imports_ini_devices_once_and_preserves_ini_file(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = os.path.join(directory, 'enoceanmqtt.conf')
            database_path = os.path.join(directory, 'devices.json')
            original_config = (
                '[CONFIG]\nmqtt_host = localhost\n\n'
                '[hall_switch]\naddress = 305419896\nrorg = 246\nfunc = 2\ntype = 1\n'
            )
            with open(config_path, 'w', encoding='utf-8') as config:
                config.write(original_config)

            manager = DeviceManager({'db_file': database_path})
            manager.migrate_ini_devices(
                [{
                    'name': 'enoceanmqtt/hall_switch',
                    'address': 305419896,
                    'rorg': 246,
                    'func': 2,
                    'type': 1
                }],
                'enoceanmqtt/'
            )

            devices = manager.get_config_devices()
            self.assertEqual(len(devices), 1)
            self.assertEqual(devices[0]['name'], 'hall_switch')
            with open(config_path, 'r', encoding='utf-8') as config:
                self.assertEqual(config.read(), original_config)

            restarted_manager = DeviceManager({'db_file': database_path})
            restarted_manager.migrate_ini_devices(
                [{'name': 'enoceanmqtt/new_device', 'address': 1}],
                'enoceanmqtt/'
            )
            self.assertEqual(len(restarted_manager.get_config_devices()), 1)
            with open(config_path, 'r', encoding='utf-8') as config:
                self.assertEqual(config.read(), original_config)


class DeviceWebTests(unittest.TestCase):
    def setUp(self):
        self.mapping = {
            0xA5: {
                0x02: {
                    0x01: {'entities': []}
                }
            },
            'eltako': {
                'fsb14': {
                    'device_config': [{'rorg': '0xA5', 'func': '0x3F', 'type': '0x7F'}]
                }
            }
        }
        self.directory = tempfile.TemporaryDirectory()
        self.manager = DeviceManager({
            'db_file': os.path.join(self.directory.name, 'devices.json')
        })
        self.changes = []
        self.server = DeviceWebServer(
            self.manager,
            self.mapping,
            lambda action, device: self.changes.append((action, device['id'])),
            '127.0.0.1',
            0
        )
        self.server.start()
        host, port = self.server._server.server_address
        self.base_url = 'http://{}:{}'.format(host, port)

    def tearDown(self):
        self.server.stop()
        self.directory.cleanup()

    def test_mapping_yaml_exposes_all_supported_profiles(self):
        mapping_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'enoceanmqtt',
            'overlays',
            'homeassistant',
            'mapping.yaml'
        )
        with open(mapping_path, encoding='utf-8') as mapping_file:
            mapping = yaml.safe_load(mapping_file)

        options = DeviceWebServer._build_options(mapping)
        self.assertGreater(len(options['eeps']), 1)
        self.assertGreater(len(options['models']), 1)
        self.assertGreaterEqual(
            len(options['eeps']) + len(options['models']),
            100
        )

    def test_profile_validation_and_virtual_sender(self):
        eep = self.server._validate_device({
            'name': 'hall_switch',
            'type': 'eep',
            'profile': 'A5-02-01',
            'address': '12345678'
        })
        self.assertEqual((eep['rorg'], eep['func'], eep['type']), (0xA5, 0x02, 0x01))

        model = self.server._validate_device({
            'name': 'roller_shutter',
            'type': 'model',
            'profile': 'eltako/fsb14',
            'address': '12345678',
            'virtual': True,
            'sender': 'FF123456'
        })
        self.assertEqual(model['model'], 'eltako/fsb14')
        self.assertEqual(model['sender'], 0xFF123456)
        with self.assertRaises(ValueError):
            self.server._validate_device({
                'name': 'virtual_switch',
                'type': 'eep',
                'profile': 'A5-02-01',
                'address': '12345678',
                'virtual': True
            })

    def test_device_address_requires_four_hexadecimal_bytes(self):
        payload = {
            'name': 'hall_switch',
            'type': 'eep',
            'profile': 'A5-02-01'
        }
        for invalid_address in (
                '1234567',
                '123456789',
                '1234G678',
                '0x12345678',
                0x12345678):
            with self.subTest(address=invalid_address):
                with self.assertRaisesRegex(ValueError, 'exactly 8 hexadecimal digits'):
                    self.server._validate_device(dict(payload, address=invalid_address))

    def test_device_store_rejects_duplicate_name_and_radio_identity(self):
        device = self.server._validate_device({
            'name': 'hall_switch',
            'type': 'eep',
            'profile': 'A5-02-01',
            'address': '12345678'
        })
        self.manager.add_config_device(device)
        duplicate_name = dict(device, id='another-id', address=0x12345679)
        with self.assertRaises(ValueError):
            self.manager.add_config_device(duplicate_name)

        duplicate_identity = dict(device, id='second-id', name='different_name')
        with self.assertRaises(ValueError):
            self.manager.add_config_device(duplicate_identity)

    def test_api_supports_ingress_prefix_and_device_crud(self):
        prefix = '/api/hassio_ingress/session'
        headers = {'X-Ingress-Path': prefix}
        page = urlopen(Request(
            self.base_url + prefix + '/',
            headers=headers
        )).read().decode('utf-8')
        self.assertIn('<base href="' + prefix + '/">', page)

        options = json.loads(urlopen(Request(
            self.base_url + prefix + '/api/options',
            headers=headers
        )).read().decode('utf-8'))
        self.assertEqual(options['eeps'][0]['value'], 'A5-02-01')
        self.assertEqual(options['models'][0]['value'], 'eltako/fsb14')

        body = json.dumps({
            'name': 'entry_sensor',
            'type': 'eep',
            'profile': 'A5-02-01',
            'address': '12345678',
            'virtual': False
        }).encode('utf-8')
        response = urlopen(Request(
            self.base_url + prefix + '/api/devices',
            data=body,
            headers={**headers, 'Content-Type': 'application/json'}
        ))
        self.assertEqual(response.status, 201)
        device = json.loads(response.read().decode('utf-8'))['device']
        self.assertEqual(device['name'], 'entry_sensor')
        self.assertEqual(self.changes, [('add', device['id'])])

        response = urlopen(Request(
            self.base_url + prefix + '/api/devices/' + device['id'],
            headers=headers,
            method='DELETE'
        ))
        self.assertEqual(response.status, 200)
        self.assertIsNone(self.manager.get_config_device(device['id']))
        self.assertEqual(self.changes[-1], ('delete', device['id']))

        with self.assertRaises(HTTPError) as error:
            urlopen(Request(
                self.base_url + prefix + '/api/devices',
                data=b'{"name":"bad/name"}',
                headers={**headers, 'Content-Type': 'application/json'}
            ))
        self.assertEqual(error.exception.code, 400)


if __name__ == '__main__':
    unittest.main()
