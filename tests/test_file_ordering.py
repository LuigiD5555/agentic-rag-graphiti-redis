from src.storage.vector.utils import sort_paths_by_size_desc


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
        str(large),
        str(medium),
        str(tie2),
        str(tie1),
        str(small),
    ]
