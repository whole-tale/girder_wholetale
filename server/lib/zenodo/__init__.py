class ZenodoNotATaleError(Exception):
    """Exception raised if Zenodo record is not a Tale.

    Attributes:
        record - JSON structure describing the Zenodo record
        message - explanation of the error

    """

    def __init__(self, record, message="Zenodo record ({}) is not a Tale"):
        self.record = record
        self.message = message.format(record["links"]["html"])
        super().__init__(self.message)
