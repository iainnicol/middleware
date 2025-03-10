from datetime import time
import ipaddress
import re
from urllib.parse import urlparse
import uuid
from string import digits, ascii_uppercase, ascii_lowercase, punctuation

from zettarepl.snapshot.name import validate_snapshot_naming_schema

EMAIL_REGEX = re.compile(r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)")
RE_MAC_ADDRESS = re.compile(r"^([0-9A-Fa-f]{2}[:-]?){5}([0-9A-Fa-f]{2})$")


class Email:
    def __init__(self, empty=False):
        self.empty = empty

    def __call__(self, value):
        if value is None:
            return
        if self.empty and not value:
            return
        if not EMAIL_REGEX.match(value):
            raise ValueError("Not a valid E-Mail address")


class Exact:
    def __init__(self, value):
        self.value = value

    def __call__(self, value):
        if value != self.value:
            raise ValueError(f"Should be {self.value!r}")


class IpAddress:
    def __call__(self, value):
        try:
            ipaddress.ip_address(value)
        except ValueError:
            raise ValueError('Not a valid IP address')


class Netmask:
    def __init__(self, ipv4=True, ipv6=True, prefix_length=True):
        self.ipv4 = ipv4
        self.ipv6 = ipv6
        self.prefix_length = prefix_length

    def __call__(self, value):
        if not self.prefix_length and value.isdigit():
            raise ValueError('Please specify expanded netmask i.e 255.255.255.128.')

        ip = '1.1.1.1'
        if self.ipv4 and self.ipv6 and value.isdigit():
            if int(value) > 32:
                ip = '2001:db8::'
        elif self.ipv6 and not self.ipv4:
            # ipaddress module does not currently support ipv6 expanded netmasks
            # TODO: Convert expanded netmasks to prefix lengths for ipv6 till ipaddress adds support
            ip = '2001:db8::'

        try:
            ipaddress.ip_network(f'{ip}/{value}', strict=False)
        except ValueError:
            raise ValueError('Not a valid netmask')


class Time:
    def __call__(self, value):
        try:
            hours, minutes = value.split(':')
        except ValueError:
            raise ValueError('Time should be in 24 hour format like "18:00"')
        else:
            try:
                time(int(hours), int(minutes))
            except TypeError:
                raise ValueError('Time should be in 24 hour format like "18:00"')


class Match:
    def __init__(self, pattern, flags=0, explanation=None):
        self.pattern = pattern
        self.flags = flags
        self.explanation = explanation

        self.regex = re.compile(pattern, flags)

    def __call__(self, value):
        if value is not None and not self.regex.match(value):
            raise ValueError(self.explanation or f"Value does not match {self.pattern!r} pattern")

    def __deepcopy__(self, memo):
        return Match(self.pattern, self.flags, self.explanation)


class Hostname(Match):
    def __init__(self, explanation=None):
        super().__init__(
            r'^[a-z\.\-0-9]*[a-z0-9]$',
            flags=re.IGNORECASE,
            explanation=explanation
        )


class Or:
    def __init__(self, *validators):
        self.validators = validators

    def __call__(self, value):
        errors = []

        for validator in self.validators:
            try:
                validator(value)
            except ValueError as e:
                errors.append(str(e))
            else:
                return

        raise ValueError(" or ".join(errors))


class Range:
    def __init__(self, min=None, max=None):
        self.min = min
        self.max = max

    def __call__(self, value):
        if value is None:
            return
        if isinstance(value, str):
            value = len(value)

        error = {
            (True, True): f"between {self.min} and {self.max}",
            (False, True): f"less or equal than {self.max}",
            (True, False): f"greater or equal than {self.min}",
            (False, False): "",
        }[self.min is not None, self.max is not None]

        if self.min is not None and value < self.min:
            raise ValueError(f"Should be {error}")

        if self.max is not None and value > self.max:
            raise ValueError(f"Should be {error}")


class Port(Range):
    def __init__(self):
        super().__init__(min=1, max=65535)


class Unique:
    def __call__(self, value):
        for item in value:
            if value.count(item) > 1:
                raise ValueError(f"Duplicate values are not allowed: {item!r}")


