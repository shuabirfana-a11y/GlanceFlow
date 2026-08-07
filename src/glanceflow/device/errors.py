class DeviceError(RuntimeError):
    """Base error at the untrusted device boundary."""


class DeviceUnavailableError(DeviceError):
    pass


class InvalidDevicePayloadError(DeviceError):
    pass


class DuplicateDeviceMessageError(DeviceError):
    pass


class DeviceSequenceError(DeviceError):
    pass


class StaleDeviceMessageError(DeviceError):
    pass
