from pathlib import Path
import sys
import time
import subprocess as sp
import lxml.etree as etree
from scipy.sparse import csgraph, load_npz
import ujson
import numpy as np
import precompute
import itertools
from tqdm import tqdm
import constants
import save_and_load as io
from operator import itemgetter
import re


def parse_input():
    # expect input in the format PATH_TO_SOURCE_FOLDER CURRENT_MASTER_REVISION BRANCH_REVISION-REQUESTED_MASTER_REVISION
    src_path = Path(sys.argv[1]).resolve()
    master = sys.argv[2]
    branches = [branch.split(constants.BRANCH_SEPARATOR) for branch in sys.argv[3:]]
    return src_path, master, branches


def get_changed_files(src_path):
    last_scanned = io.load_last_scanned_revision()
    if last_scanned is None:
        return None
    changed_files = set([])
    output = sp.check_output([*constants.GIT_CALL, str(src_path.resolve()), "diff", "--name-only", last_scanned])
    output = str(output, 'utf-8')
    output = output.split("\n")

    for rel_path in output:
        abs_path = src_path / rel_path
        if abs_path.exists and abs_path.suffix[1:] in constants.VALID_FILE_EXTENSIONS:
            changed_files.add(str(abs_path.relative_to(src_path).as_posix()))

    return changed_files


def parse_diff(src_path, master, branch):
    changed_files = set([])
    output = sp.check_output(
        [*constants.GIT_CALL, str(src_path.resolve()), "diff", "--name-only", master + ".." + branch])
    output = str(output, 'utf-8')
    output = output.split("\n")

    for rel_path in output:
        abs_path = src_path / rel_path
        if abs_path.exists and abs_path.suffix[1:] in constants.VALID_FILE_EXTENSIONS:
            changed_files.add(str(abs_path.relative_to(src_path).as_posix()))

    output = sp.check_output([*constants.GIT_CALL, str(src_path.resolve()), "diff", "-U0", master + "..." + branch])
    output = re.findall(b"(@@)(.*)(@@)|(\+\+\+)(.*)\n", output)
    output = ["".join([str(match, 'utf-8') for match in group]) for group in output]

    change_intervals = {}
    last_file = None

    for line in output:
        if line.startswith("+++ b/"):
            rel_path = line[6:]
            abs_path = src_path / rel_path
            last_file = None
            if abs_path.exists() and abs_path.suffix[1:] in constants.VALID_FILE_EXTENSIONS:
                potential_changed_file = str(Path(rel_path).as_posix())
                if potential_changed_file in changed_files:
                    # try to catch cherry picks
                    last_file = potential_changed_file
                    change_intervals[last_file] = []
        elif line.startswith("@@") and last_file:
            for change in line.split():
                if change.startswith("+"):
                    if constants.INPUT_LINE_NUMBER_SEPARATOR in change:
                        # multiple lines changed
                        change_interval = change[1:].split(constants.INPUT_LINE_NUMBER_SEPARATOR)
                        change_intervals[last_file].append(
                            range(int(change_interval[0]), int(change_interval[0]) + int(change_interval[1])))
                        break
                    else:
                        # single line changed
                        change_intervals[last_file].append(
                            range(int(change[1:]), int(change[1:])))
                        break

    return change_intervals


def find_changes(src_path, branch):
    checkout(branch[1], src_path)
    change_intervals = parse_diff(src_path, *branch)
    xpath_named_unit_name_query = etree.XPath(constants.NAMED_UNIT_NAME_QUERY, namespaces=constants.ns)

    changed_units = {}
    if not change_intervals:
        # empty loops upset the progress bar
        return changed_units

    for rel_path in tqdm(change_intervals.keys(), desc=branch[1]):
        path = (src_path / rel_path).resolve()
        if not path.exists():
            continue

        path = str(path)
        change_interval_condition = ""
        if len(change_intervals[rel_path]) > constants.MAX_FILE_CHANGES:
            change_interval_condition += "(@pos:line>={0} and @pos:line<={1})".format(
                change_intervals[rel_path][0].start, change_intervals[rel_path][-1].stop)
            tqdm.write("too many changes, using pessimistic estimate instead")
        else:
            for change in change_intervals[rel_path]:
                if change_interval_condition:
                    change_interval_condition += " or "
                change_interval_condition += "(@pos:line>={0} and @pos:line<={1})".format(change.start, change.stop)

        xpath_named_unit_pos_query = etree.XPath("//*[({0}) and descendant-or-self::node()[{1}]]".format(
            constants.NAMED_UNIT_QUERY, change_interval_condition), namespaces=constants.ns)

        extensions = ["--register-ext", rel_path.split(".")[-1] + "=C++"]
        counter = 0
        xml = None
        while not xml:
            try:
                xml = sp.check_output([*constants.SRCML_BASE_CALL, constants.SRCML_POSITION, *extensions, path],
                                      timeout=60)
            except sp.CalledProcessError:
                # retry, srcml occasionally crashes
                counter += 1
                if counter > 3:
                    print("multiple crashes occured at {}".format(path))
                    raise
            except sp.TimeoutExpired:
                tqdm.write("timeout while parsing {}".format(str((src_path / path).resolve())))
                break

        if xml:
            parser = etree.XMLParser(recover=True)
            root = etree.fromstring(xml, parser=parser)
            root = xpath_named_unit_pos_query(root)

            for node in root:
                text, _ = precompute.get_named_unit_name(xpath_named_unit_name_query, node)
                if text:
                    changed_units.setdefault(rel_path, set([])).add(text)
    return changed_units


