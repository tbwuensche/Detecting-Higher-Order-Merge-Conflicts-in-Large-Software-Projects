import subprocess as sp
import lxml.etree as etree
from scipy.sparse import lil_matrix, save_npz
import ujson
import numpy as np
from tqdm import tqdm
import constants
import save_and_load as io


def find_includes(xpath_find_includes, unit, properties):
    includes = xpath_find_includes(unit)
    for included_file in includes:
        included_file = included_file.split("\"")
        if len(included_file) == 3:
            properties[constants.INCLUDES].add(included_file[1])


# Find the name of a given named unit
def get_named_unit_name(xpath_named_unit_name_query, unit):
    if unit.tag == constants.TAGS["block"]:
        # When parsed, srcml separates the name and content of macros.
        # The xpath query finds the contents, the name is contained in the precious unit.
        macro = unit.getprevious()
        return etree.tostring(macro, method="text").decode("utf-8").strip(), set({})
    names = xpath_named_unit_name_query(unit)
    name = ""
    calls = set([])
    name_found = False
    if not names:
        return name, calls
    else:
        name_unit = names[0]
        units = list(name_unit)

        if (len(units) == 0 or (len(units) == 1 and units[0].tag == constants.TAGS["position"])) and name_unit.tag == \
                constants.TAGS["name"]:
            name = name_unit.text
            name_found = True
        while not name_found:
            if len(units) == 1 and units[0].tag == constants.TAGS["name"]:
                name = units[0].text
                if not name or not name.strip():
                    units = list(units[0])
                else:
                    name_found = True
            elif len(units) >= 3 and units[1].tag == constants.TAGS["operator"] and (
                    units[1].text == "::" or units[1].text == "->" or units[1].text == "."):
                calls.add(units[0].text)
                units = units[2:]
            elif len(units) >= 2 and (
                    units[1].tag == constants.TAGS["argument_list"] or units[1].tag == constants.TAGS["index"]):
                calls.update(units[1].xpath(".//src:name/text()", namespaces=constants.ns))
                units.pop(1)
            elif len(units) >= 1 and (
                    units[0].tag == constants.TAGS["operator"] or units[0].tag == constants.TAGS["modifier"]):
                units = units[1:]
            elif len(units) >= 1 and units[0].tag == constants.TAGS["typename"]:
                # typenames are used locally and need not be considered
                return "", set([])
            elif any(unit.tag == constants.TAGS["comment"] for unit in units):
                for i in range(len(units)):
                    if units[i].tag == constants.TAGS["comment"]:
                        units.pop(i)
                        break
            else:
                return name, calls
        return name, calls


# extract named units from srcml
def find_named_units(xpath_find_named_units, xpath_find_calls, xpath_named_unit_name_query, element, properties):
    named_units = xpath_find_named_units(element)

    for unit in named_units:
        name, calls = get_named_unit_name(xpath_named_unit_name_query, unit)
        if name:
            properties[constants.CALLS_NAIVE].setdefault(name, {name}).update(calls, xpath_find_calls(unit))


# parse the entire source directory.
# If changed_files is passed, all other files will be skipped
def parse_source_code(src_path, changed_files=None):
    scanned_paths = set([])
    xpath_find_includes = etree.XPath(".//cpp:include/cpp:file/text()", namespaces=constants.ns)
    xpath_find_named_units = etree.XPath(".//*[({0})]".format(constants.NAMED_UNIT_QUERY), namespaces=constants.ns)
    xpath_find_calls = etree.XPath(".//*[{0}]//src:name/text()".format(constants.CALLING_UNIT_QUERY), namespaces=constants.ns)
    xpath_named_unit_name_query = etree.XPath(constants.NAMED_UNIT_NAME_QUERY, namespaces=constants.ns)
    parser = etree.XMLParser(huge_tree=True)

    paths = set([])

    for file_ext in tqdm(constants.VALID_FILE_EXTENSIONS, desc="finding files"):
        paths.update(src_path.rglob("*.{}".format(file_ext)))

    for path in tqdm(paths, desc="parsing files"):
        rel_path = str(path.relative_to(src_path).as_posix())
        jsonpath = constants.DUMP_FOLDER_JSON / (rel_path + ".json")

        scanned_paths.add(rel_path)
        if changed_files is None or rel_path in changed_files or not jsonpath.exists():
            srcml = run_srcml_one_file(src_path, path)
            if srcml:
                properties = {constants.INCLUDES: {rel_path}, constants.CALLS_NAIVE: {}}
                element = etree.fromstring(srcml, parser)
                find_includes(xpath_find_includes, element, properties)
                find_named_units(xpath_find_named_units, xpath_find_calls, xpath_named_unit_name_query, element,
                                 properties)

                io.save_preprocessed_file(rel_path, properties)

    io.save_paths(scanned_paths)


