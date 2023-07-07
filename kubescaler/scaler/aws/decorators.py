# Copyright 2023 Lawrence Livermore National Security, LLC and other
# HPCIC DevTools Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (MIT)

from functools import partial, update_wrapper

from botocore.exceptions import ClientError

from kubescaler.logger import logger


class refresh_session:
    """
    Given a ClientError, refresh the session
    """

    def __init__(self, func):
        update_wrapper(self, func)
        self.func = func

    def __get__(self, obj, objtype):
        return partial(self.__call__, obj)

    def __call__(self, cls, *args, **kwargs):
        name = self.func.__name__
        try:
            res = self.func(cls, *args, **kwargs)
        # This ensures we just retry once
        except ClientError as e:
            logger.warning(
                f"ClientError triggered for function {name}, attempting to refresh session: {e}"
            )
            cls.refresh_clients()
            res = self.func(cls, *args, **kwargs)
        return res