# collect optional data about the call graph
def call_graph_analysis(graph):
    analysis_time = time.time()

    print("graph dimensions: {}".format(graph.shape))
    print("number of connections: {}".format(graph.nnz))
    comp_number, labels = csgraph.connected_components(graph, return_labels=True)
    print("number of connected components: {}".format(comp_number))
    _, u_counts = np.unique(labels, return_counts=True)
    u_counts.sort()
    print("size of the ten largest connected components: {}".format(u_counts[-10:]))
    print("analysis: --- {0:.2f} seconds ---".format(time.time() - analysis_time))


# Find the earliest points of overlap in the call graph between the calling units
# This prevents callers of the affected unit to show up as new affected units
def find_earliest_caller(units, overlap, predecessors):
    unit_1, unit_2 = units
    predecessors_1, predecessors_2 = predecessors

    paths_to_units = []
    for caller in overlap:
        paths_to_units_candidate = (
            find_path_to_unit(caller, unit_1, predecessors_1), find_path_to_unit(caller, unit_2, predecessors_2))
        if paths_to_units_candidate[0] and paths_to_units_candidate[1] and len(
                set(paths_to_units_candidate[0]).intersection(paths_to_units_candidate[1])) <= 1:
            # should never be less than one, as both paths contain the same origin
            paths_to_units.append(paths_to_units_candidate)
    return sorted(paths_to_units, key=path_length_sort_key)



def find_path_to_unit(caller, unit, predecessors):
    path = [caller]
    while path[-1] != unit:
        if path[-1] in predecessors:
            path.append(predecessors[path[-1]])
        else:
            return None
    return path


# export final results
def save_potential_conflicts(potential_conflicts):
    # build ranking
    ranking = {}
    pairs = {}
    for conflict in potential_conflicts:
        units = set(conflict.get("conflicting units", []))
        for unit in units:
            ranking[unit] = ranking.get(unit, 0) + 1
        branches = conflict.get("branch revisions", [])
        if len(branches) == 2:
            branches_a = branches[0]
            branches_b = branches[1]
            for branch_a in branches_a:
                pairs.setdefault(branch_a, {})
                for branch_b in branches_b:
                    if branch_a == branch_b:
                        continue

                    pairs.setdefault(branch_b, {})

                    count_a = pairs[branch_a].setdefault(branch_b, 0)
                    pairs[branch_a][branch_b] = count_a + 1

                    count_b = pairs[branch_b].setdefault(branch_a, 0)
                    pairs[branch_b][branch_a] = count_b + 1

    ranking = list(ranking.items())
    ranking.sort(reverse=True, key=itemgetter(1))

    result = {"number_of_conflicts": len(potential_conflicts),
              "conflicting_branches": pairs,
              "ranking": ranking,
              "conflicts": potential_conflicts}
    potential_conflicts_minimal = []

    print("save potential_conflicts_transitive_{}.json...".format(constants.MAX_TRANSITIVE_INCLUDE_LEVEL))
    with open("potential_conflicts_transitive_{}.json".format(constants.MAX_TRANSITIVE_INCLUDE_LEVEL), 'w') as fp:
        ujson.dump(result, fp, indent=4)

    for conflict in potential_conflicts:
        potential_conflicts_minimal.append({"conflicting units": conflict["conflicting units"],
                                            "branch revisions": conflict["branch revisions"],
                                            "shortest path:": conflict["call paths"][0]})

    result_minimal = {"number_of_conflicts": len(potential_conflicts),
                      "conflicting_branches": pairs,
                      "ranking": ranking,
                      "conflicts": potential_conflicts_minimal}

    print("save potential_conflicts_transitive_{}_minimal.json...".format(constants.MAX_TRANSITIVE_INCLUDE_LEVEL))
    with open("potential_conflicts_transitive_{}_minimal.json".format(constants.MAX_TRANSITIVE_INCLUDE_LEVEL),
              'w') as fp:
        ujson.dump(result_minimal, fp, indent=4)

    print("save complete")


# sort conflicts by the distance between their conflicting units
def potential_conflict_sort_key(potential_conflict):
    min_length = np.inf
    for path_pair in potential_conflict["call paths"]:
        new_length = path_length_sort_key(path_pair)
        if new_length < min_length:
            min_length = new_length
    return min_length


