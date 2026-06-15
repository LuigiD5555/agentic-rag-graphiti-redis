# Infrastructure and configuration verification tests

This directory contains infrastructure tests that verify the system is correctly configured before startup:

- **Volume Checks** ([test_volumes.py](test_volumes.py)): Verify external volumes and set up fallbacks

## Test Categories

1. **System Commands**: Verify required commands are installed
2. **Configuration Files**: Validate configuration files
   - Valid and well-formed YAML
3. **Podman Configuration**: Verify Podman configuration
   - Podman is running and accessible
   - Podman version

## Integration with start-everything.sh

If any check fails, the script asks whether you want to continue anyway.

## Volume Tests

Tests to verify external volumes are available and set up fallback directories when needed.

### Basic Usage

```bash
# Run all volume tests (verification only)
pytest -m volumes
```

### Markers

Tests include special markers for selective execution:

```bash
# Run only volume tests
pytest -m volumes
```

### Command Line Options

- `--setup-fallback`: Create fallback directories when volumes are not accessible
  - Without this option, only verifies and reports status
  - With this option, sets up fallbacks automatically

### What the Tests Do

1. **TestVolumeAccessibility**: Verifies we can detect whether volumes are accessible
2. **TestFallbackSetup**: Verifies creation of fallback directories
   - `test_fallback_directory_creation`: Verify directory creation
   - `test_volume_marker_creation`: Verify marker creation
3. **TestVolumeIntegration**: Full integration test
   - `test_libros_volume_with_fallback_setup`: Full verification and setup flow
   - `test_env_file_update`: Verify `.env` update

### Integration with start-everything.sh (Volumes)

1. Verify external volumes are available
2. If not, create fallback directories automatically

### Benefits

1. **Testable**: Each function has unit tests
2. **Maintainable**: Clearer and more structured code
3. **Reusable**: Can be imported as a module
