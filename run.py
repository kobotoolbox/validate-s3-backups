#!/usr/bin/env python3
import argparse
import http.server
import json
import os
import string
from datetime import datetime
from functools import partial
from http import HTTPStatus
from typing import Dict
from urllib.parse import parse_qs
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

import boto3


config_path = './config.json'


class BackupConfigNotFoundException(Exception):
    pass


class BackupFileNotFoundException(Exception):
    pass


class BadSizeFileException(Exception):
    pass


class ImproperlyConfiguredBackupConfigException(Exception):
    pass


class TooOldBackupException(Exception):
    pass


class MyHTTPRequestHandler(http.server.BaseHTTPRequestHandler):

    def __init__(self, config_path, *args, **kwargs):
        self._config_path = config_path
        super().__init__(*args, **kwargs)

    def do_GET(self):
        path = self.path.strip('/')

        try:
            environment, service = path.split('/')
        except ValueError:
            self._create_response(
                content='Please specify an environment and service',
                status_code=HTTPStatus.BAD_REQUEST,
            )
            return

        try:
            global_config = self._get_config()
        except FileNotFoundError:
            self._create_response(
                content='Could not find config file',
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        except json.decoder.JSONDecodeError:
            self._create_response(
                content='Could not decode config file',
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return

        # If endpoint is protected, validate token is provided.
        if token := global_config.get('token'):
            if '?' in service:
                service, qs = service.split('?')
                parsed_qs = parse_qs(qs)
                # `parse_qs()` returns an array.
                qs_token = ''.join(parsed_qs.get('token', []))
                if qs_token != token:
                    self._create_response(
                        content='Access forbidden',
                        status_code=HTTPStatus.FORBIDDEN,
                    )
                    return

        try:
            environment_config = global_config[environment]
        except KeyError:
            status_code = HTTPStatus.NOT_FOUND
            output = 'Could not find environment'
        else:
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            try:
                self._validate_backup(environment_config, service)
            except ImproperlyConfiguredBackupConfigException:
                output = 'Backup configuration is improperly configured'
            except BackupConfigNotFoundException:
                output = f'Could not find `{service}` backup settings'
                status_code = HTTPStatus.BAD_REQUEST
            except BackupFileNotFoundException:
                output = (
                    f'Could not find any files matching `{service}` backup settings'
                )
                status_code = HTTPStatus.NOT_FOUND

            except BadSizeFileException:
                output = f'Latest backup found is too small'
            except TooOldBackupException:
                output = f'Latest backup found is too old'
            else:
                # Everything is ok, let's revert the status code to 200
                status_code = HTTPStatus.OK
                output = 'Backup is OK!'

        self._create_response(content=output, status_code=status_code)

    def _convert_age_to_seconds(self, age: str) -> int:
        """
        Convert expression to corresponding time in seconds.

        Support minutes, hours, days, weeks
        E.g: "1D" -> 86400

        If no units are provided, it falls back on hours
        """
        valid_units = {
            'M': 60,
            'H': 60 * 60,
            'D': 60 * 60 * 24,
            'W': 60 * 60 * 24 * 7,
        }
        unit = str(age)[-1]
        if unit not in string.ascii_letters:
            unit = 'H'
        else:
            age = age[0:-1]

        if unit not in valid_units.keys():
            raise ImproperlyConfiguredBackupConfigException

        return int(age) * valid_units[unit]

    def _create_response(
        self,
        content: str,
        status_code: HTTPStatus,
        content_type: str = 'text/plain; charset=UTF-8',
    ):
        self.send_response(status_code)
        self.send_header('Content-Type', content_type)
        self.end_headers()
        self.wfile.write(content.encode('utf-8'))

    def _get_config(self) -> Dict:
        with open(self._config_path, 'r') as f:
            config = f.read()

        return json.loads(config)

    def _validate_backup(self, config: Dict, backup: str):
        bucket_name = config['bucket_name']
        access_key = config['access_key']
        secret = config['secret_key']
        region = config.get('region')

        try:
            backup_config = config['backups'][backup]
        except KeyError:
            raise BackupConfigNotFoundException

        # required settings
        try:
            age = backup_config['age']
        except KeyError:
            raise ImproperlyConfiguredBackupConfigException

        prefix = backup_config.get('prefix', '/')
        suffix = backup_config.get('suffix')
        min_size = backup_config.get('min_size')

        # Ensure prefix endswith trailing slash
        if not prefix.endswith('/'):
            prefix = f'{prefix}/'

        s3 = boto3.resource(
            's3',
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret,
        )
        bucket = s3.Bucket(bucket_name)
        last_backup = None
        get_last_modified = lambda o: int(o.last_modified.strftime('%s'))
        # Notice: AWS API only returns 1000 objets max.
        # See https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectsV2.html
        obj_summaries = bucket.objects.filter(Prefix=prefix)
        # Unfortunately, there is no way to get results sorted from latest to
        # oldest. We need to sort in Python. Because the API returns only 1000
        # items max, there could be a chance that the backup file we are looking
        # for, is not part of `obj_summaries` (i.e.: when more than 1000 files
        # match search criteria).
        obj_summaries = sorted(obj_summaries, key=get_last_modified, reverse=True)
        if suffix:
            for obj_summary in obj_summaries:
                if obj_summary.key.endswith(suffix):
                    last_backup = obj_summary
                    break
        elif obj_summaries:
            last_backup = list(obj_summaries)[0]

        if not last_backup:
            raise BackupFileNotFoundException

        if min_size and min_size > int(last_backup.size / 1024):
            raise BadSizeFileException

        now = datetime.now(tz=ZoneInfo('UTC'))
        diff = now - last_backup.last_modified
        if diff.total_seconds() > self._convert_age_to_seconds(age):
            raise TooOldBackupException


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-p',
        '--port',
        required=False,
        help='Listen to this port to run the HTTP server',
        default='9090',
        type=int,
    )

    parser.add_argument(
        '-c',
        '--config',
        required=False,
        help='Path to config.json',
        default=os.path.realpath(os.path.join(
            os.path.dirname(__file__),
            'config.json',
        ))
    )

    args = parser.parse_args()

    handler = partial(MyHTTPRequestHandler, config_path)
    with http.server.ThreadingHTTPServer(
            ('', args.port), handler
    ) as httpd:
        print(f'Ready for service on port {args.port}.')
        httpd.serve_forever()


if __name__ == '__main__':
    main()
