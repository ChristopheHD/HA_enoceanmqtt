## Security Vulnerability Fixes

### Avoid Broad Exceptions
- **Issue**: Using a bare `except:` clause (e.g., in JSON parsing) is dangerous because it can inadvertently catch and suppress critical system exceptions like `KeyboardInterrupt` or `SystemExit`.
- **Solution**: Always catch specific exceptions (e.g., `ValueError`, `TypeError` for JSON parsing) to handle expected failure modes while allowing system-level signals to pass through.