# sort all potential conflicts
def path_length_sort_key(path_pair):
    length = len(path_pair[0]) + len(path_pair[1])
    if len(path_pair[0]) == 1 or len(path_pair[1]) == 1:
        # prioritize paths originating directly from a changed unit
        length -= 0.5
    return length


def perform_merge(master, branches, src_path):
    checkout(master, src_path)
    print("performing temporary merge")
    contributions = []
    for branch in branches:
        contributions.append(branch[1])
    sp.run([*constants.GIT_CALL, str(src_path.resolve()), "merge", "--no-commit", "--no-ff", *contributions])


def abort_merge(src_path):
    print("reverting temporary merge")
    sp.run([*constants.GIT_CALL, str(src_path.resolve()), "merge", "--abort"])


def checkout(branch, src_path):
    print("checking out {}".format(branch))
    sp.run([*constants.GIT_CALL, str(src_path.resolve()), "checkout", branch])

# Delete preprocessed files, that have been changed by the merge.
def delete_dirty_files(dirty_files):
    if dirty_files:
        for rel_path in tqdm(dirty_files, desc="deleting temporary files"):
            path = constants.DUMP_FOLDER_JSON / rel_path
            if path.exists():
                path.unlink()


# Find preprocessed files, that have been changed by the merge.
def get_dirty_files(src_path, master):
    dirty_files = set([])
    output = sp.check_output([*constants.GIT_CALL, str(src_path.resolve()), "diff", "--name-only", master])
    output = str(output, 'utf-8')
    output = output.split("\n")

    for rel_path in output:
        abs_path = src_path / rel_path
        if abs_path.exists:
            dirty_files.add(str(abs_path.relative_to(src_path).as_posix()) + ".json")

    return dirty_files


# Find pairs of units with replacement and without considering their order
def pairs(*sets):
    scanned = set([])
    for t in itertools.combinations(sets, 2):
        for pair in itertools.product(*t):
            if pair not in scanned:
                scanned.add(pair)
                yield pair


def main():
    src_path, master, branches = parse_input()
    perform_merge(master, branches, src_path)
    precompute.parse_source_code(src_path, changed_files=get_changed_files(src_path))
    delete_dirty_files(get_dirty_files(src_path, master))
    abort_merge(src_path)
    io.save_last_scanned_revision(master)
    precompute.build_call_graph()

    called_by_graph = load_npz("called_by_graph.npz")

    id_to_named_unit, named_unit_to_id = io.load_id_dicts()

    call_graph_analysis(called_by_graph)

    unit_id_to_branch_revision = {}
    branch_revision_to_unit_id = {}
    changed_ids = set([])
    for branch in branches:
        changed_units = find_changes(src_path, branch)
        branch_revision_to_unit_id[branch[1]] = set([])
        for key, value in changed_units.items():
            for unit in value:
                unit_id = named_unit_to_id.get((key, unit), None)
                if unit_id:
                    if unit_id not in unit_id_to_branch_revision:
                        unit_id_to_branch_revision[unit_id] = {branch[1]}
                    else:
                        unit_id_to_branch_revision[unit_id].add(branch[1])
                    branch_revision_to_unit_id[branch[1]].add(unit_id)
                    changed_ids.add(unit_id)

    checkout(master, src_path)

    callers = {}
    predecessors = {}
    for unit_id in tqdm(changed_ids, desc="find callers"):

        dist, pred = csgraph.dijkstra(called_by_graph, return_predecessors=True, indices=[unit_id],
                                      limit=constants.MAX_PATH_LENGTH)
        _, Y = np.where(dist <= constants.MAX_PATH_LENGTH)
        callers[unit_id] = set(Y)
        _, Y = np.where(pred >= 0)
        predecessors[unit_id] = {}
        for y in Y:
            predecessors[unit_id][y] = pred[0, y]

    potential_conflicts = []

    for unit_1, unit_2 in tqdm(pairs(*branch_revision_to_unit_id.values()),
                               desc="examining units pairwise"):

        overlap = callers[unit_1].intersection(callers[unit_2])
        if overlap:
            path_pairs = find_earliest_caller((unit_1, unit_2), overlap, (predecessors[unit_1], predecessors[unit_2]))

            readable_paths = []
            for paths in path_pairs:
                readable_pair = []
                for path in paths:
                    readable_path = [id_to_named_unit[unit_id] for unit_id in path]
                    readable_pair.append(readable_path)
                readable_paths.append(readable_pair)

            if readable_paths:
                potential_conflicts.append({"conflicting units": [id_to_named_unit[unit_1], id_to_named_unit[unit_2]],
                                            "branch revisions": [unit_id_to_branch_revision[unit_1],
                                                                 unit_id_to_branch_revision[unit_2]],
                                            "call paths": readable_paths})

    save_potential_conflicts(sorted(potential_conflicts, key=potential_conflict_sort_key))


if __name__ == "__main__":
    start_time = time.time()
    main()
    print("--- {0:.2f} seconds ---".format(time.time() - start_time))