class IpInUse:
    def __init__(self, middleware, exclude=None):
        self.middleware = middleware
        self.exclude = exclude or []

    def __call__(self, ip):
        IpAddress()(ip)

        # ip is valid
        if ip not in self.exclude:
            ips = [d['address'] for d in self.middleware.call_sync('interface.ip_in_use')]
            if ip in ips:
                raise ValueError(
                    f'{ip} is already being used by the system. Please select another IP'
                )


class MACAddr:

    SEPARATORS = [':', '-']

    def __init__(self, separator=None):
        if separator:
            assert separator in self.SEPARATORS
        self.separator = separator

    def __call__(self, value):
        if not RE_MAC_ADDRESS.match(value.lower()) or (
            self.separator and (
                self.separator not in value or ({self.separator} ^ set(self.SEPARATORS)).pop() in value.lower()
            )
        ):
            raise ValueError('Please provide a valid MAC address')


class ReplicationSnapshotNamingSchema:
    def __call__(self, value):
        validate_snapshot_naming_schema(value)


class UUID:
    def __call__(self, value):
        if value is None:
            return

        try:
            uuid.UUID(value, version=4)
        except ValueError as e:
            raise ValueError(f'Invalid UUID: {e}')


class PasswordComplexity:
    def __init__(self, required_types, required_cnt=None):
        self.required_types = required_types
        self.required_cnt = required_cnt

    def __call__(self, value):
        cnt = 0
        reqs = []
        errstr = ''

        if value and self.required_types:
            if 'ASCII_LOWER' in self.required_types:
                reqs.append('lowercase character')
                if not any(c in ascii_lowercase for c in value):
                    if self.required_cnt is None:
                        errstr += 'Must contain at least one lowercase character. '
                else:
                    cnt += 1

            if 'ASCII_UPPER' in self.required_types:
                reqs.append('uppercase character')
                if not any(c in ascii_uppercase for c in value):
                    if self.required_cnt is None:
                        errstr += 'Must contain at least one uppercase character. '
                else:
                    cnt += 1

            if 'DIGIT' in self.required_types:
                reqs.append('digits 0-9')
                if not any(c in digits for c in value):
                    if self.required_cnt is None:
                        errstr += 'Must contain at least one numeric digit (0-9). '
                else:
                    cnt += 1

            if 'SPECIAL' in self.required_types:
                reqs.append('special characters (!, $, #, %, etc.)')
                if not any(c in punctuation for c in value):
                    if self.required_cnt is None:
                        errstr += 'Must contain at least one special character (!, $, #, %, etc.). '
                else:
                    cnt += 1

        if self.required_cnt and self.required_cnt > cnt:
            raise ValueError(
                f'Must contain at least {self.required_cnt} of the following categories: {", ".join(reqs)}'
            )

        if errstr:
            raise ValueError(errstr)


def validate_schema(schema, data, additional_attrs=False, dict_kwargs=None):
    from middlewared.schema import Dict, Error
    from middlewared.service import ValidationErrors
    verrors = ValidationErrors()
    dict_kwargs = dict_kwargs or {}

    schema = Dict("attributes", *schema, additional_attrs=additional_attrs, **dict_kwargs)

    try:
        schema.clean(data)
    except Error as e:
        verrors.add(e.attribute, e.errmsg, e.errno)
    except ValidationErrors as e:
        verrors.extend(e)
    else:
        try:
            schema.validate(data)
        except ValidationErrors as e:
            verrors.extend(e)

    for verror in verrors.errors:
        if not verror.attribute.startswith("attributes."):
            raise ValueError(f"Got an invalid attribute name: {verror.attribute!r}")

        verror.attribute = verror.attribute[len("attributes."):]

    return verrors


class URL:
    def __init__(self, **kwargs):
        kwargs.setdefault("scheme", ["http", "https"])

        self.scheme = kwargs["scheme"]

    def __call__(self, value):
        try:
            result = urlparse(value)
        except Exception as e:
            raise ValueError(f'Invalid URL: {e}')

        if not result.scheme:
            raise ValueError('Invalid URL: no scheme specified')

        if self.scheme and result.scheme not in self.scheme:
            raise ValueError(f'Invalid URL: invalid scheme: {result.scheme}')

        if not result.netloc:
            raise ValueError('Invalid URL: no netloc specified')
