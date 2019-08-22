import uuid


def randomUUID():
    return uuid.uuid4().__str__().replace('-', '')
