"""Population brackets: bill wording parsed into population tests (parse) and resolved against the census (index)."""
from atlas.feeds.brackets.index import (BRACKET_BILL, BRACKET_FORMAT, BRACKET_LIST_MAX, NEAR_SHARE, POPULATION_FORMAT,
                                        build_brackets, default_census, load_population, write_brackets)
from atlas.feeds.brackets.parse import bill_brackets, bracket_bounds
