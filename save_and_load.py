import constants
import ujson


def save_last_scanned_revision(revision):
    path = constants.LAST_SCANNED_REVISION
    with path.open("w") as fp:
        fp.write(revision)


def load_last_scanned_revision():
    path = constants.LAST_SCANNED_REVISION
    if path.exists():
        with path.open("r") as fp:
            return fp.read()
    else:
        return None


def save_preprocessed_file(path, properties):
    properties[constants.INCLUDES] = list(properties[constants.INCLUDES])
    for unit, calls in properties[constants.CALLS_NAIVE].items():
        properties[constants.CALLS_NAIVE][unit] = list(calls)
    path += ".json"
    filepath = constants.DUMP_FOLDER_JSON / path
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w") as fp:
        ujson.dump(properties, fp)


def load_preprocessed_file(path):
    path += ".json"
    filepath = constants.DUMP_FOLDER_JSON / path
    if filepath.exists():
        with filepath.open("r") as fp:
            properties = ujson.load(fp)

        properties[constants.INCLUDES] = set(properties[constants.INCLUDES])
        for unit, calls in properties[constants.CALLS_NAIVE].items():
            properties[constants.CALLS_NAIVE][unit] = set(calls)
        return properties
    else:
        return None


def save_paths(paths):
    with open(constants.DUMP_PATH_LIST, 'w') as fp:
        ujson.dump(list(paths), fp)


def load_paths():
    if constants.DUMP_PATH_LIST.exists():
        with open(constants.DUMP_PATH_LIST, 'r') as fp:
            paths = ujson.load(fp)
        return set(paths)
    else:
        return set([])


def load_id_dicts():
    id_to_named_unit = {}
    named_unit_to_id = {}

    with open("id_to_named_unit.json", "r") as file:
        id_to_named_unit_from_file = ujson.load(file)
        for k, v in id_to_named_unit_from_file.items():
            id_to_named_unit[int(k)] = (v[0], v[1])
            named_unit_to_id[(v[0], v[1])] = int(k)

    return id_to_named_unit, named_unit_to_id
