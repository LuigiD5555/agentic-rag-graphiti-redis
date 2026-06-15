from src.utils.file_operations import sort_paths_by_size_desc
from pytest_readable import readable



@readable(
    intent="Verify sort paths by size desc.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the sort paths by size desc behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_sort_paths_by_size_desc(tmp_path):
    large = tmp_path / "z_large.txt"
    medium = tmp_path / "a_medium.txt"
    small = tmp_path / "b_small.txt"
    tie1 = tmp_path / "c_same.txt"
    tie2 = tmp_path / "B_same.txt"

    large.write_bytes(b"x" * 50)
    medium.write_bytes(b"x" * 20)
    small.write_bytes(b"x" * 5)
    tie1.write_bytes(b"x" * 10)
    tie2.write_bytes(b"x" * 10)

    ordered = sort_paths_by_size_desc(
        [str(small), str(tie1), str(large), str(tie2), str(medium)]
    )

    assert ordered == [
        str(small),
        str(tie2),
        str(tie1),
        str(medium),
        str(large),
    ]
