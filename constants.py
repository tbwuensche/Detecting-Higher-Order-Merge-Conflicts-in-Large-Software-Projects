from pathlib import Path


VALID_FILE_EXTENSIONS = ["C", "H", "c", "h", "cpp", "hpp", "cxx", "hxx", "c++", "h++", "cc", "hh", "inl", "inc"]

TAGS = {"unit": "{http://www.srcML.org/srcML/src}unit",
        "include": "{http://www.srcML.org/srcML/cpp}include",
        "operator": "{http://www.srcML.org/srcML/src}operator",
        "name": "{http://www.srcML.org/srcML/src}name",
        "argument_list": "{http://www.srcML.org/srcML/src}argument_list",
        "index": "{http://www.srcML.org/srcML/src}index",
        "modifier": "{http://www.srcML.org/srcML/src}modifier",
        "typename": "{http://www.srcML.org/srcML/src}typename",
        "comment": "{http://www.srcML.org/srcML/src}comment",
        "block": "{http://www.srcML.org/srcML/src}block",
        "position": "{http://www.srcML.org/srcML/position}position"}

ns = {"cpp": "http://www.srcML.org/srcML/cpp",
      "src": "http://www.srcML.org/srcML/src",
      "pos": "http://www.srcML.org/srcML/position"}

NAMED_UNIT_QUERY = "self::src:constructor or " \
                   "self::src:constructor_decl or " \
                   "self::src:function[not(@type='operator')] or " \
                   "self::src:function_decl[not(@type='operator')] or " \
                   "self::src:destructor or " \
                   "self::src:destructor_decl or " \
                   "self::src:class[not(ancestor::src:template)] or " \
                   "self::src:class_decl[not(ancestor::src:template)] or " \
                   "self::src:struct or " \
                   "self::src:struct_decl or " \
                   "self::src:enum or" \
                   "self::src:typedef or " \
                   "self::src:union or " \
                   "self::src:block/preceding-sibling::*[1][self::src:macro] or " \
                   "self::src:decl[parent::src:decl_stmt[parent::src:block[parent::src:namespace]]]"


NAMED_UNIT_NAME_QUERY = "./src:name[1]"

CALLING_UNIT_QUERY = "self::src:call or" \
                     "self::src:type"

INCLUDES = "includes"
CALLED_BY = "called_by"
CALLS = "calls"
CALLS_NAIVE = "calls_naive"
DUMP_FILE = "preprocessed_files.xml"
DUMP_FOLDER_JSON = Path("preprocessed_files/json/")
DUMP_PATH_LIST = Path("preprocessed_files_paths.json")
LAST_SCANNED_REVISION = Path("preprocessed_files/last_scanned_revision.txt")

SRCML_BASE_CALL = ["srcml"]
SRCML_POSITION = "--position"
GIT_CALL = ["git", "-C"]
INPUT_LINE_NUMBER_SEPARATOR = ","

OUT_OF_DATE = True
MAX_TRANSITIVE_INCLUDE_LEVEL = 1

CHANGES = "_changes.txt"

MAX_PATH_LENGTH = 1
MAX_FILE_CHANGES = 500
BRANCH_SEPARATOR = "-"
