"""
Class representing the available licenses. For specific providers, methods that filter
the list of global licences can be added.
"""


class WholeTaleLicense:
    def __init__(self):
        super().__init__()

        # List of all the licenses that are supported.
        self.licenses = [
            {
                "name": "Creative Commons Zero v1.0 Universal",
                "spdx": "CC0-1.0",
                "text": "This work is dedicated to the public domain under the Creative Commons "
                "Universal 1.0 Public Domain Dedication. To view a copy of this "
                "dedication, visit https://creativecommons.org/publicdomain/zero/1.0/.",
            },
            {
                "name": "Creative Commons Attribution 4.0 International",
                "spdx": "CC-BY-4.0",
                "text": "This work is licensed under the Creative Commons Attribution 4.0 "
                "International License. To view a copy of this license, "
                "visit http://creativecommons.org/licenses/by/4.0/.",
            },
        ]

    def supported_licenses(self):
        """
        Returns all of the supported licenses
        :return: List of default licenses
        """
        return self.licenses

    def supported_spdxes(self):
        """
        Returns the SPDX of the supported licenses
        :return: A list of SPDXs for each supported license
        """
        return {tale_license["spdx"] for tale_license in self.licenses}

    @staticmethod
    def default_spdx():
        """
        Returns the default Tale spdx
        :return: The spdx that is applied to a Tale on default
        """
        return "CC-BY-4.0"

    def license_from_spdx(self, spdx):
        """Return a license given its spdx"""
        return next((_ for _ in self.licenses if _["spdx"] == spdx), None)
