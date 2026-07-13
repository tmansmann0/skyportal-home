from skyportal.figures import DATABASE_RECORDS, FIGURE_VARIANTS, FIGURES, identify, identify_all_present, identify_present


def test_all_generation_database_is_loaded():
    assert len(DATABASE_RECORDS) == 684
    assert len(FIGURE_VARIANTS) == 683
    assert len(FIGURES) == 345
    assert identify(100, 4096)["name"] == "Jet-Vac"
    assert identify(601, 20480)["name"] == "King Pen"


def test_variant_and_new_elements_are_identified():
    assert identify(100, 5123)["name"] == "Legendary Jet-Vac"
    assert identify(482, 12288)["name"] == "Knight Light"
    assert identify(482, 12288)["element"] == "light"
    assert identify(485, 12288)["element"] == "dark"


def test_unknown_variant_falls_back_to_character():
    figure = identify(100, 65535)
    assert figure["name"] == "Jet-Vac"
    assert figure["variant_id"] == 65535
    assert not figure["variant_known"]


def test_unknown_figure_is_safe():
    figure = identify(9998, 4)
    assert figure["name"] == "Unknown figure #9998"
    assert figure["element"] == "unknown"


def test_swap_force_halves_are_treated_as_two_characters():
    figures = identify_all_present([(2004, 8192), (1004, 8192)])
    assert [(figure["name"], figure["element"], figure["swap_half"]) for figure in figures] == [
        ("Blast", "fire", "top"),
        ("Zone", "fire", "bottom"),
    ]


def test_swap_force_variant_name_is_preserved():
    figures = identify_all_present([(2015, 9218), (1015, 9218)])
    assert [figure["name"] for figure in figures] == ["Dark Wash", "Dark Buckler"]
    assert [figure["element"] for figure in figures] == ["water", "water"]


def test_multiple_figures_are_preserved_with_both_swap_halves():
    figures = identify_all_present([(2004, 8192), (1004, 8192), (100, 4096)])
    assert [figure["name"] for figure in figures] == ["Blast", "Zone", "Jet-Vac"]


def test_mixed_swap_uses_each_original_characters_element():
    figures = identify_all_present([(2004, 8192), (1015, 8192)])
    assert [(figure["name"], figure["element"]) for figure in figures] == [
        ("Blast", "fire"), ("Buckler", "water"),
    ]


def test_magic_items_are_classified_as_power_ups():
    assert identify(202, 0)["name"] == "Healing Elixir"
    assert identify(202, 0)["kind"] == "power_up"
    assert identify(100, 4096)["kind"] == "figure"
