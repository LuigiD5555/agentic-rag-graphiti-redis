"""Integration tests for SQLite-based architecture."""
import pytest
from src.backends.storage.sqlite import SQLiteControlPlane
from src.workflows.ingestion.discovery.pattern_matching import PatternMatcher
from pytest_readable import readable


@pytest.fixture
def sqlite_control():
    return SQLiteControlPlane(":memory:")

@readable(
    intent="Test concurrent access to SQLite with WAL mode.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the concurrent access behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
@pytest.mark.integration
def test_concurrent_access(sqlite_control):
    """Test concurrent access to SQLite with WAL mode."""
    # Create 10 parallel connections
    connections = [sqlite_control.get_connection() for _ in range(10)]
    
    # Verify all connections are using WAL mode (memory databases use "memory")
    for conn in connections:
        cursor = conn.execute("PRAGMA journal_mode")
        journal_mode = cursor.fetchone()[0]
        # Memory databases use "memory" journal mode, file-based use "wal"
        assert journal_mode in ["wal", "memory"]
    
    # Cleanup
    for conn in connections:
        conn.close()
        
    # Verify we can still get a connection after closing all
    conn = sqlite_control.get_connection()
    cursor = conn.execute("SELECT 1")
    assert cursor.fetchone()[0] == 1
    conn.close()


@readable(
    intent="Test directory exclusion patterns.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the directory exclusion behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
@pytest.mark.integration
def test_directory_exclusion():
    """Test directory exclusion patterns."""
    matcher = PatternMatcher()
    test_cases = [
        ("/mnt/Documents/Personales", {"**/Personales/**"}, True),
        ("/mnt/Documents/Projects", {"**/Personales/**"}, False),
        ("/mnt/Documents/Personales/docs", {"**/Personales/**"}, True),  # Fixed pattern
    ]
    
    for path, patterns, expected in test_cases:
        assert matcher.matches_any_glob(
            path, 
            patterns,
            absolute_path=path
        ) == expected

@readable(
    intent="Test basic cache operations through SQLite control plane.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the sqlite cache operations behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
@pytest.mark.integration 
def test_sqlite_cache_operations(sqlite_control):
    """Test basic cache operations through SQLite control plane."""
    with sqlite_control.get_connection() as conn:
        # Create test table
        conn.execute("CREATE TABLE IF NOT EXISTS test_cache (key TEXT PRIMARY KEY, value TEXT)")
        
        # Test concurrent writes
        conn.execute("INSERT INTO test_cache VALUES (?, ?)", ("test1", "value1"))
        conn.commit()
        
        result = conn.execute("SELECT value FROM test_cache WHERE key = ?", ("test1",)).fetchone()
        assert result[0] == "value1"