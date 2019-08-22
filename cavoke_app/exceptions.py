class BaseCavokeError(Exception):
    # Base exception
    pass


class BaseCavokeWarning(Warning):
    # Base warning
    pass


class GameTypeDoesNotExistError(BaseCavokeError):
    # Raised when no game type was found for the request
    pass


class UrlInvalidError(BaseCavokeError):
    # Raised when provided url is invalid
    pass


class ProcessTooSlowError(BaseCavokeError):
    # Raised when cavoke game takes too long to process
    pass


class TooManyGameTypesWarning(BaseCavokeWarning):
    # Raised when user has authored too many games
    pass


class TooManyGameSessionsWarning(BaseCavokeWarning):
    # Raised when user has too many game sessions
    pass
