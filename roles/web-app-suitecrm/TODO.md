# TODO

- `logs/prod/prod.log` in the `suitecrm_data` volume still holds the Redis password from the `SessionHandler::read(): open(tcp://...)` warnings written before the session handler override in `files/session.yaml`. Options: truncate the file once after the password was rotated, or let a log rotation drop it.
