from abc import ABCMeta
from typing import Any, Dict


class SingletonMeta(ABCMeta):
    """
    A Metaclass that ensures a class has only one instance.
    It inherits from ABCMeta to support abstract methods.
    """

    _instances: Dict[type, Any] = {}

    def __call__(cls, *args, **kwargs):
        """
        Overrides the default call behavior to control instantiation.
        """
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


class Singleton(metaclass=SingletonMeta):
    """
    An abstract base class for Singletons.
    Inherit from this class to make class a Singleton.
    """

    def __init__(self):
        pass
