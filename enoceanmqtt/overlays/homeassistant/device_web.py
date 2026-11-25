"""HTTP API and web UI for managing Home Assistant overlay devices."""

import json
import logging
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


_NAME_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_. -]{0,63}$')
_INGRESS_PATH_PATTERN = re.compile(r'^/[A-Za-z0-9/_-]*$')


class DeviceWebServer:
    """Serve the device management page and its same-origin JSON API."""

    def __init__(self, device_manager, mapping, on_change, host, port):
        self._device_manager = device_manager
        self._mapping = mapping
        self._on_change = on_change
        self._host = host
        self._port = port
        self._server = None
        self._thread = None
        self._static_dir = Path(__file__).parent / 'static'
        self._options = self._build_options(mapping)

    def start(self):
        owner = self

        class RequestHandler(BaseHTTPRequestHandler):
            def log_message(self, format_string, *args):
                logging.info("Device UI: " + format_string, *args)

            def _ingress_prefix(self):
                prefix = self.headers.get('X-Ingress-Path', '').rstrip('/')
                if prefix and _INGRESS_PATH_PATTERN.fullmatch(prefix):
                    return prefix
                return ''

            def _route_path(self):
                path = urlsplit(self.path).path
                prefix = self._ingress_prefix()
                if prefix and path == prefix:
                    return '/'
                if prefix and path.startswith(prefix + '/'):
                    return path[len(prefix):]
                return path

            def _send_json(self, status, value):
                body = json.dumps(value).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)

            def _send_file(self, file_name, content_type, base_href=None):
                try:
                    body = (owner._static_dir / file_name).read_bytes()
                except OSError:
                    logging.exception("Could not read device UI asset %s", file_name)
                    self._send_json(500, {'error': 'The web interface could not be loaded.'})
                    return
                if base_href is not None:
                    html = body.decode('utf-8').replace(
                        '<base href="/">',
                        '<base href="' + base_href + '/">'
                    )
                    body = html.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)

            def _device_list(self):
                devices = []
                for device in owner._device_manager.get_config_devices():
                    profile = device.get('model')
                    if profile:
                        device_type = 'model'
                    else:
                        device_type = 'eep'
                        profile = '{:02X}-{:02X}-{:02X}'.format(
                            int(device['rorg']),
                            int(device['func']),
                            int(device['type'])
                        )
                    devices.append({
                        'id': device['id'],
                        'name': device['name'],
                        'address': '{:08X}'.format(int(device['address'])),
                        'type': device_type,
                        'profile': profile,
                        'virtual': str(device.get('virtual', '0')) == '1',
                        'sender': (
                            '{:08X}'.format(int(device['sender']))
                            if device.get('sender') is not None else ''
                        ),
                        'security': owner._security_for_device(device)
                    })
                return devices

            def do_GET(self):
                path = self._route_path()
                if path == '/':
                    prefix = self._ingress_prefix()
                    self._send_file('index.html', 'text/html; charset=utf-8', prefix)
                elif path == '/app.css':
                    self._send_file('app.css', 'text/css; charset=utf-8')
                elif path == '/app.js':
                    self._send_file('app.js', 'text/javascript; charset=utf-8')
                elif path == '/api/devices':
                    self._send_json(200, {'devices': self._device_list()})
                elif path == '/api/options':
                    self._send_json(200, owner._options)
                else:
                    self._send_json(404, {'error': 'Not found.'})

            def do_POST(self):
                if self._route_path() != '/api/devices':
                    self._send_json(404, {'error': 'Not found.'})
                    return
                try:
                    content_length = int(self.headers.get('Content-Length', '0'))
                except ValueError:
                    self._send_json(400, {'error': 'Invalid request size.'})
                    return
                if content_length <= 0 or content_length > 16384:
                    self._send_json(413, {'error': 'The device details are too large.'})
                    return
                try:
                    payload = json.loads(self.rfile.read(content_length))
                    device = owner._validate_device(payload)
                    stored_device = owner._device_manager.add_config_device(device)
                    try:
                        owner._on_change('add', stored_device)
                    except Exception:
                        owner._device_manager.remove_config_device(stored_device['id'])
                        raise
                except ValueError as error:
                    self._send_json(400, {'error': str(error)})
                    return
                except RuntimeError as error:
                    self._send_json(503, {'error': str(error)})
                    return
                except TimeoutError as error:
                    self._send_json(503, {'error': str(error)})
                    return
                except Exception:
                    logging.exception("Could not add device through the web UI")
                    self._send_json(500, {'error': 'The device could not be added.'})
                    return
                self._send_json(201, {'device': next(
                    item for item in self._device_list()
                    if item['id'] == stored_device['id']
                )})

            def do_PUT(self):
                path = self._route_path()
                prefix = '/api/devices/'
                if not path.startswith(prefix):
                    self._send_json(404, {'error': 'Not found.'})
                    return
                device_id = unquote(path[len(prefix):])
                if not device_id or '/' in device_id:
                    self._send_json(404, {'error': 'Device not found.'})
                    return
                previous_device = owner._device_manager.get_config_device(device_id)
                if previous_device is None:
                    self._send_json(404, {'error': 'Device not found.'})
                    return
                try:
                    content_length = int(self.headers.get('Content-Length', '0'))
                except ValueError:
                    self._send_json(400, {'error': 'Invalid request size.'})
                    return
                if content_length <= 0 or content_length > 16384:
                    self._send_json(413, {'error': 'The device details are too large.'})
                    return
                try:
                    payload = json.loads(self.rfile.read(content_length))
                    device = owner._validate_device(payload, device_id=device_id)
                    stored_device = owner._device_manager.update_config_device(
                        device_id,
                        device
                    )
                    try:
                        owner._on_change('update', stored_device, previous_device)
                    except Exception:
                        owner._device_manager.update_config_device(
                            device_id,
                            previous_device
                        )
                        try:
                            owner._on_change('update', previous_device, stored_device)
                        except Exception:
                            logging.exception("Could not restore device after a failed update")
                        raise
                except ValueError as error:
                    self._send_json(400, {'error': str(error)})
                    return
                except (RuntimeError, TimeoutError) as error:
                    self._send_json(503, {'error': str(error)})
                    return
                except Exception:
                    logging.exception("Could not update device through the web UI")
                    self._send_json(500, {'error': 'The device could not be updated.'})
                    return
                self._send_json(200, {'device': next(
                    item for item in self._device_list()
                    if item['id'] == device_id
                )})

            def do_DELETE(self):
                path = self._route_path()
                prefix = '/api/devices/'
                if not path.startswith(prefix):
                    self._send_json(404, {'error': 'Not found.'})
                    return
                device_id = unquote(path[len(prefix):])
                if not device_id or '/' in device_id:
                    self._send_json(404, {'error': 'Device not found.'})
                    return
                device = owner._device_manager.get_config_device(device_id)
                if device is None:
                    self._send_json(404, {'error': 'Device not found.'})
                    return
                try:
                    owner._on_change('delete', device)
                    owner._device_manager.remove_config_device(device_id)
                except (RuntimeError, TimeoutError) as error:
                    self._send_json(503, {'error': str(error)})
                    return
                except Exception:
                    logging.exception("Could not delete device through the web UI")
                    self._send_json(500, {'error': 'The device could not be deleted.'})
                    return
                self._send_json(200, {'deleted': device_id})

        self._server = ThreadingHTTPServer((self._host, self._port), RequestHandler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name='enoceanmqtt-device-web',
            daemon=True
        )
        self._thread.start()
        logging.info("Device management UI listening on http://%s:%d", *self._server.server_address)

    def stop(self):
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None

    @classmethod
    def _build_options(cls, mapping):
        eeps = []
        for rorg, functions in mapping.items():
            if not isinstance(rorg, int) or not isinstance(functions, dict):
                continue
            for func, types in functions.items():
                if not isinstance(func, int) or not isinstance(types, dict):
                    continue
                for type_, profile in types.items():
                    if not isinstance(type_, int) or not isinstance(profile, dict):
                        continue
                    if any(key in profile for key in ('entities', 'virtual', 'device_config')):
                        code = '{:02X}-{:02X}-{:02X}'.format(rorg, func, type_)
                        eeps.append({
                            'value': code,
                            'label': code,
                            'security': cls._mapping_security(
                                profile.get('device_config', {})
                            )
                        })

        models = []
        for manufacturer, model_map in mapping.items():
            if not isinstance(manufacturer, str) or not isinstance(model_map, dict):
                continue
            for model, profile in model_map.items():
                if not isinstance(profile, dict) or not profile.get('device_config'):
                    continue
                reference = manufacturer.lower() + '/' + str(model).lower()
                models.append({
                    'value': reference,
                    'label': manufacturer.replace('_', ' ').title() + ' / ' + str(model),
                    'security': cls._mapping_security(profile.get('device_config', []))
                })
        return {
            'eeps': sorted(eeps, key=lambda option: option['value']),
            'models': sorted(models, key=lambda option: option['label'].lower())
        }

    @staticmethod
    def _mapping_security(device_config):
        configs = device_config if isinstance(device_config, list) else [device_config]
        security = {}
        for config in configs:
            if not isinstance(config, dict):
                continue
            for field in ('secure_teachin_telegrams', 'secure_teachin_bidirectional'):
                if field in config and field not in security:
                    security[field] = config[field]
        security['secure_teachin_telegrams'] = int(
            security.get('secure_teachin_telegrams', 2)
        )
        security['secure_teachin_bidirectional'] = (
            str(security.get('secure_teachin_bidirectional', False)).lower()
            in ('true', '1', 'yes')
        )
        return security

    def _security_for_device(self, device):
        if device.get('model'):
            profile = device['model'].lower()
            options = self._options['models']
        else:
            profile = '{:02X}-{:02X}-{:02X}'.format(
                int(device['rorg']),
                int(device['func']),
                int(device['type'])
            )
            options = self._options['eeps']
        option = next((item for item in options if item['value'] == profile), None)
        if option is None or option.get('security') is None:
            return None
        security = dict(option['security'])
        if 'secure_teachin_telegrams' in device:
            security['secure_teachin_telegrams'] = int(
                device['secure_teachin_telegrams']
            )
        if 'secure_teachin_bidirectional' in device:
            security['secure_teachin_bidirectional'] = (
                str(device['secure_teachin_bidirectional']).lower()
                in ('true', '1', 'yes')
            )
        return security

    def _validate_device(self, payload, device_id=None):
        if not isinstance(payload, dict):
            raise ValueError("Provide the device details as an object.")
        name = payload.get('name')
        if not isinstance(name, str) or not _NAME_PATTERN.fullmatch(name.strip()):
            raise ValueError("Use a device name of 1–64 letters, numbers, spaces, dots, dashes or underscores.")
        name = name.strip()

        address = self._parse_hex_value(
            payload.get('address'),
            'address',
            required_digits=8,
            allow_prefix=False
        )
        if address < 0 or address > 0xFFFFFFFF:
            raise ValueError("The address must fit in 32 bits.")

        device_type = payload.get('type')
        profile = payload.get('profile')
        if device_type not in ('eep', 'model') or not isinstance(profile, str):
            raise ValueError("Choose an EEP or model from the supported list.")

        device = {
            'id': device_id or uuid.uuid4().hex,
            'name': name,
            'address': address,
            'virtual': '1' if payload.get('virtual') is True else '0'
        }
        if device_type == 'eep':
            options = self._options['eeps']
            option_values = {option['value'] for option in options}
            if profile not in option_values:
                raise ValueError("Choose a supported EEP from the list.")
            profile_option = next(option for option in options if option['value'] == profile)
            device['rorg'], device['func'], device['type'] = (
                int(part, 16) for part in profile.split('-')
            )
        else:
            options = self._options['models']
            option_values = {option['value'] for option in options}
            if profile not in option_values:
                raise ValueError("Choose a supported model from the list.")
            profile_option = next(option for option in options if option['value'] == profile)
            device['model'] = profile

        if profile_option.get('security') is not None:
            mapped_security = profile_option['security']
            telegrams = payload.get(
                'secure_teachin_telegrams',
                mapped_security.get('secure_teachin_telegrams', 2)
            )
            try:
                telegrams = int(telegrams)
            except (TypeError, ValueError) as error:
                raise ValueError("Secure teach-in telegrams must be 2 or 3.") from error
            if telegrams not in (2, 3):
                raise ValueError("Secure teach-in telegrams must be 2 or 3.")
            bidirectional = payload.get(
                'secure_teachin_bidirectional',
                mapped_security.get('secure_teachin_bidirectional', False)
            )
            if not isinstance(bidirectional, bool):
                raise ValueError("Choose whether secure teach-in is bidirectional.")
            device['secure_teachin_telegrams'] = telegrams
            device['secure_teachin_bidirectional'] = bidirectional

        sender = payload.get('sender', '')
        if sender:
            device['sender'] = self._parse_hex_value(sender, 'sender')
        elif device['virtual'] == '1':
            raise ValueError("A sender ID is required for virtual devices.")
        return device

    @staticmethod
    def _parse_hex_value(value, field_name, required_digits=None, allow_prefix=True):
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise ValueError("Enter a hexadecimal {}.".format(field_name))
        if required_digits and not isinstance(value, str):
            raise ValueError(
                "The {} must contain exactly {} hexadecimal digits (4 bytes).".format(
                    field_name,
                    required_digits
                )
            )
        try:
            if isinstance(value, str):
                digits = value.strip()
                if allow_prefix and digits.lower().startswith('0x'):
                    digits = digits[2:]
                digit_count = str(required_digits) if required_digits else '1,8'
                if not re.fullmatch(r'[0-9a-fA-F]{' + digit_count + '}', digits):
                    raise ValueError
                parsed = int(digits, 16)
            else:
                parsed = value
        except ValueError as error:
            if required_digits:
                raise ValueError(
                    "The {} must contain exactly {} hexadecimal digits (4 bytes).".format(
                        field_name,
                        required_digits
                    )
                ) from error
            raise ValueError("Enter a valid hexadecimal {}.".format(field_name)) from error
        if parsed < 0 or parsed > 0xFFFFFFFF:
            raise ValueError("The {} must fit in 32 bits.".format(field_name))
        return parsed
