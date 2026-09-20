# Contributing to OpenAI Realtime Voice Assistant

Thank you for your interest in contributing! Here are some guidelines to help you get started.

## Development Setup

1. Fork the repository
2. Clone your fork
3. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Code Style

- Follow PEP 8 style guidelines
- Use type hints where possible
- Add docstrings to functions and classes
- Keep functions focused and single-purpose

## Testing

Before submitting a PR:

1. Test your changes in a live Home Assistant instance
2. Verify the integration loads without errors
3. Test all configuration options
4. Check logs for warnings or errors

## Submitting Changes

1. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Make your changes
3. Commit with clear messages:
   ```bash
   git commit -m "Add feature: description"
   ```
4. Push to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```
5. Create a Pull Request

## Pull Request Guidelines

- Provide a clear description of the changes
- Reference any related issues
- Include screenshots/videos if UI changes are involved
- Ensure all tests pass
- Update documentation if needed

## Reporting Issues

When reporting issues, please include:

- Home Assistant version
- Integration version
- Relevant logs (enable debug logging)
- Steps to reproduce
- Expected vs actual behavior

## Feature Requests

We welcome feature requests! Please:

- Check if the feature already exists or is planned
- Provide a clear use case
- Describe the expected behavior
- Consider implementation complexity

## Code of Conduct

- Be respectful and inclusive
- Welcome newcomers
- Focus on constructive feedback
- Help others learn and grow

Thank you for contributing!
