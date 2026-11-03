# Author: Marc Alexandre K. <marcalexandrek-developer@yahoo.fr>
"""this class is a device manager for the Home Assistant overlay of enoceanmqtt"""

import logging
import os
import hashlib
import json
import copy
from threading import RLock
from tinydb import TinyDB, Query

class DeviceManager():
    '''Device Manager class, providing database methods'''

    _db = None

    def __init__(self, config):
        db_file = config.get('db_file')
        if not db_file:
            db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'device_db.json')
        self._db = TinyDB(db_file, indent=4)
        self._device_config = self._db.table('device_config')
        self._metadata = self._db.table('metadata')
        self._lock = RLock()
        self.db_add_uid()
        logging.info("Device database %s correctly read/created", db_file)

    def migrate_ini_devices(self, sensors, mqtt_prefix):
        """Import legacy INI devices once without changing the source configuration."""
        with self._lock:
            migration = Query()
            if self._metadata.contains(migration.name == 'ini_devices_migrated'):
                return

            for index, sensor in enumerate(sensors):
                device = copy.deepcopy(sensor)
                name = device.get('name', '')
                if mqtt_prefix and name.startswith(mqtt_prefix):
                    name = name[len(mqtt_prefix):]
                device['name'] = name
                digest_input = json.dumps(
                    {'index': index, 'sensor': sensor},
                    sort_keys=True,
                    separators=(',', ':')
                )
                device['id'] = 'legacy-' + hashlib.sha256(
                    digest_input.encode('utf-8')
                ).hexdigest()[:16]
                if not self._device_config.contains(Query().id == device['id']):
                    self._device_config.insert(device)

            self._metadata.insert({'name': 'ini_devices_migrated', 'value': True})

    def get_config_devices(self):
        """Return the device definitions managed by the UI."""
        with self._lock:
            return copy.deepcopy(self._device_config.all())

    def get_config_device(self, device_id):
        """Return a managed device definition by its stable ID."""
        with self._lock:
            device = self._device_config.get(Query().id == device_id)
            return copy.deepcopy(device) if device else None

    def add_config_device(self, device):
        """Persist a new UI-managed device definition."""
        with self._lock:
            for existing in self._device_config.all():
                if existing.get('name', '').casefold() == device['name'].casefold():
                    raise ValueError("A device with this name already exists")
                same_profile = (
                    existing.get('model', '').lower() == device.get('model', '').lower()
                    if device.get('model')
                    else (
                        existing.get('rorg') == device.get('rorg')
                        and existing.get('func') == device.get('func')
                        and existing.get('type') == device.get('type')
                    )
                )
                if (
                        same_profile
                        and existing.get('address') == device.get('address')
                        and existing.get('sender') == device.get('sender')
                ):
                    raise ValueError("This device profile and address already exist")
            stored_device = copy.deepcopy(device)
            self._device_config.insert(stored_device)
            return stored_device

    def remove_config_device(self, device_id):
        """Remove a UI-managed device definition."""
        with self._lock:
            removed = self._device_config.remove(Query().id == device_id)
            return bool(removed)

    def db_add_uid(self):
        '''Update old databases without UID'''
        with self._lock:
            for device in self.db_get_devices():
                if not device.get('uid'):
                    eep = format((device['rorg']<<16)+(device['func']<<8)+device['type'], '06X')
                    device['uid'] = eep+"_"+format(device['address'],'08X')+"_NONE"
                    dev = Query()
                    self._db.update(device, dev.address == device['address'])

    def db_search_device_by_address(self, address):
        '''Search device in the database using the device address'''
        with self._lock:
            dev = Query()
            return self._db.contains(dev.address == address)

    def db_search_device_by_name(self, name):
        '''Search device in the database using the device name'''
        with self._lock:
            dev = Query()
            return self._db.contains(dev.name == name)

    def db_search_device_by_field(self, field_name, field):
        '''Search device in the database using a device field'''
        with self._lock:
            dev = Query()
            if type(field) is list:
                return self._db.contains(dev[field_name].all([field]))
            return self._db.contains(dev[field_name] == field)

    def db_get_device_by_address(self, address):
        '''Get device from the database using the device address'''
        with self._lock:
            dev = Query()
            return self._db.get(dev.address == address)

    def db_get_device_by_name(self, name):
        '''Get device from the database using the device name'''
        with self._lock:
            dev = Query()
            return self._db.get(dev.name == name)

    def db_get_device_by_field(self, field_name, field):
        '''Get device from the database using a device field'''
        with self._lock:
            dev = Query()
            if type(field) is list:
                return self._db.get(dev[field_name].all([field]))
            return self._db.get(dev[field_name] == field)

    def db_get_devices(self):
        '''Get all devices from the database'''
        with self._lock:
            return self._db.all()

    def db_list_from_fields(self, field):
        '''Get a list of field values for all devices in the database'''
        with self._lock:
            field_list = []
            for sensor in self._db.all():
                field_list.append(sensor[field])
            return field_list

    def db_add_device(self, sensor, uid, attr_name = None, attr = None):
        '''Add new device to the database'''
        with self._lock:
            if not self.db_search_device_by_address(sensor['address']):
                sensor_db = {}
                sensor_db['uid']     = uid
                sensor_db['address'] = sensor['address']
                sensor_db['name']    = sensor['name']
                sensor_db['rorg']    = sensor['rorg']
                sensor_db['func']    = sensor['func']
                sensor_db['type']    = sensor['type']
                if attr is not None:
                    sensor_db[attr_name]= attr
                self._db.insert(sensor_db)
                return True
            return False

    def db_update_device(self, sensor, uid, attr_name = None, attr = None):
        '''Update device on the database'''
        with self._lock:
            if self.db_search_device_by_field('uid', sensor['uid']):
                sensor_db = {}
                sensor_db['name'] = sensor['name']
                if attr is not None:
                    sensor_db[attr_name] = attr
                dev = Query()
                self._db.update(sensor_db, dev.uid == uid)
                return True
            return False

    def db_upsert_device(self, sensor, uid, attr_name = None, attr = None):
        '''Update or add device to the database'''
        with self._lock:
            sensor_db = {}
            sensor_db['uid'] = uid
            if not sensor.get('model'):
               sensor_db['address'] = sensor['address']
               sensor_db['name']    = sensor['name']
               sensor_db['rorg']    = sensor['rorg']
               sensor_db['func']    = sensor['func']
               sensor_db['type']    = sensor['type']
            else:
               sensor_db['address'] = sensor['address']
               sensor_db['name']    = sensor['name'][:-3]
               sensor_db['model']   = sensor['model']

            if attr is not None:
                sensor_db[attr_name] = attr
            dev = Query()
            self._db.upsert(sensor_db, dev.uid == uid)

    def db_remove_device_by_address(self, address):
        '''Remove device from the database using device address'''
        with self._lock:
            if self.db_search_device_by_address(address):
                dev = Query()
                self._db.remove(dev.address == address)
                return True
            return False

    def db_remove_device_by_field(self, field_name, field):
        '''Remove device from the database using a device field'''
        with self._lock:
            sensor = self.db_get_device_by_field(field_name, field)
            if sensor:
                dev = Query()
                # Remove the sensor from the database
                if type(field) is list:
                    ids = self._db.remove(dev[field_name].all([field]))
                else:
                    ids = self._db.remove(dev[field_name] == field)

                if ids:
                    logging.debug("Delete request for sensor %s (UID %s): DONE",sensor['name'],sensor['uid'])
                    return True
                else:
                    logging.debug("Delete request for sensor %s (UID %s): ERROR",sensor['name'],sensor['uid'])
                    return False
            return False