def build_call_graph():
    paths = io.load_paths()
    named_unit_dict = {}
    includes_dict = {}

    id_counter = 0
    named_unit_to_id = {}
    for path in tqdm(paths, desc="assigning IDs to named units: "):
        properties = io.load_preprocessed_file(path)
        if properties:
            named_unit_dict[path] = set(properties[constants.CALLS_NAIVE].keys())
            includes_dict[path] = properties[constants.INCLUDES]
            for named_unit in properties[constants.CALLS_NAIVE].keys():
                named_unit_to_id[(path, named_unit)] = id_counter
                id_counter += 1

    call_graph = lil_matrix((id_counter, id_counter), dtype=np.int8)
    called_by_graph = lil_matrix((id_counter, id_counter), dtype=np.int8)

    for including_file in tqdm(paths, desc="building callgraph: "):
        scanned_files = set([])
        including_file_dict = io.load_preprocessed_file(including_file)
        if including_file_dict:
            included_files = set([(include, 0) for include in including_file_dict[constants.INCLUDES]])
            while included_files:
                included_file, include_level = included_files.pop()
                if include_level < constants.MAX_TRANSITIVE_INCLUDE_LEVEL:
                    scanned_files.add(included_file)
                    included_files = included_files.union([(include, include_level + 1) for include in
                                                           includes_dict.get(included_file, set([])) - scanned_files])
                calling_named_units = named_unit_dict[including_file]
                callable_units = named_unit_dict.get(included_file, set([]))
                for calling_named_unit in calling_named_units:
                    calls = including_file_dict[constants.CALLS_NAIVE].get(calling_named_unit, set([]))
                    for callable_unit in callable_units:
                        if callable_unit in calls:
                            from_id = named_unit_to_id[(including_file, calling_named_unit)]
                            to_id = named_unit_to_id[(included_file, callable_unit)]
                            call_graph[from_id, to_id] = 1
                            called_by_graph[to_id, from_id] = 1

    call_graph = call_graph.tocsr()
    called_by_graph = called_by_graph.tocsr()

    id_to_named_unit = {}
    for k, v in named_unit_to_id.items():
        id_to_named_unit[v] = (k[0], k[1])

    print("save call_graph.npz...")
    save_npz("call_graph.npz", call_graph)
    print("save called_by_graph.npz...")
    save_npz("called_by_graph.npz", called_by_graph)

    print("save id_to_named_unit.json...")
    with open("id_to_named_unit.json", 'w') as fp:
        ujson.dump(id_to_named_unit, fp)


def run_srcml_one_file(src_path, path):
    query = ["srcml", "-X", "--register-ext", "{}=C++".format(path.suffix[1:])]
    output = ""
    counter = 0
    while not output:
        try:
            output = sp.check_output([*query, str((src_path/path).resolve())], timeout=60)
            return output
        except sp.CalledProcessError:
            #retry, srcml occasionally crashes
            counter += 1
            if counter > 3:
                print("multiple crashes occured at {}".format(path))
                raise
        except sp.TimeoutExpired:
            tqdm.write("timeout while parsing {}".format(str((src_path/path).resolve())))
            return None
