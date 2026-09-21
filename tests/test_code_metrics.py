from dsm_ae.litellm_client import _clean_main, _sloppy_main
from dsm_ae.packs.slop_indicator import analyze_code


def test_sloppy_more_eroded_than_clean():
    clean = analyze_code(_clean_main(2))
    sloppy = analyze_code(_sloppy_main(2))
    assert sloppy["max_cc"] >= clean["max_cc"]
    assert sloppy["erosion"] >= clean["erosion"] or sloppy["verbosity"] > clean["verbosity"]
