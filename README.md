# Detecting-Higher-Order-Merge-Conflicts-in-Large-Software-Projects

## Dependencies:
- python	3.7
- lxml	4.3.0
- numpy	1.16.0
- scipy	1.2.0
- tqdm	4.28.1
- ujson	1.35

## Usage

Run "find_conflicts.py" with the following arguments:

path to the source directory of the repository
current revision of the master branch as hash value given by "git rev-parse"
any number of pairs of master revision and branch revision, with which the merge was requested, separated by "-"


This tool was presented at ICST 2020. It and its background are further described in this paper: https://ieeexplore.ieee.org/document/9159072.
