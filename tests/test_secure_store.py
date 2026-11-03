import importlib
import json
import os
import stat
import sys
import tempfile
import threading
import unittest


def import_real(*names):
    '''import modules with the real TinyDB, which the other tests replace by a fake one'''
    prefixes = ('tinydb', 'enoceanmqtt.database', 'enoceanmqtt.secure_store')
    saved = {key: sys.modules.pop(key) for key in list(sys.modules) if key.startswith(prefixes)}
    try:
        return [importlib.import_module(name) for name in names]
    finally:
        sys.modules.update(saved)


database, secure_store = import_real('enoceanmqtt.database', 'enoceanmqtt.secure_store')

ADDRESS = 0x01A2B3C4
STATE = {'key': '00' * 16, 'slf': 0x8B, 'rlc': 3, 'rlc_snd': 7}


class SecureStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, 'device_db.json')

    def tearDown(self):
        self.tmpdir.cleanup()

    def open(self):
        return secure_store.SecureStore(database.open_database(self.path))

    def test_unknown_device(self):
        store = self.open()
        self.assertEqual(store.states(), {})
        self.assertIsNone(store.sender(ADDRESS))

    def test_state_and_sender_are_persisted(self):
        store = self.open()
        store.save_sender(ADDRESS, 0x01020304)
        store.save_state(ADDRESS, STATE)
        store.save_state(ADDRESS, dict(STATE, rlc_snd=8))

        store = self.open()
        self.assertEqual(store.states(), {ADDRESS: dict(STATE, rlc_snd=8)})
        self.assertEqual(store.sender(ADDRESS), 0x01020304)

    def test_device_paired_by_its_own_teach_in_has_no_sender(self):
        self.open().save_state(ADDRESS, STATE)
        self.assertIsNone(self.open().sender(ADDRESS))

    def test_kept_in_its_own_table_of_the_device_database(self):
        db = database.open_database(self.path)
        db.insert({'name': 'enoceanmqtt/heater', 'address': ADDRESS})
        secure_store.SecureStore(db).save_state(ADDRESS, STATE)

        db = database.open_database(self.path)
        self.assertEqual(db.all(), [{'name': 'enoceanmqtt/heater', 'address': ADDRESS}])
        with open(self.path, encoding='utf-8') as file:
            self.assertEqual(json.load(file)['secure_devices'], {str(ADDRESS): {'address': ADDRESS, 'state': STATE}})

    def test_concurrent_changes_are_not_lost(self):
        # Rolling codes are saved by the EnOcean thread while the MQTT thread updates the devices
        db = database.open_database(self.path)
        store = secure_store.SecureStore(db)

        def save_states(address):
            for rlc in range(40):
                store.save_state(address, dict(STATE, rlc_snd=rlc))

        def insert_devices():
            for index in range(40):
                db.insert({'name': f'device{index}'})
        threads = [threading.Thread(target=save_states, args=(address,)) for address in (1, 2)]
        threads.append(threading.Thread(target=insert_devices))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        db = database.open_database(self.path)
        self.assertEqual(len(db.all()), 40)
        self.assertEqual(secure_store.SecureStore(db).states(),
                         {1: dict(STATE, rlc_snd=39), 2: dict(STATE, rlc_snd=39)})

    def test_database_is_private(self):
        self.open()
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        os.chmod(self.path, 0o644)
        self.open()
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)


if __name__ == '__main__':
    unittest.main()
