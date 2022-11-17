class Entity:
    """
    Holds a raw entity together with custom information from resolvers. The basic idea is that
    a user types some string in the data import input dialog, which is the raw entity value.
    Resolvers then look at that raw value and, if they know what to do with it, translate it into
    some final product (most likely a URL). For example, a user could type "doi:10.1037/rmh0000008"
    or "https://doi.org/10.1037/rmh0000008". Then, the DOI resolve would find the URL that the
    DOI points to, store it in the "URL" entity field, and store "10.1037/rmh0000008" in the
    entity "DOI" field.
    """

    def __init__(self, rawValue, user):
        self.rawValue = rawValue
        self.value = rawValue
        self.user = user
        self.dict = {}

    def raw(self):
        return self.rawValue

    def getValue(self):
        return self.value

    def setValue(self, value):
        self.value = value

    def getUser(self):
        return self.user

    def __setitem__(self, key, value):
        self.dict[key] = value

    def __getitem__(self, key):
        return self.dict[key]

    def __delitem__(self, key):
        del self.dict[key]

    def __contains__(self, key):
        return key in self.dict

    def __str__(self):
        return "Entity[%s, %s; %s]" % (self.rawValue, self.value, self.dict)
