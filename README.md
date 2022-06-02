## Summary
 
This script checks whether the latest backup file stored on S3 is valid or not.
The validation check is on backup age but can be also on the size.

## Requirements

- Python 3.8+
- pipenv

## Installation

Using `pipenv install`


## Usage

#### To launch the script and the HTTP server

`pipenv run python run.py`

1. Options

`run.py` accepts two options:

- `--port` The port the HTTP server should listen to. Default is `9090`
- `--config` The path of the configuration file the script should look for. Default is `./config.json`


#### To access the result of the backup check

With a browser, go to `http://localhost:9090/<environment>/<backup>/`

If access is protected, add `?token=<token>` at the end the URL where `<token>` is the token provided in the `token` property of the config file.


## Configuration file

A configuration file sample is provided and can be used as a starter.

The only required setting is `age`. By default, the value is in hours. But it understands minutes, hours, days and weeks when the unit is specified. For example: `90M` (90 minutes),`3H` (3 hours), `2D` (2 days) or `3W` (3 weeks).

The three settings below are optional, but it is recommended to set them to narrow down the search of the correct backup file on the S3 bucket:

- `prefix` The beginning of the backup file path. Default is `/` (the whole bucket).
- `suffix` The end of the backup file. It can be the extension, but can be something longer. Default is `None`.
- `min_size` The minimum size in kB the backup file should weight to be considered as a valid backup. Default is `None`.

## Secure the endpoint

A token can be used to secure the endpoint. In a configuration file, just add `token` property at the root level on the JSON.
From the browser, go to `http://localhost:9090/<environment>/<backup>/?token=<token>`.

_Notes: if you try to access the endpoint with a token but no token are set in the config, it will raise a 500 error._
